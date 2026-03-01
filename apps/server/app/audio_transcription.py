"""Audio transcription abstraction layer - Base classes and models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator, Any


class AudioEncoding(str, Enum):
    """Supported audio encoding formats."""
    
    OPUS = "opus"
    LINEAR16 = "linear16"
    MP3 = "mp3"
    MP4 = "mp4"
    MPEG = "mpeg"
    MPGA = "mpga"
    M4A = "m4a"
    WAV = "wav"
    WEBM = "webm"


class TranscriptionProvider(str, Enum):
    """Available transcription service providers."""
    
    GOOGLE_SPEECH = "google_speech"
    OPENAI_WHISPER = "openai_whisper"
    ELEVENLABS = "elevenlabs"


@dataclass
class TranscriptionConfig:
    """Configuration for transcription request."""
    
    # Audio settings
    encoding: AudioEncoding = AudioEncoding.OPUS
    sample_rate: int = 48000
    
    # Language settings
    language: str | list[str] = "zh-CN"
    
    # Feature flags
    enable_timestamps: bool = True
    enable_word_timestamps: bool = False
    enable_punctuation: bool = True
    
    # Provider-specific options
    provider_options: dict[str, Any] = field(default_factory=dict)
    
    def get_language_codes(self) -> list[str]:
        """Get language codes as a list."""
        if isinstance(self.language, str):
            return [self.language]
        return self.language


@dataclass
class WordTimestamp:
    """Word-level timestamp information."""
    
    word: str
    start: float  # seconds
    end: float    # seconds
    confidence: float | None = None


@dataclass
class TranscriptionChunk:
    """A chunk of transcription result (for streaming)."""
    
    text: str
    is_final: bool = False
    confidence: float | None = None
    language: str | None = None
    
    # Timestamps
    start_time: float | None = None
    end_time: float | None = None
    words: list[WordTimestamp] = field(default_factory=list)
    
    # Provider-specific data
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptionResult:
    """Complete transcription result."""
    
    text: str
    language: str | None = None
    duration: float | None = None
    
    # Confidence and quality
    confidence: float | None = None
    
    # Timestamps
    segments: list[TranscriptionChunk] = field(default_factory=list)
    words: list[WordTimestamp] = field(default_factory=list)
    
    # Provider info
    provider: str | None = None
    model: str | None = None
    
    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class AudioTranscriptionProvider(ABC):
    """Abstract base class for audio transcription providers."""
    
    def __init__(self, config: dict[str, Any]):
        """
        Initialize provider with configuration.
        
        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self._validate_config()
    
    @abstractmethod
    def _validate_config(self) -> None:
        """Validate provider configuration. Raise ValueError if invalid."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider name."""
        pass
    
    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        config: TranscriptionConfig,
    ) -> AsyncGenerator[TranscriptionChunk, None]:
        """
        Transcribe audio stream in real-time.
        
        Args:
            audio_stream: Async generator yielding audio chunks
            config: Transcription configuration
        
        Yields:
            TranscriptionChunk objects as transcription progresses
        """
        pass
    
    @abstractmethod
    async def transcribe_file(
        self,
        file_path: Path | bytes,
        config: TranscriptionConfig,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.
        
        Args:
            file_path: Path to audio file or raw audio bytes
            config: Transcription configuration
        
        Returns:
            Complete transcription result
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the provider is available and configured correctly.
        
        Returns:
            True if provider is healthy, False otherwise
        """
        try:
            self._validate_config()
            return True
        except Exception:
            return False


class TranscriptionProviderFactory:
    """Factory for creating transcription provider instances."""
    
    _providers: dict[str, type[AudioTranscriptionProvider]] = {}
    
    @classmethod
    def register_provider(
        cls,
        provider_type: TranscriptionProvider,
        provider_class: type[AudioTranscriptionProvider],
    ) -> None:
        """
        Register a transcription provider.
        
        Args:
            provider_type: Provider type identifier
            provider_class: Provider class to register
        """
        cls._providers[provider_type.value] = provider_class
    
    @classmethod
    def create_provider(
        cls,
        provider_type: str | TranscriptionProvider,
        config: dict[str, Any],
    ) -> AudioTranscriptionProvider:
        """
        Create a transcription provider instance.
        
        Args:
            provider_type: Type of provider to create
            config: Provider-specific configuration
        
        Returns:
            Configured provider instance
        
        Raises:
            ValueError: If provider type is not registered
        """
        if isinstance(provider_type, TranscriptionProvider):
            provider_type = provider_type.value
        
        provider_class = cls._providers.get(provider_type)
        if not provider_class:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unknown provider: {provider_type}. "
                f"Available providers: {available}"
            )
        
        return provider_class(config)
    
    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider types."""
        return list(cls._providers.keys())
