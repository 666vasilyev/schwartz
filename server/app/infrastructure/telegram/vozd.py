"""
Telegram для проекта vozd: комментарии к постам канала (из привязанного чата
обсуждений) и данные авторов комментариев. Использует существующий
`telegram_client` (Telethon, сессия из БД); общий код сбора wall не затрагивается.
"""
from __future__ import annotations

from typing import Any

from app.infrastructure.db.orm.models import TelegramSession
from app.infrastructure.telegram.client import TelegramClientError, telegram_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _sender_dict(sender: Any, about: str | None = None) -> dict[str, Any] | None:
    if sender is None:
        return None
    sid = getattr(sender, "id", None)
    if sid is None:
        return None
    return {
        "id": int(sid),
        "username": getattr(sender, "username", None),
        "first_name": getattr(sender, "first_name", None) or getattr(sender, "title", None),
        "last_name": getattr(sender, "last_name", None),
        "is_bot": bool(getattr(sender, "bot", False)),
        "about": about,
    }


async def fetch_comments_for_posts(
    session: TelegramSession,
    username: str,
    post_message_ids: list[int],
    *,
    per_post_limit: int | None = None,
    fetch_bios: bool = True,
) -> dict[int, dict[str, Any]]:
    """
    Для каждого поста канала вернуть {"status": ok|disabled, "comments": [...], "senders": {id: {...}}}.

    comment: id, parent_comment_id, from_id, text, date(iso), likes_count.
    Комментарии доступны только если у канала есть привязанный чат обсуждений.
    """
    try:
        from telethon.errors import FloodWaitError, MsgIdInvalidError
        from telethon.tl.functions.users import GetFullUserRequest
    except ImportError as exc:
        raise TelegramClientError("telethon не установлен") from exc

    out: dict[int, dict[str, Any]] = {}
    bios: dict[int, str | None] = {}
    bios_allowed = fetch_bios

    async with telegram_client(session) as client:
        entity = await client.get_entity(username)
        for msg_id in post_message_ids:
            comments: list[dict[str, Any]] = []
            senders: dict[int, dict[str, Any]] = {}
            try:
                raw: list[Any] = []
                async for c in client.iter_messages(entity, reply_to=msg_id, limit=per_post_limit):
                    raw.append(c)
                ids = {int(c.id) for c in raw}
                # iter_messages отдаёт новые → старые; хотим родитель раньше ответа
                for c in sorted(raw, key=lambda m: m.id):
                    if not c.date:
                        continue
                    reply_to = getattr(c, "reply_to", None)
                    parent = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
                    parent = int(parent) if parent and int(parent) in ids and int(parent) != c.id else None
                    sender = None
                    try:
                        sender = await c.get_sender()
                    except Exception:  # noqa: BLE001
                        sender = None
                    sid = getattr(c, "sender_id", None)
                    if sender is not None and getattr(sender, "id", None) is not None:
                        sid = int(sender.id)
                        if sid not in senders:
                            about = bios.get(sid)
                            if sid not in bios and bios_allowed and hasattr(sender, "first_name"):
                                try:
                                    full = await client(GetFullUserRequest(sender))
                                    about = getattr(getattr(full, "full_user", None), "about", None)
                                except FloodWaitError:
                                    bios_allowed = False
                                    about = None
                                except Exception:  # noqa: BLE001
                                    about = None
                                bios[sid] = about
                            d = _sender_dict(sender, about)
                            if d:
                                senders[sid] = d
                    likes = 0
                    reactions = getattr(c, "reactions", None)
                    if reactions is not None:
                        likes = sum(int(getattr(r, "count", 0) or 0) for r in (reactions.results or []))
                    comments.append(
                        {
                            "id": int(c.id),
                            "parent_comment_id": parent,
                            "thread_root_id": None,
                            "from_id": int(sid) if sid is not None else None,
                            "text": c.message or None,
                            "date": c.date.isoformat(),
                            "likes_count": likes or None,
                            "deleted": False,
                        }
                    )
                out[msg_id] = {"status": "ok", "comments": comments, "senders": senders}
            except MsgIdInvalidError:
                out[msg_id] = {"status": "disabled", "comments": [], "senders": {}}
            except FloodWaitError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Нет привязанного чата / нет доступа — не сбой сбора.
                logger.info("tg_vozd_comments_unavailable", post=msg_id, error=str(exc)[:200])
                out[msg_id] = {"status": "disabled", "comments": [], "senders": {}}
    return out
