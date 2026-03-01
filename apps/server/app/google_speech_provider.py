"""Google Cloud Speech-to-Text provider for audio transcription."""

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Any

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech
from google.api_core.client_options import ClientOptions

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


class GoogleSpeechProvider(AudioTranscriptionProvider):
    """Google Cloud Speech-to-Text (Chirp 2) transcription provider."""

    def __init__(self, config: dict[str, Any]):
        """
        Initialize Google Speech provider.

        Config keys:
            - project_id: Google Cloud project ID
            - location: API location (default: "global")
            - recognizer_id: Recognizer ID (default: "chirp-2-recognizer")
            - credentials_path: Path to service account JSON (optional)
        """
        super().__init__(config)

        self.project_id = config["project_id"]
        self.location = config.get("location", "global")
        self.recognizer_id = config.get("recognizer_id", "chirp-2-recognizer")

        # Initialize client
        client_options = None
        if self.location != "global":
            client_options = ClientOptions(
                api_endpoint=f"{self.location}-speech.googleapis.com"
            )

        # Set credentials if provided
        credentials_path = config.get("credentials_path")
        if credentials_path:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.client = speech_v2.SpeechAsyncClient(
            client_options=client_options)

        # Build recognizer name
        self.recognizer_name = (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"recognizers/{self.recognizer_id}"
        )

    def _validate_config(self) -> None:
        """Validate Google Speech configuration."""
        required_keys = ["project_id"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "google_speech"

    def _map_encoding(self, encoding: AudioEncoding) -> cloud_speech.ExplicitDecodingConfig.AudioEncoding:
        """Map our encoding enum to Google's encoding enum."""
        encoding_map = {
            AudioEncoding.LINEAR16: cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            AudioEncoding.OPUS: cloud_speech.ExplicitDecodingConfig.AudioEncoding.OPUS,
        }

        result = encoding_map.get(encoding)
        if result is None:
            raise ValueError(
                f"Unsupported encoding for Google Speech: {encoding}. "
                f"Supported: {list(encoding_map.keys())}"
            )
        return result

    # Container / self-describing formats that need AutoDetectDecodingConfig
    _AUTO_DETECT_ENCODINGS = {
        AudioEncoding.WEBM,
        AudioEncoding.OPUS,   # browsers always wrap Opus in a WebM container
        AudioEncoding.MP3,
        AudioEncoding.MP4,
        AudioEncoding.M4A,
    }

    def _create_recognition_config(
        self,
        config: TranscriptionConfig,
        model: str = "chirp_2",
    ) -> cloud_speech.RecognitionConfig:
        """Create Google Speech recognition config."""
        recognition_features = cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=config.enable_punctuation,
            enable_word_time_offsets=config.enable_word_timestamps,
        )
        language_codes = config.get_language_codes()

        if config.encoding in self._AUTO_DETECT_ENCODINGS:
            return cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=language_codes,
                model=model,
                features=recognition_features,
            )
        else:
            audio_encoding = self._map_encoding(config.encoding)
            explicit_decoding_config = cloud_speech.ExplicitDecodingConfig(
                encoding=audio_encoding,
                sample_rate_hertz=config.sample_rate,
            )
            return cloud_speech.RecognitionConfig(
                explicit_decoding_config=explicit_decoding_config,
                language_codes=language_codes,
                model=model,
                features=recognition_features,
            )

    def _create_streaming_config(
        self,
        config: TranscriptionConfig,
    ) -> cloud_speech.StreamingRecognitionConfig:
        """Create Google Speech streaming configuration.

        Uses 'latest_long' model for streaming (much lower latency than chirp_2).
        """
        recognition_config = self._create_recognition_config(
            config, model="latest_long")

        # Create streaming config
        streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=cloud_speech.StreamingRecognitionFeatures(
                interim_results=True,
            ),
        )

        return streaming_config

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        config: TranscriptionConfig,
    ) -> AsyncGenerator[TranscriptionChunk, None]:
        """Transcribe audio stream using Google Speech."""
        # Create streaming config
        streaming_config = self._create_streaming_config(config)

        # Generator to produce streaming recognize requests
        async def request_generator():
            # First request with config
            yield cloud_speech.StreamingRecognizeRequest(
                recognizer=self.recognizer_name,
                streaming_config=streaming_config,
            )

            # Subsequent requests with audio content
            async for audio_chunk in audio_stream:
                yield cloud_speech.StreamingRecognizeRequest(audio=audio_chunk)

        # Make streaming recognize call (async client returns Awaitable[AsyncIterable])
        responses = await self.client.streaming_recognize(requests=request_generator())

        # Process responses – a single StreamingRecognizeResponse can contain
        # multiple results covering sequential audio segments.  We must yield
        # each *final* result individually (so the frontend appends it) while
        # combining all *interim* results from the same response into ONE chunk
        # so the frontend doesn't overwrite earlier segments with the latest
        # short interim.
        async for response in responses:
            final_results = []
            interim_results = []

            for result in response.results:
                if not result.alternatives:
                    continue
                if result.is_final:
                    final_results.append(result)
                else:
                    interim_results.append(result)

            # --- Yield each final result individually ---
            for result in final_results:
                alternative = result.alternatives[0]
                words = []
                if config.enable_word_timestamps and alternative.words:
                    words = [
                        WordTimestamp(
                            word=word.word,
                            start=word.start_offset.total_seconds(),
                            end=word.end_offset.total_seconds(),
                        )
                        for word in alternative.words
                    ]
                yield TranscriptionChunk(
                    text=alternative.transcript,
                    is_final=True,
                    confidence=alternative.confidence,
                    language=result.language_code,
                    start_time=words[0].start if words else None,
                    end_time=words[-1].end if words else None,
                    words=words,
                    metadata={
                        "stability": result.stability,
                        "result_end_time": result.result_end_offset.total_seconds() if result.result_end_offset else None,
                    },
                )

            # --- Combine all interim results into ONE chunk ---
            if interim_results:
                combined_text = " ".join(
                    r.alternatives[0].transcript for r in interim_results
                )
                # Merge word timestamps across all interim segments
                all_words: list[WordTimestamp] = []
                if config.enable_word_timestamps:
                    for r in interim_results:
                        alt = r.alternatives[0]
                        if alt.words:
                            all_words.extend(
                                WordTimestamp(
                                    word=w.word,
                                    start=w.start_offset.total_seconds(),
                                    end=w.end_offset.total_seconds(),
                                )
                                for w in alt.words
                            )
                last = interim_results[-1]
                yield TranscriptionChunk(
                    text=combined_text,
                    is_final=False,
                    confidence=None,
                    language=last.language_code,
                    start_time=all_words[0].start if all_words else None,
                    end_time=all_words[-1].end if all_words else None,
                    words=all_words,
                    metadata={
                        "stability": last.stability,
                        "result_end_time": last.result_end_offset.total_seconds() if last.result_end_offset else None,
                    },
                )

    def _create_streaming_config_with_model(
        self,
        config: TranscriptionConfig,
        model: str = "chirp_2",
    ) -> cloud_speech.StreamingRecognitionConfig:
        """Create streaming config with a specific model override."""
        recognition_config = self._create_recognition_config(
            config, model=model)
        return cloud_speech.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=cloud_speech.StreamingRecognitionFeatures(
                interim_results=True,
            ),
        )

    async def _transcribe_stream_with_config(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        config: TranscriptionConfig,
        streaming_config: cloud_speech.StreamingRecognitionConfig,
    ) -> AsyncGenerator[TranscriptionChunk, None]:
        """Internal: transcribe with an explicit streaming config."""
        async def request_generator():
            yield cloud_speech.StreamingRecognizeRequest(
                recognizer=self.recognizer_name,
                streaming_config=streaming_config,
            )
            async for audio_chunk in audio_stream:
                yield cloud_speech.StreamingRecognizeRequest(audio=audio_chunk)

        responses = await self.client.streaming_recognize(requests=request_generator())

        async for response in responses:
            for result in response.results:
                if not result.alternatives:
                    continue

                alternative = result.alternatives[0]
                words = []
                if config.enable_word_timestamps and alternative.words:
                    words = [
                        WordTimestamp(
                            word=word.word,
                            start=word.start_offset.total_seconds(),
                            end=word.end_offset.total_seconds(),
                        )
                        for word in alternative.words
                    ]

                chunk_start_time = words[0].start if words else None
                chunk_end_time = words[-1].end if words else None
                yield TranscriptionChunk(
                    text=alternative.transcript,
                    is_final=result.is_final,
                    confidence=alternative.confidence if result.is_final else None,
                    language=result.language_code,
                    start_time=chunk_start_time,
                    end_time=chunk_end_time,
                    words=words,
                    metadata={
                        "stability": result.stability,
                        "result_end_time": result.result_end_offset.total_seconds() if result.result_end_offset else None,
                    },
                )

    async def transcribe_file(
        self,
        file_path: Path | bytes,
        config: TranscriptionConfig,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file using Google Speech.

        Note: This currently uses streaming API. For production,
        consider using batch transcription API for better performance.
        """
        # Read file content
        if isinstance(file_path, Path):
            with open(file_path, "rb") as f:
                audio_content = f.read()
        else:
            audio_content = file_path

        # Create a simple audio stream from file content
        async def file_stream():
            # Split into chunks of ~64KB
            chunk_size = 65536
            for i in range(0, len(audio_content), chunk_size):
                yield audio_content[i:i + chunk_size]
                await asyncio.sleep(0)  # Yield control

        # For file transcription, use chirp_2 (higher quality, latency is acceptable)
        file_streaming_config = self._create_streaming_config_with_model(
            config, model="chirp_2")

        # Collect all transcription chunks
        full_text = []
        all_words = []
        segments = []
        final_language = None
        final_confidence = None

        async for chunk in self._transcribe_stream_with_config(file_stream(), config, file_streaming_config):
            if chunk.is_final:
                full_text.append(chunk.text)
                if chunk.words:
                    all_words.extend(chunk.words)
                segments.append(chunk)
                if chunk.language:
                    final_language = chunk.language
                if chunk.confidence is not None:
                    final_confidence = chunk.confidence

        # Build complete result
        result = TranscriptionResult(
            text=" ".join(full_text),
            language=final_language,
            confidence=final_confidence,
            segments=segments,
            words=all_words,
            provider=self.get_provider_name(),
            model="chirp_2",
        )

        return result


# Register provider with factory
TranscriptionProviderFactory.register_provider(
    TranscriptionProvider.GOOGLE_SPEECH,
    GoogleSpeechProvider,
)
