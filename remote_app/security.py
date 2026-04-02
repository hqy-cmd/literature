from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    expected = (settings.api_admin_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "admin_token_not_configured", "message": "server token missing"},
        )
    token = (x_admin_token or "").strip()
    if token == expected:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "admin_token_invalid", "message": "missing or invalid X-Admin-Token"},
    )
