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
        db_statement_timeout_ms (int): Server-side cap on any single query.
        db_idle_in_transaction_timeout_ms (int): Server-side cap on a
            session sitting idle inside an open transaction.
        rate_limit_requests (int): Requests allowed per client per window.
        rate_limit_window_seconds (int): Sliding-window length.
    """

    app_name: str = Field(default="ai-bi-backend", alias="APP_NAME")
    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_key: str = Field(alias="API_KEY")
    database_url: str = Field(alias="DATABASE_URL")
    db_statement_timeout_ms: int = Field(
        default=5000, gt=0, alias="DB_STATEMENT_TIMEOUT_MS"
    )
    db_idle_in_transaction_timeout_ms: int = Field(
        default=10000, gt=0, alias="DB_IDLE_IN_TRANSACTION_TIMEOUT_MS"
    )

    rate_limit_requests: int = Field(default=5, gt=0, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(
        default=60, gt=0, alias="RATE_LIMIT_WINDOW_SECONDS"
    )

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
