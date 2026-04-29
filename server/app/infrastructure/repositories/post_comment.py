from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import PostComment


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _as_comment_dict(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        return node
    if hasattr(node, "model_dump"):
        return node.model_dump()
    return {}


async def delete_comments_for_post(db: AsyncSession, post_id: int) -> None:
    await db.execute(delete(PostComment).where(PostComment.post_id == post_id))
    await db.flush()


async def replace_comments_from_vk_collect(
    db: AsyncSession,
    post_id: int,
    items: list[Any] | None,
) -> None:
    await delete_comments_for_post(db, post_id)

    async def walk(nodes: list[Any], parent_db_id: int | None) -> None:
        for node in nodes:
            d = _as_comment_dict(node)
            cid = d.get("id")
            if cid is None:
                continue
            atts = d.get("attachments")
            if atts == []:
                atts = None
            row = PostComment(
                post_id=post_id,
                source_comment_id=int(cid),
                parent_id=parent_db_id,
                from_id=int(d["from_id"]) if d.get("from_id") is not None else None,
                text=d.get("text"),
                published_at=_parse_iso_datetime(d.get("date")),
                attachments=atts,
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)
            replies = d.get("replies") or []
            if isinstance(replies, list) and replies:
                await walk(replies, row.id)

    if items:
        await walk(items, None)
