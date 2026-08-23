"""
Хэширование и проверка паролей — bcrypt напрямую, без passlib.

passlib не обновлялся с 2020 года и несовместим с bcrypt>=4.1: та убрала
атрибут __about__.__version__, на который опирается детект бэкенда passlib,
из-за чего он падает на собственной самопроверке (ValueError о 72-байтном
лимите bcrypt) ещё до реального хэширования. Используем bcrypt напрямую —
он поддерживает лимит в 72 байта нативно, и никакой прослойки не нужно.
"""
from __future__ import annotations

import bcrypt

_MAX_PASSWORD_BYTES = 72  # собственное ограничение алгоритма bcrypt


def hash_password(raw_password: str) -> str:
    password_bytes = raw_password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(raw_password: str, hashed_password: str) -> bool:
    password_bytes = raw_password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        # Повреждённый/несовместимый хэш в БД — считаем как неверный пароль,
        # а не роняем запрос 500-й ошибкой.
        return False
