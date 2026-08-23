"""Хэширование и проверка паролей (bcrypt через passlib)."""
from __future__ import annotations

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw_password: str) -> str:
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    try:
        return _pwd_context.verify(raw_password, hashed_password)
    except ValueError:
        # Повреждённый/несовместимый хэш в БД — считаем как неверный пароль,
        # а не роняем запрос 500-й ошибкой.
        return False
