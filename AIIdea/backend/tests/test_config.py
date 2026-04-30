import pytest
from unittest.mock import patch


def test_config_loads_from_env():
    env = {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
        "OPENAI_API_KEY": "sk-test-key",
    }
    with patch.dict("os.environ", env, clear=False):
        from src.config import Settings
        settings = Settings()
        assert settings.database_url == env["DATABASE_URL"]
        assert settings.openai_api_key == env["OPENAI_API_KEY"]


def test_config_requires_database_url():
    with patch.dict("os.environ", {}, clear=True):
        from src.config import Settings
        with pytest.raises(Exception):
            Settings()
