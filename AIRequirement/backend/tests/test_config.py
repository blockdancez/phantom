def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    from app.config import Settings
    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    assert settings.openai_api_key == "sk-test-key"
    assert settings.tavily_api_key == "tvly-test-key"


def test_config_has_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    from app.config import Settings
    settings = Settings()

    assert settings.app_name == "Product Requirement Agent"
    assert settings.log_level == "INFO"
    assert settings.port == 8000
    assert settings.openai_model == "gpt-4o"
