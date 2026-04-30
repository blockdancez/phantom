"""集中配置：从环境变量加载，Pydantic 校验。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIJUICER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    redis_url: str
    artifact_root: Path

    heartbeat_timeout_sec: int = 90
    heartbeat_interval_sec: int = 5
    # Agent presence TTL = 3 × heartbeat_interval。
    # 漏 1 次心跳（>5s）→ 标记 offline 但仍显示
    # 漏 3 次心跳（>15s）→ key 自动过期，列表消失
    presence_ttl_sec: int = 15
    max_retries: int = 3
    retry_backoff_sec: list[int] = Field(default_factory=lambda: [60, 300, 900])

    step_max_duration: dict[str, int] = Field(
        default_factory=lambda: {
            "idea": 600,
            "requirement": 1800,
            "plan": 1800,
            "design": 3600,
            "devtest": 21600,
            "deploy": 1800,
        }
    )

    log_level: str = "INFO"
    # 半结构化 ``<ts> <LEVEL> [<thread>] <logger> <msg> k=v...``；
    # 'json' 走 JSON 渲染（给日志收集器），'console' 走 structlog dev 渲染
    log_format: str = "kv"
    # 日志同时写入控制台和该文件（10MB × 5 滚动）
    log_file: Path = Path("/Users/lapsdoor/phantom/logs/ai-juicer.log")


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
