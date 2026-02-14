"""
Dependency utilities for API authentication and shared components.
"""

from fastapi import Header, HTTPException, status

from app.core.config import settings


def verify_api_key(x_api_key: str = Header(...)) -> None:
    """
    Verifies incoming API key header.

    Raises:
        HTTPException: If API key is invalid.
    """
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
