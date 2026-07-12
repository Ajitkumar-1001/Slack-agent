from typing import Literal

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
    # Jira fields are optional (unlike github_* above) so a deployment with no Jira
    # configured still instantiates Settings() cleanly (AC-105) — see research.md Decision 2.
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    default_target_system: Literal["github", "jira", "both"] = "github"
    # Notion fields are optional, same reason as jira_* above (AC-203) — see research.md Decision 6.
    notion_api_key: str | None = None
    notion_parent_page_id: str | None = None
    default_notion_enabled: bool = False
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]  # fields are populated from env vars at runtime
