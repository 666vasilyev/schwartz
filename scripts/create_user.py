"""
Создать пользователя для входа в API. Регистрация закрытая — HTTP-ручки
/auth/register нет намеренно (нет ролей/прав — только "авторизован/нет", так
что открытая саморегистрация была бы равносильна отсутствию авторизации).

Запуск (на сервере, где доступна БД из .env):
    pip install -r server/requirements.txt --break-system-packages   # если ещё не установлено
    python scripts/create_user.py <username> <password>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from app.application.services.auth.password import hash_password  # noqa: E402
from app.infrastructure.db.orm.session import AsyncSessionLocal  # noqa: E402
from app.infrastructure.repositories.user import create_user, get_user_by_username  # noqa: E402


async def main(username: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        existing = await get_user_by_username(db, username)
        if existing is not None:
            print(f"Пользователь '{username}' уже существует (id={existing.id})")
            return
        user = await create_user(db, username=username, hashed_password=hash_password(password))
        await db.commit()
        print(f"Создан пользователь '{user.username}' (id={user.id})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Использование: python scripts/create_user.py <username> <password>")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
