"""JSON-дамп данных социальной группы проекта vozd (потоковая сборка)."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.infrastructure.db.orm.models import Post
from app.infrastructure.db.orm.models_vozd import SocialGroup, VozdUser
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.use_case.vozd import common

_POST_BATCH = 100
_USER_BATCH = 200


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


async def iter_dump(group_id: int) -> AsyncGenerator[str, None]:
    """Генератор кусков JSON. Использует собственную сессию — переживает закрытие request-сессии."""
    async with AsyncSessionLocal() as db:
        use_project_scope(db, PROJECT_VOZD)
        group = await db.get(SocialGroup, group_id)
        if group is None or group.deleted_at is not None:
            raise LookupError("Социальная группа не найдена")
        sources = await common.group_sources(db, group_id)
        src_by_id = {s.id: s for s in sources}
        stats = await common.group_stats(db, sources)

        yield "{"
        yield f'"format": "vozd-dump/1", "generated_at": {_j(datetime.now(tz=timezone.utc).isoformat())},'
        yield f'"group": {_j(common.group_header(group, sources))},'
        yield f'"stats": {_j(stats)},'

        # ── посты с комментариями ──
        yield '"posts": ['
        first = True
        last_id = 0
        src_ids = list(src_by_id)
        while src_ids:
            posts = list(
                (
                    await db.execute(
                        select(Post)
                        .where(Post.source_id.in_(src_ids), Post.id > last_id)
                        .order_by(Post.id)
                        .limit(_POST_BATCH)
                    )
                ).scalars()
            )
            if not posts:
                break
            last_id = posts[-1].id
            cmap = await common.comments_by_post(db, [p.id for p in posts])
            for p in posts:
                item = common.post_to_dict(src_by_id[p.source_id], p, cmap.get(p.id, []))
                yield ("" if first else ",") + _j(item)
                first = False
            db.expunge_all()
        yield "],"

        # ── участники: профиль + что и где писали ──
        yield '"users": ['
        first = True
        id_rows = (await db.execute(common.participants_query(sources).order_by(VozdUser.id))).scalars().all()
        for off in range(0, len(id_rows), _USER_BATCH):
            chunk_ids = id_rows[off : off + _USER_BATCH]
            users = list(
                (await db.execute(select(VozdUser).where(VozdUser.id.in_(chunk_ids)).order_by(VozdUser.id))).scalars()
            )
            details = await common.user_details(db, users, with_profile=True)
            activity = await common.user_activity(db, users, sources)
            for u, d in zip(users, details):
                comments = activity.get(u.id, [])
                d["activity"] = {
                    "comments_count": len(comments),
                    "comments": comments,
                }
                yield ("" if first else ",") + _j(d)
                first = False
            db.expunge_all()
        yield "]"
        yield "}"


async def write_dump_file(group_id: int) -> str:
    """Записать дамп на диск; возвращает путь к файлу."""
    directory = get_settings().vozd_dump_dir
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(directory, f"group_{group_id}_{stamp}.json")
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        async for chunk in iter_dump(group_id):
            fh.write(chunk)
    os.replace(tmp, path)
    return path
