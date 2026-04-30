import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    producthunt_api_token: str = ""

    collect_interval_minutes: int = 60
    process_interval_minutes: int = 30
    analysis_interval_minutes: int = 120
    experience_interval_minutes: int = 360  # 6 小时一次
    experience_headless: bool = True
    codex_binary_path: str = "codex"
    codex_experience_root: str = "data/codex_experience"
    discover_interval_minutes: int = 60  # 每小时刷新候选产品池

    log_level: str = "INFO"

    # ``extra="ignore"`` so unrelated env vars / .env keys (e.g. AIJUICER_*
    # consumed directly by the integration layer) don't break Settings init.
    model_config = {"env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context) -> None:
        """Propagate LLM provider keys into the process environment.

        langchain-openai / langchain-anthropic clients read ``OPENAI_API_KEY``
        and ``ANTHROPIC_API_KEY`` from ``os.environ`` directly — they do not
        see our pydantic Settings values. Syncing here makes Settings the
        single source of truth for every code path (FastAPI lifespan, ad-hoc
        Python scripts, tests) without having to pass ``api_key=`` explicitly
        into every ChatOpenAI construction.
        """
        if self.openai_api_key and not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = self.openai_api_key
        if self.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key
