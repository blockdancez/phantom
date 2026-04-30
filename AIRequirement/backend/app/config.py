from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    openai_api_key: str
    tavily_api_key: str
    app_name: str = "Product Requirement Agent"
    log_level: str = "INFO"
    port: int = 8000
    openai_model: str = "gpt-4o"
    project_root: str = "/Users/lapsdoor/phantom"
    log_dir: str = "/Users/lapsdoor/phantom/logs"
    service_name: str = "ai-requirement"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    return Settings()
