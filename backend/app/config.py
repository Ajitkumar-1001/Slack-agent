from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    slack_bot_token: str
    slack_signing_secret: str
    anthropic_api_key: str
    default_model_provider: str = "anthropic"
    default_model_name: str = "claude-sonnet-5"
    database_url: str
    github_token: str
    github_owner: str
    github_repo: str
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]  # fields are populated from env vars at runtime
