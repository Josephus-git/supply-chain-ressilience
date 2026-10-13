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
    page_size: int = 100
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

        def positive(name: str, default: str, cast):
            try:
                value = cast(os.getenv(name, default))
            except ValueError as exc:
                raise ConfigurationError(f"{name} must be numeric") from exc
            if value <= 0:
                raise ConfigurationError(f"{name} must be positive")
            return value

        return cls(
            api_key=api_key,
            base_url=os.getenv("IMPORTYETI_BASE_URL", cls.base_url).rstrip("/"),
            page_size=positive("IMPORTYETI_PAGE_SIZE", "100", int),
            max_retries=positive("IMPORTYETI_MAX_RETRIES", "4", int),
            timeout_seconds=positive("IMPORTYETI_TIMEOUT_SECONDS", "30", float),
            retry_base_seconds=positive(
                "IMPORTYETI_RETRY_BASE_SECONDS", "1", float
            ),
        )

