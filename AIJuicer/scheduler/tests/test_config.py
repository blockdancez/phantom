from scheduler.config import Settings


def test_default_settings(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AIJUICER_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/test",
    )
    monkeypatch.setenv("AIJUICER_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AIJUICER_ARTIFACT_ROOT", str(tmp_path))

    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.artifact_root == tmp_path
    assert s.heartbeat_timeout_sec == 90
    assert s.heartbeat_interval_sec == 5
    assert s.presence_ttl_sec == 15
    assert s.max_retries == 3
    assert s.retry_backoff_sec == [60, 300, 900]
    assert set(s.step_max_duration.keys()) == {
        "idea",
        "requirement",
        "plan",
        "design",
        "devtest",
        "deploy",
    }
    assert s.log_format == "json"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AIJUICER_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/test",
    )
    monkeypatch.setenv("AIJUICER_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AIJUICER_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("AIJUICER_HEARTBEAT_TIMEOUT_SEC", "120")
    monkeypatch.setenv("AIJUICER_MAX_RETRIES", "5")

    s = Settings()
    assert s.heartbeat_timeout_sec == 120
    assert s.max_retries == 5
