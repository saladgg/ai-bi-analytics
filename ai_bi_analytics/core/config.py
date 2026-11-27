"""
Application configuration module.

Loads and validates environment-based settings using Pydantic.
Ensures centralized configuration management.
"""

import os
import re
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        app_name (str): Application name.
        env (str): Runtime environment (development, staging, production).
        log_level (str): Logging verbosity level.
        api_key (SecretStr | None): Legacy single API key (client "default").
        api_keys (list[str]): ``client_id:sha256hex`` entries, one per client.
        database_url (str): SQLAlchemy database connection string.
        llm_provider (str): LLM provider identifier.
        openai_api_key (str | None): OpenAI API key if used.
        db_statement_timeout_ms (int): Server-side cap on any single query.
        db_idle_in_transaction_timeout_ms (int): Server-side cap on a
            session sitting idle inside an open transaction.
        rate_limit_requests (int): Requests allowed per client per window.
        rate_limit_window_seconds (int): Sliding-window length.
        max_question_length (int): Longest accepted question, in characters.
        max_result_rows (int): Most rows a query may return; more are
            truncated (the database stops at the cap).
        explanation_sample_rows (int): Rows sent to the LLM for explanation.
        cache_max_bytes (int): Responses larger than this aren't cached.
        queryable_schema (str): The one schema the LLM sees and queries.
        queryable_tables (list[str]): Tables/views the LLM may use. Empty
            means every table in ``queryable_schema`` (development only).
        redacted_columns (list[str]): ``table.column`` or ``column``
            entries hidden from the LLM and rejected by the SQL guard.
    """

    app_name: str = Field(default="ai-bi-backend", alias="APP_NAME")
    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # None: JSON outside development, text in development (audit OPS-2).
    log_format: Literal["json", "text"] | None = Field(default=None, alias="LOG_FORMAT")
    # Questions are user text and may be sensitive: by default logs carry
    # a hash and length, not the text.
    log_questions: bool = Field(default=False, alias="LOG_QUESTIONS")
    # Traces and metrics over OTLP; exporter settings come from the standard
    # OTEL_EXPORTER_OTLP_* variables.
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")

    api_key: SecretStr | None = Field(default=None, alias="API_KEY")
    api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="API_KEYS"
    )
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

    queryable_schema: str = Field(default="public", alias="QUERYABLE_SCHEMA")
    queryable_tables: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="QUERYABLE_TABLES"
    )
    redacted_columns: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="REDACTED_COLUMNS"
    )

    max_result_rows: int = Field(
        default=1000, ge=1, le=100_000, alias="MAX_RESULT_ROWS"
    )
    explanation_sample_rows: int = Field(
        default=20, ge=1, le=500, alias="EXPLANATION_SAMPLE_ROWS"
    )
    cache_max_bytes: int = Field(default=512_000, ge=0, alias="CACHE_MAX_BYTES")

    max_question_length: int = Field(
        default=500, ge=10, le=4000, alias="MAX_QUESTION_LENGTH"
    )

    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # SKIP_DOTENV=1 ignores a local .env, so the pre-push test hook sees the
    # same configuration as CI (which has no .env) instead of a developer's.
    model_config = SettingsConfigDict(
        env_file=None if os.getenv("SKIP_DOTENV") else ".env",
        case_sensitive=False,
    )

    @field_validator("queryable_tables", "redacted_columns", "api_keys", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("api_keys")
    @classmethod
    def _api_keys_well_formed(cls, value: list[str]) -> list[str]:
        from ai_bi_analytics.core.security import parse_api_key_entry

        client_ids = [parse_api_key_entry(entry)[0] for entry in value]
        duplicates = sorted({c for c in client_ids if client_ids.count(c) > 1})
        if duplicates:
            raise ValueError(f"API_KEYS has duplicate client ids: {duplicates}")
        return value

    @model_validator(mode="after")
    def _some_api_key_configured(self) -> "Settings":
        if not self.api_keys and not (self.api_key and self.api_key.get_secret_value()):
            raise ValueError("Configure API_KEYS (preferred) or API_KEY")
        return self

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL"
            )
        return level

    @property
    def effective_log_format(self) -> Literal["json", "text"]:
        if self.log_format is not None:
            return self.log_format
        return "text" if self.env == "development" else "json"

    @field_validator("queryable_schema")
    @classmethod
    def _schema_is_identifier(cls, value: str) -> str:
        # Interpolated into the connection's search_path option.
        if not _IDENTIFIER.match(value):
            raise ValueError("QUERYABLE_SCHEMA must be a plain SQL identifier")
        return value

    @field_validator("queryable_tables")
    @classmethod
    def _tables_are_identifiers(cls, value: list[str]) -> list[str]:
        bad = [t for t in value if not _IDENTIFIER.match(t)]
        if bad:
            raise ValueError(f"QUERYABLE_TABLES has invalid names: {bad}")
        return value

    @field_validator("redacted_columns")
    @classmethod
    def _redactions_are_identifiers(cls, value: list[str]) -> list[str]:
        bad = [
            entry
            for entry in value
            if not all(_IDENTIFIER.match(part) for part in entry.split("."))
            or entry.count(".") > 1
        ]
        if bad:
            raise ValueError(
                f"REDACTED_COLUMNS entries must be 'table.column' or 'column': {bad}"
            )
        return value


settings = Settings()
