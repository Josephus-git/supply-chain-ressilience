"""Environment-backed application configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required configuration is absent or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str = "https://data.importyeti.com"
    page_size: int = 50
    max_retries: int = 4
    timeout_seconds: float = 30.0
    retry_base_seconds: float = 1.0

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file)
        api_key = os.getenv("IMPORTYETI_API_KEY", "").strip()
        if not api_key or api_key == "replace-with-your-private-key":
            raise ConfigurationError(
                "IMPORTYETI_API_KEY is required. Set it in a local .env file."
            )
        return cls(api_key=api_key)
