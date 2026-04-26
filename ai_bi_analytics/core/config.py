"""
Application configuration module.

Loads and validates environment-based settings using Pydantic.
Ensures centralized configuration management.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        app_name (str): Application name.
        env (str): Runtime environment (development, staging, production).
        log_level (str): Logging verbosity level.
        api_key (str): Static API key for request authentication.
        database_url (str): SQLAlchemy database connection string.
        llm_provider (str): LLM provider identifier.
        openai_api_key (str | None): OpenAI API key if used.
    """

    app_name: str = Field(default="ai-bi-backend", alias="APP_NAME")
    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_key: str = Field(alias="API_KEY")
    database_url: str = Field(alias="DATABASE_URL")

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
