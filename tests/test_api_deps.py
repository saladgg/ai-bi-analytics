import pytest
from fastapi import HTTPException

from ai_bi_analytics.api.deps import verify_api_key
from ai_bi_analytics.core.config import settings


def test_verify_api_key_accepts_valid_key():
    verify_api_key(x_api_key=settings.api_key)


def test_verify_api_key_rejects_invalid_key():
    with pytest.raises(HTTPException) as exc:
        verify_api_key(x_api_key="definitely-wrong-key")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid API key"

