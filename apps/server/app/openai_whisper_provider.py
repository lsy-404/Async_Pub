"""OpenAI Whisper API provider for audio transcription."""

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Any
import httpx

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


class OpenAIWhisperProvider(AudioTranscriptionProvider):
    """OpenAI Whisper API transcription provider."""
    
    def __init__(self, config: dict[str, Any]):
        """
        Initialize OpenAI Whisper provider.
        
        Config keys:
            - api_key: OpenAI API key
            - base_url: API base URL (default: "https://api.openai.com/v1")
            - model: Model name (default: "whisper-1")
            - timeout: Request timeout in seconds (default: 60)
        """
        super().__init__(config)
        
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model", "whisper-1")
        self.timeout = config.get("timeout", 60)
        
        # Initialize HTTP client
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
        )
    
    def _validate_config(self) -> None:
        """Validate OpenAI Whisper configuration."""
        required_keys = ["api_key"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")
    
    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai_whisper"
    
    def _map_encoding_to_extension(self, encoding: AudioEncoding) -> str:
        """Map encoding to file extension."""
        extension_map = {
            AudioEncoding.OPUS: "opus",
            AudioEncoding.MP3: "mp3",
            AudioEncoding.MP4: "mp4",
            AudioEncoding.MPEG: "mpeg",
            AudioEncoding.MPGA: "mpga",
            AudioEncoding.M4A: "m4a",
            AudioEncoding.WAV: "wav",
            AudioEncoding.WEBM: "webm",
        }
        
        result = extension_map.get(encoding)
        if result is None:
            raise ValueError(
                f"Unsupported encoding for OpenAI Whisper: {encoding}. "
                f"Supported: {list(extension_map.keys())}"
            )
        return result
    
    async def _call_whisper_api(
        self,
        audio_file: Path | bytes,
        config: TranscriptionConfig,
    ) -> dict[str, Any]:
        """Call OpenAI Whisper API."""
        url = f"{self.base_url}/audio/transcriptions"
        
        # Prepare form data
        files = {}
        if isinstance(audio_file, Path):
            files["file"] = open(audio_file, "rb")
        else:
            # Create file-like object from bytes
            extension = self._map_encoding_to_extension(config.encoding)
            files["file"] = (f"audio.{extension}", audio_file)
        
        # Get primary language
        language = config.get_language_codes()[0] if config.get_language_codes() else None
        if language:
            # Extract language code (e.g., "zh-CN" -> "zh")
            language = language.split("-")[0]
        
        # Prepare form data
        data = {
            "model": self.model,
            "response_format": "verbose_json" if config.enable_timestamps else "json",
        }
        if language:
            data["language"] = language
        if config.enable_word_timestamps:
            data["timestamp_granularities"] = ["word"]
        
        try:
            response = await self.client.post(
                url,
                files=files,
                data=data,
            )
            response.raise_for_status()
            return response.json()
        finally:
            # Close file if we opened it
            if isinstance(audio_file, Path) and "file" in files:
                files["file"].close()
    
    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        config: TranscriptionConfig,
    ) -> AsyncGenerator[TranscriptionChunk, None]:
        """
        Transcribe audio stream using OpenAI Whisper.
        
        Note: OpenAI Whisper doesn't support true streaming.
        This method buffers the entire stream and then transcribes it.
        """
        # Buffer the entire stream
        audio_buffer = bytearray()
        async for chunk in audio_stream:
            audio_buffer.extend(chunk)
        
        # Transcribe the buffered audio
        result = await self.transcribe_file(bytes(audio_buffer), config)
        
        # Convert result to streaming chunks
        if result.segments:
            # Yield segments as chunks
            for segment in result.segments:
                yield segment
        else:
            # Yield single final chunk
            yield TranscriptionChunk(
                text=result.text,
                is_final=True,
                confidence=result.confidence,
                language=result.language,
                words=result.words,
            )
    
    async def transcribe_file(
        self,
        file_path: Path | bytes,
        config: TranscriptionConfig,
    ) -> TranscriptionResult:
        """Transcribe an audio file using OpenAI Whisper."""
        # For bytes input with OPUS encoding, save to temp file
        # (OpenAI API requires file upload)
        temp_file = None
        try:
            if isinstance(file_path, bytes):
                extension = self._map_encoding_to_extension(config.encoding)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=f".{extension}"
                )
                temp_file.write(file_path)
                temp_file.close()
                file_to_use = Path(temp_file.name)
            else:
                file_to_use = file_path
            
            # Call API
            response_data = await self._call_whisper_api(file_to_use, config)
            
            # Parse response
            text = response_data.get("text", "")
            language = response_data.get("language")
            duration = response_data.get("duration")
            
            # Parse segments
            segments = []
            if "segments" in response_data:
                for seg in response_data["segments"]:
                    segment = TranscriptionChunk(
                        text=seg.get("text", ""),
                        is_final=True,
                        start_time=seg.get("start"),
                        end_time=seg.get("end"),
                    )
                    segments.append(segment)
            
            # Parse word timestamps
            words = []
            if "words" in response_data:
                for word_data in response_data["words"]:
                    word = WordTimestamp(
                        word=word_data.get("word", ""),
                        start=word_data.get("start", 0.0),
                        end=word_data.get("end", 0.0),
                    )
                    words.append(word)
            
            result = TranscriptionResult(
                text=text,
                language=language,
                duration=duration,
                segments=segments,
                words=words,
                provider=self.get_provider_name(),
                model=self.model,
            )
            
            return result
            
        finally:
            # Clean up temp file
            if temp_file:
                try:
                    Path(temp_file.name).unlink()
                except Exception:
                    pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()


# Register provider with factory
TranscriptionProviderFactory.register_provider(
    TranscriptionProvider.OPENAI_WHISPER,
    OpenAIWhisperProvider,
)
