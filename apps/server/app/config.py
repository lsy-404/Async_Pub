"""Configuration loader for AI models and system settings."""

import os
import sys
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Python 3.11+ has tomllib built-in, 3.10 needs tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError(
            "tomli is required for Python < 3.11. Install with: pip install tomli"
        )


class AIModelConfig:
    """Configuration for an AI model."""

    def __init__(self, data: dict[str, Any]):
        self.name: str = data.get("name", "")
        self.endpoint: str = data.get("endpoint", "")
        self.api_token: str = data.get("api_token", "")
        self.description: str = data.get("description", "")

    def is_valid(self) -> bool:
        """Check if configuration has required fields."""
        return bool(self.name and self.endpoint and self.api_token)


class WebSearchConfig:
    """Configuration for external web search API."""

    def __init__(self, data: dict[str, Any]):
        self.endpoint: str = data.get("endpoint", "")
        self.api_token: str = data.get("api_token", "")
        self.freshness: str = data.get("freshness", "one_month")
        self.default_count: int = int(data.get("default_count", 5))

    def is_valid(self) -> bool:
        """Check if configuration has required fields."""
        return bool(self.endpoint and self.api_token)


class SystemConfig:
    """System configuration."""

    def __init__(self, data: dict[str, Any]):
        self.session_timeout_minutes: int = data.get(
            "session_timeout_minutes", 60)
        self.max_sessions_per_user: int = data.get("max_sessions_per_user", 10)
        # Load master token strictly from environment variable
        self.master_token: str = os.getenv("ASYNC_MASTER_TOKEN", "")


class MySQLConfig:
    """Configuration for MySQL database."""

    def __init__(self, data: dict[str, Any]):
        self.address: str = data.get("address", "localhost")
        self.port: int = data.get("port", 3306)
        self.username: str = data.get("username", "root")
        self.password: str = data.get("password", "")
        self.database: str = data.get("database", "async_db")

    def get_database_url(self) -> str:
        """Build SQLAlchemy database connection URL."""
        return f"mysql+aiomysql://{self.username}:{self.password}@{self.address}:{self.port}/{self.database}"

    def is_valid(self) -> bool:
        """Check if configuration has required fields."""
        return bool(self.address and self.username and self.database)


class GoogleSpeechConfig:
    """Configuration for Google Cloud Speech-to-Text."""

    def __init__(self, data: dict[str, Any]):
        self.project_id: str = data.get("project_id", "")
        self.location: str = data.get("location", "global")
        self.recognizer_id: str = data.get(
            "recognizer_id", "chirp-2-recognizer")
        self.credentials_path: str = data.get("credentials_path", "")
        self.enabled: bool = data.get("enabled", False)

    def is_valid(self) -> bool:
        """Check if configuration has required fields."""
        return bool(
            self.enabled
            and self.project_id
            and (self.credentials_path or not self.credentials_path)
        )


class AudioTranscriptionConfig:
    """Configuration for audio transcription service."""

    def __init__(self, data: dict[str, Any]):
        self.provider: str = data.get("provider", "google_speech")
        self.default_language: str | list[str] = data.get(
            "default_language", ["zh-CN", "en-US"])
        self.enable_timestamps: bool = data.get("enable_timestamps", True)
        self.enable_word_timestamps: bool = data.get(
            "enable_word_timestamps", False)

        # Provider-specific configurations
        self.google_speech: dict[str, Any] = data.get("google_speech", {})
        self.openai_whisper: dict[str, Any] = data.get("openai_whisper", {})
        self.elevenlabs: dict[str, Any] = data.get("elevenlabs", {})

    def get_provider_config(self) -> dict[str, Any]:
        """Get configuration for the selected provider."""
        if self.provider == "google_speech":
            return self.google_speech
        elif self.provider == "openai_whisper":
            return self.openai_whisper
        elif self.provider == "elevenlabs":
            return self.elevenlabs
        else:
            return {}

    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return bool(self.provider and self.get_provider_config())


class Config:
    """Main configuration container."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._load()

    def _load(self):
        """Load configuration from TOML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}"
            )

        with open(self.config_path, "rb") as f:
            data = tomllib.load(f)

        # Load AI model configurations
        ai_config = data.get("ai", {})
        self.text_model = AIModelConfig(ai_config.get("text_model", {}))
        self.multimodal_model = AIModelConfig(
            ai_config.get("multimodal_model", {}))
        self.speech_model = AIModelConfig(ai_config.get("speech_model", {}))
        self.web_search = WebSearchConfig(ai_config.get("web_search", {}))

        # Load Google Speech configuration (legacy)
        google_config = data.get("google", {})
        self.google_speech = GoogleSpeechConfig(
            google_config.get("speech", {}))

        # Load audio transcription configuration
        self.audio_transcription = AudioTranscriptionConfig(
            data.get("audio_transcription", {})
        )

        # Load system configuration
        self.system = SystemConfig(data.get("system", {}))

        # Load MySQL configuration
        self.mysql = MySQLConfig(data.get("mysql", {}))

    def reload(self):
        """Reload configuration from file."""
        self._load()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from default or specified path."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.toml"
    return Config(config_path)
