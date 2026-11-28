"""
Health endpoints (audit OPS-3).

- ``/api/health/live``: the process is up and serving. Cheap, no
  dependencies; use it for container/process health (Docker HEALTHCHECK,
  Kubernetes livenessProbe).
- ``/api/health/ready``: the dependencies a query needs (Postgres and
  Redis) answer. 503 when either doesn't; use it for load-balancer /
  readinessProbe routing.
- ``/api/health``: kept as an alias of ``live`` for existing monitors.

All three are unauthenticated and outside the rate limiter. Failure
details go to the log; the body only names which check failed.
"""

import logging
from typing import Literal

import redis
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, text

from ai_bi_analytics.api.deps import get_resources
from ai_bi_analytics.resources import Resources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

CheckStatus = Literal["ok", "error"]


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckStatus]


def _check_database(engine: Engine) -> CheckStatus:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        logger.exception("Readiness: database check failed")
        return "error"


def _check_redis(client: redis.Redis) -> CheckStatus:
    try:
        client.ping()
        return "ok"
    except Exception:
        logger.exception("Readiness: redis check failed")
        return "error"


@router.get("", response_model=LiveResponse, summary="Liveness (alias of /live)")
@router.get("/live", response_model=LiveResponse, summary="Liveness")
def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Readiness",
    responses={503: {"model": ReadyResponse}},
)
def ready(
    response: Response, resources: Resources = Depends(get_resources)
) -> ReadyResponse:
    checks: dict[str, CheckStatus] = {
        "database": _check_database(resources.engine),
        "redis": _check_redis(resources.redis),
    }
    if all(result == "ok" for result in checks.values()):
        return ReadyResponse(status="ok", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="unavailable", checks=checks)
