"""
JWT access-токены + непрозрачные (opaque) refresh-токены.

Access-токен — короткоживущий (settings.jwt_access_token_expire_minutes), сам
себя валидирует по подписи (HS256) — без обращения к БД на каждый запрос,
кроме финальной проверки is_active пользователя в get_current_user.

Refresh-токен — НЕ JWT: просто случайная строка, которую клиент хранит и
предъявляет в /auth/refresh. В БД (таблица refresh_tokens) хранится только её
SHA-256 хэш — так утечка БД не даёт готовый токен для входа. Это также даёт
возможность отзыва (logout, ротация при refresh), которой у чистого
stateless-JWT нет без отдельного blacklist.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings

_ALGORITHM = "HS256"
_REFRESH_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) ≈ 43 символа


def create_access_token(*, user_id: int, username: str) -> str:
    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Возвращает payload при валидной подписи/сроке действия, иначе None (не бросает)."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None


def generate_refresh_token() -> tuple[str, str, datetime]:
    """
    Новый refresh-токен: (сырой_токен_для_клиента, его_sha256_хэш_для_БД, expires_at).
    Сырой токен возвращается ровно один раз — дальше в системе хранится только хэш.
    """
    settings = get_settings()
    raw = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    return raw, hash_refresh_token(raw), expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
