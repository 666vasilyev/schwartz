from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


async def require_collector_auth(request: Request) -> None:
    settings = get_settings()
    expected = (settings.collector_shared_secret or "").strip()
    if not expected:
        return

    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth[7:].strip()
    ta = token.encode("utf-8")
    ex = expected.encode("utf-8")
    if len(ta) != len(ex):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not secrets.compare_digest(ta, ex):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
