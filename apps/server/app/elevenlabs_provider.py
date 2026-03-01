"""ElevenLabs Scribe v2 Realtime provider for audio transcription."""

import asyncio
import base64
import re
import shutil
from pathlib import Path
from typing import AsyncGenerator, Any

from app.audio_transcription import (
    AudioTranscriptionProvider,
    TranscriptionConfig,
    TranscriptionChunk,
    TranscriptionResult,
    WordTimestamp,
    AudioEncoding,
    TranscriptionProvider,
    TranscriptionProviderFactory,
)


class ElevenLabsProvider(AudioTranscriptionProvider):
    """ElevenLabs Scribe v2 Realtime transcription provider."""

    def __init__(self, config: dict[str, Any]):
        """
        Initialize ElevenLabs provider.

        Config keys:
            - api_key: ElevenLabs API key
            - model_id: Model ID (default: "scribe_v2_realtime")
            - include_timestamps: Enable word-level timestamps (default: True)
        """
        super().__init__(config)

        self.api_key = config["api_key"]
        self.model_id = config.get("model_id", "scribe_v2")  # 文件转录模型
        self.include_timestamps = config.get("include_timestamps", True)
        self.vad_silence_threshold_secs = config.get(
            "vad_silence_threshold_secs", 1.0)
        self.vad_threshold = config.get("vad_threshold", 0.4)
        self.min_speech_duration_ms = config.get("min_speech_duration_ms", 100)
        self.min_silence_duration_ms = config.get(
            "min_silence_duration_ms", 120)

        # Import ElevenLabs SDK (lazy import to avoid dependency issues)
        try:
            from elevenlabs import ElevenLabs
            from elevenlabs.realtime.scribe import CommitStrategy as _CommitStrategy
            self.elevenlabs = ElevenLabs(api_key=self.api_key)
            # Map string config to enum
            _commit_map = {"vad": _CommitStrategy.VAD, "manual": _CommitStrategy.MANUAL}
            raw_commit = config.get("commit_strategy", "vad")
            self.commit_strategy: _CommitStrategy = _commit_map.get(
                raw_commit, _CommitStrategy.VAD
            )
        except ImportError:
            raise ImportError(
                "elevenlabs package is required for ElevenLabs provider. "
                "Install with: pip install elevenlabs"
            )

    def _validate_config(self) -> None:
        """Validate ElevenLabs configuration."""
        required_keys = ["api_key"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "elevenlabs"

    def _map_encoding_to_format(self, encoding: AudioEncoding) -> str:
        """Map encoding to format string for ElevenLabs."""
        # ElevenLabs automatically handles various formats via ffmpeg
        format_map = {
            AudioEncoding.OPUS: "opus",
            AudioEncoding.MP3: "mp3",
            AudioEncoding.MP4: "mp4",
            AudioEncoding.WAV: "wav",
            AudioEncoding.WEBM: "webm",
        }

        result = format_map.get(encoding)
        if result is None:
            # Default to opus for unsupported formats
            return "opus"
        return result

    @staticmethod
    def _pcm_audio_format_for_sample_rate(audio_format_cls: Any, sample_rate: int):
        """Map sample rate to ElevenLabs PCM audio format enum."""
        pcm_format_map = {
            8000: audio_format_cls.PCM_8000,
            16000: audio_format_cls.PCM_16000,
            22050: audio_format_cls.PCM_22050,
            24000: audio_format_cls.PCM_24000,
            44100: audio_format_cls.PCM_44100,
            48000: audio_format_cls.PCM_48000,
        }
        return pcm_format_map.get(sample_rate)

    @staticmethod
    def _coerce_audio_format(audio_format_cls: Any, value: Any) -> Any:
        """Coerce SDK audio format value to enum member when possible.

        Some SDK versions expose AudioFormat members as strings, while connect()
        may expect enum members and access `.value` internally.
        """
        if value is None:
            return None

        if hasattr(value, "value"):
            return value

        # Try direct enum construction from string value.
        if isinstance(value, str):
            try:
                candidate = audio_format_cls(value)
                if hasattr(candidate, "value"):
                    return candidate
            except Exception:
                pass

            # Try class attribute lookup (e.g. "pcm_16000" -> "PCM_16000").
            attr_name = value.upper()
            candidate = getattr(audio_format_cls, attr_name, None)
            if candidate is not None and hasattr(candidate, "value"):
                return candidate

        return value

    @staticmethod
    def _ensure_value_like(value: Any) -> Any:
        """Ensure value has a `.value` attribute for SDKs that expect enum-like objects."""
        if value is None or hasattr(value, "value"):
            return value

        class _ValueAdapter:
            def __init__(self, raw: Any):
                self.value = raw

        return _ValueAdapter(value)

    @staticmethod
    def _ffmpeg_input_format_for_encoding(encoding: AudioEncoding) -> str | None:
        """Map encoding to ffmpeg demuxer format (for streaming decode from stdin)."""
        ffmpeg_input_map = {
            AudioEncoding.WEBM: "webm",
            AudioEncoding.OPUS: "webm",  # browser opus chunks are typically in webm container
            AudioEncoding.MP3: "mp3",
            AudioEncoding.MP4: "mp4",
            AudioEncoding.M4A: "ipod",
            AudioEncoding.WAV: "wav",
            AudioEncoding.MPEG: "mpeg",
            AudioEncoding.MPGA: "mp3",
        }
        return ffmpeg_input_map.get(encoding)

    async def _transcode_stream_to_pcm16(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        input_format: str,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> AsyncGenerator[bytes, None]:
        """Transcode streamed audio bytes to raw PCM s16le using ffmpeg."""
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg is required for ElevenLabs realtime transcoding but was not found in PATH"
            )

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            input_format,
            "-i",
            "pipe:0",
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        feeder_error: Exception | None = None

        async def feed_stdin() -> None:
            nonlocal feeder_error
            try:
                async for chunk in audio_stream:
                    if not chunk:
                        continue
                    process.stdin.write(chunk)
                    await process.stdin.drain()
                process.stdin.close()
            except Exception as exc:
                feeder_error = exc
                try:
                    process.stdin.close()
                except Exception:
                    pass

        feeder_task = asyncio.create_task(feed_stdin())

        try:
            while True:
                pcm_chunk = await process.stdout.read(4096)
                if not pcm_chunk:
                    break
                yield pcm_chunk
        finally:
            await feeder_task
            stderr_output = (await process.stderr.read()).decode("utf-8", errors="ignore")
            return_code = await process.wait()

            if feeder_error is not None:
                raise RuntimeError(
                    f"Error feeding ffmpeg stream: {feeder_error}")

            if return_code != 0:
                raise RuntimeError(
                    f"ffmpeg transcoding failed (exit={return_code}): {stderr_output.strip()}"
                )

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        config: TranscriptionConfig,
    ) -> AsyncGenerator[TranscriptionChunk, None]:
        """
        Transcribe audio stream using ElevenLabs Scribe v2 Realtime.

        This uses WebSocket-based streaming with manual audio chunking.
        """
        try:
            from elevenlabs import RealtimeEvents
            from elevenlabs.realtime.scribe import AudioFormat
        except ImportError:
            raise ImportError("elevenlabs package is required")

        # Queue for passing transcripts from event handlers to async generator
        transcript_queue: asyncio.Queue[TranscriptionChunk |
                                        Exception] = asyncio.Queue()
        stop_event = asyncio.Event()
        last_partial_text = ""
        last_final_text = ""

        # ElevenLabs realtime manual chunk mode expects raw PCM/ULAW bytes.
        # Browser stream chunks are containerized/compressed (e.g. webm+opus),
        # so we transcode those to PCM16 first.
        target_sample_rate = 16000
        target_audio_format = self._coerce_audio_format(
            AudioFormat,
            AudioFormat.PCM_16000,
        )
        target_audio_format = self._ensure_value_like(target_audio_format)

        raw_audio_stream: AsyncGenerator[bytes, None]
        if config.encoding == AudioEncoding.LINEAR16:
            # If caller already provides LINEAR16, try to use direct mode.
            requested_sample_rate = config.sample_rate or 16000
            mapped_format = self._pcm_audio_format_for_sample_rate(
                AudioFormat, requested_sample_rate)
            mapped_format = self._coerce_audio_format(
                AudioFormat, mapped_format)
            mapped_format = self._ensure_value_like(mapped_format)
            if mapped_format is not None:
                target_sample_rate = requested_sample_rate
                target_audio_format = mapped_format
                raw_audio_stream = audio_stream
            else:
                # Unsupported PCM rate for ElevenLabs API; resample via ffmpeg.
                raw_audio_stream = self._transcode_stream_to_pcm16(
                    audio_stream,
                    input_format="s16le",
                    sample_rate=target_sample_rate,
                    channels=1,
                )
        else:
            ffmpeg_input_format = self._ffmpeg_input_format_for_encoding(
                config.encoding)
            if ffmpeg_input_format is None:
                raise ValueError(
                    f"Unsupported streaming encoding for ElevenLabs: {config.encoding}"
                )
            raw_audio_stream = self._transcode_stream_to_pcm16(
                audio_stream,
                input_format=ffmpeg_input_format,
                sample_rate=target_sample_rate,
                channels=1,
            )

        # Connect to ElevenLabs realtime API
        try:
            connect_options = {
                "model_id": "scribe_v2_realtime",
                # Required for manual audio mode.
                "audio_format": target_audio_format,
                "sample_rate": target_sample_rate,
                "include_timestamps": self.include_timestamps,
            }

            # Some SDK versions accept string commit_strategy, others expect enum-like values.
            # Keep it optional to avoid hard failures while preserving required manual-mode fields.
            connect_options["commit_strategy"] = self.commit_strategy

            if self.commit_strategy == "vad":
                connect_options.update({
                    "vad_silence_threshold_secs": self.vad_silence_threshold_secs,
                    "vad_threshold": self.vad_threshold,
                    "min_speech_duration_ms": self.min_speech_duration_ms,
                    "min_silence_duration_ms": self.min_silence_duration_ms,
                })

            try:
                connection = await self.elevenlabs.speech_to_text.realtime.connect(
                    options=connect_options
                )
            except Exception as first_error:
                # SDK compatibility fallback: keep required manual mode fields
                # (audio_format + sample_rate), drop optional strategy fields.
                if "has no attribute 'value'" in str(first_error):
                    fallback_options = {
                        k: v
                        for k, v in connect_options.items()
                        if k
                        not in {
                            "commit_strategy",
                            "vad_silence_threshold_secs",
                            "vad_threshold",
                            "min_speech_duration_ms",
                            "min_silence_duration_ms",
                        }
                    }
                    connection = await self.elevenlabs.speech_to_text.realtime.connect(
                        options=fallback_options
                    )
                else:
                    raise
        except Exception as e:
            raise RuntimeError(f"Failed to connect to ElevenLabs: {e}")

        # Event handlers
        def on_partial_transcript(data):
            """Handle partial transcript events."""
            nonlocal last_partial_text
            text = (data.get("text", "") or "").strip()
            if not text or text == last_partial_text:
                return
            last_partial_text = text
            chunk = TranscriptionChunk(
                text=text,
                is_final=False,
                language=None,  # ElevenLabs doesn't provide language in events
            )
            try:
                transcript_queue.put_nowait(chunk)
            except Exception as e:
                print(f"Error queueing partial transcript: {e}")

        def on_committed_transcript(data):
            """Handle committed transcript events (without timestamps)."""
            nonlocal last_final_text, last_partial_text
            text = (data.get("text", "") or "").strip()
            if not text or text == last_final_text:
                return
            last_final_text = text
            last_partial_text = ""
            chunk = TranscriptionChunk(
                text=text,
                is_final=True,
                language=None,
            )
            try:
                transcript_queue.put_nowait(chunk)
            except Exception as e:
                print(f"Error queueing committed transcript: {e}")

        def on_committed_transcript_with_timestamps(data):
            """Handle committed transcript with word-level timestamps."""
            nonlocal last_final_text, last_partial_text
            words = []
            for word_data in data.get("words", []):
                word = WordTimestamp(
                    word=word_data.get("text", ""),
                    start=word_data.get("start", 0.0),
                    end=word_data.get("end", 0.0),
                )
                words.append(word)

            # Prefer server-provided text to avoid punctuation spacing artifacts;
            # fall back to word join if absent.
            text = (data.get("text") or data.get("transcript") or "").strip()
            if not text:
                text = " ".join(w.word for w in words)
            text = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", text)

            if not text or text == last_final_text:
                return

            last_final_text = text
            last_partial_text = ""

            chunk = TranscriptionChunk(
                text=text,
                is_final=True,
                words=words,
                language=None,
            )
            try:
                transcript_queue.put_nowait(chunk)
            except Exception as e:
                print(f"Error queueing transcript with timestamps: {e}")

        def on_error(error):
            """Handle errors."""
            print(f"ElevenLabs transcription error: {error}")
            try:
                transcript_queue.put_nowait(Exception(str(error)))
            except Exception as e:
                print(f"Error queueing error: {e}")
            stop_event.set()

        def on_close():
            """Handle connection close."""
            stop_event.set()

        # Register event handlers
        connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial_transcript)
        if self.include_timestamps:
            # Avoid duplicate final chunks: when timestamps are enabled, consume
            # only the timestamp variant.
            connection.on(
                RealtimeEvents.COMMITTED_TRANSCRIPT_WITH_TIMESTAMPS,
                on_committed_transcript_with_timestamps,
            )
        else:
            connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT,
                          on_committed_transcript)
        connection.on(RealtimeEvents.ERROR, on_error)
        connection.on(RealtimeEvents.CLOSE, on_close)

        # Background task to send audio chunks to ElevenLabs
        async def send_audio():
            try:
                async for audio_chunk in raw_audio_stream:
                    if audio_chunk:
                        # Encode audio to base64
                        audio_base64 = base64.b64encode(
                            audio_chunk).decode('utf-8')
                        await connection.send({
                            "audio_base_64": audio_base64
                        })
                        await asyncio.sleep(0)  # Yield control
                # Signal end of stream by committing
                await connection.commit()
            except Exception as e:
                print(f"Error sending audio: {e}")
                stop_event.set()

        # Start background task
        send_task = asyncio.create_task(send_audio())

        try:
            # Yield transcripts as they arrive
            while not stop_event.is_set() or not transcript_queue.empty():
                try:
                    # Wait for next transcript with timeout
                    chunk = await asyncio.wait_for(
                        transcript_queue.get(),
                        timeout=0.1
                    )

                    # Check if it's an exception
                    if isinstance(chunk, Exception):
                        raise chunk

                    yield chunk

                except asyncio.TimeoutError:
                    # No transcript available, continue waiting
                    continue
                except Exception as e:
                    print(f"Error in transcript loop: {e}")
                    break

        finally:
            # Cleanup
            stop_event.set()
            await send_task
            try:
                await connection.close()
            except Exception:
                pass

    async def transcribe_file(
        self,
        file_path: Path | bytes,
        config: TranscriptionConfig,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file using ElevenLabs.

        For file transcription, we use a simpler approach that doesn't require
        realtime streaming.
        """
        import tempfile
        import os

        # Write file content to temporary file if it's bytes
        if isinstance(file_path, bytes):
            audio_content = file_path
            # Create temp file with appropriate extension
            temp_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=".wav")
            try:
                temp_file.write(audio_content)
                temp_file.flush()
                temp_file.close()
                file_to_process = Path(temp_file.name)
            except Exception as e:
                temp_file.close()
                os.unlink(temp_file.name)
                raise RuntimeError(f"Failed to write temp file: {e}")
        else:
            file_to_process = file_path
            temp_file = None

        try:
            # Try using ElevenLabs file transcription API if available
            # Use correct parameter name: model_id and file
            with open(str(file_to_process), "rb") as f:
                response = await asyncio.to_thread(
                    self.elevenlabs.speech_to_text.convert,
                    model_id=self.model_id,
                    file=f
                )

            # Parse response
            full_text = response.text if hasattr(response, 'text') else ""
            words = []
            if hasattr(response, 'words') and response.words:
                for word_data in response.words:
                    words.append(WordTimestamp(
                        word=word_data.text if hasattr(
                            word_data, 'text') else str(word_data),
                        start=word_data.start if hasattr(
                            word_data, 'start') else 0.0,
                        end=word_data.end if hasattr(
                            word_data, 'end') else 0.0,
                    ))

            result = TranscriptionResult(
                text=full_text,
                language=response.language_code if hasattr(
                    response, 'language_code') else None,
                segments=[],
                words=words,
                provider=self.get_provider_name(),
                model=self.model_id,
            )

            return result

        finally:
            # Clean up temp file if created
            if temp_file is not None:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass


# Register provider with factory
TranscriptionProviderFactory.register_provider(
    TranscriptionProvider.ELEVENLABS,
    ElevenLabsProvider,
)
