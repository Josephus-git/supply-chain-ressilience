import pytest

from dyson_supply_chain.config import ConfigurationError, Settings


def test_missing_api_key_fails(monkeypatch):
    monkeypatch.delenv("IMPORTYETI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="IMPORTYETI_API_KEY"):
        Settings.from_env()


def test_settings_are_loaded(monkeypatch):
    monkeypatch.setenv("IMPORTYETI_API_KEY", "test-secret")
    settings = Settings.from_env()
    assert settings.api_key == "test-secret"
    assert settings.base_url == "https://data.importyeti.com"

