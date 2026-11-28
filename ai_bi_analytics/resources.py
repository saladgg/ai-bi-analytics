"""
Process-wide clients (audit ARCH-2, PERF-2).

The database engine, Redis client and LLM client (each with its own
connection pool) are built once, in the app's lifespan, from the app's
``Settings``, and closed on shutdown. Nothing connects at import time.
Request handlers reach them through the dependencies in ``api/deps.py``.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_bi_analytics.core.config import Settings
from ai_bi_analytics.core.redis_client import build_redis_client
from ai_bi_analytics.db.session import build_engine, build_session_factory
from ai_bi_analytics.services.llm_client import LLMClient, build_provider
from ai_bi_analytics.services.schema_loader import SchemaProvider

logger = logging.getLogger(__name__)


@dataclass
class Resources:
    engine: Engine
    session_factory: sessionmaker[Session]
    redis: redis.Redis
    llm: LLMClient
    schema: SchemaProvider

    def close(self) -> None:
        """
        Closes pooled connections so Postgres, Redis and the LLM API see
        clean disconnects rather than dropped sockets (audit OPS-3). One
        failure doesn't stop the others closing.
        """
        closers: list[tuple[str, Callable[[], object]]] = [
            ("llm", self.llm.close),
            ("redis", self.redis.close),
            ("database", self.engine.dispose),
        ]
        for name, close in closers:
            try:
                close()
            except Exception:
                logger.warning("Closing the %s client failed", name, exc_info=True)


ResourcesFactory = Callable[[Settings], Resources]


def build_resources(cfg: Settings) -> Resources:
    engine = build_engine(cfg)
    return Resources(
        engine=engine,
        session_factory=build_session_factory(engine),
        redis=build_redis_client(str(cfg.redis_url), cfg.redis_socket_timeout_seconds),
        llm=LLMClient(build_provider(cfg), cfg),
        schema=SchemaProvider(cfg),
    )
