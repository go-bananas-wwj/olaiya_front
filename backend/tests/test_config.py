import importlib

from app import config as config_module


def test_default_database_url_is_sqlite():
    assert config_module.settings.database_url.startswith("sqlite")


def test_env_override(monkeypatch):
    monkeypatch.setenv("CFZ_DATABASE_URL", "sqlite:////tmp/override.db")
    importlib.reload(config_module)
    try:
        assert config_module.settings.database_url == "sqlite:////tmp/override.db"
    finally:
        monkeypatch.undo()
        importlib.reload(config_module)
