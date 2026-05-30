"""
Telegram Integration API — /api/v1/telegram

Sessions:
  GET    /sessions                  — список сессий
  POST   /sessions                  — добавить сессию
  GET    /sessions/{id}             — получить сессию
  PATCH  /sessions/{id}             — обновить (is_active, note, phone)
  DELETE /sessions/{id}             — удалить сессию
  POST   /sessions/{id}/check       — проверить работоспособность сессии

Resolve:
  POST   /resolve                   — получить инфо о канале по username/URL

Sources:
  POST   /sources/{id}/fetch        — ручной парсинг с сохранением в БД
  POST   /sources/{id}/fetch/preview — предпросмотр без сохранения
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.telegram import (
    TelegramFetchPreviewResponse,
    TelegramFetchRequest,
    TelegramFetchResult,
    TelegramResolveRequest,
    TelegramResolvedChannel,
    TelegramSessionAddRequest,
    TelegramSessionCheckResponse,
    TelegramSessionListResponse,
    TelegramSessionRead,
    TelegramSessionUpdateRequest,
)
from app.use_case.telegram import fetch as fetch_uc
from app.use_case.telegram import sessions as sessions_uc

router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram"])


# ── Sessions ──────────────────────────────────────────────────────────────────


@router.get(
    "/sessions",
    response_model=TelegramSessionListResponse,
    summary="Список Telegram-сессий",
)
async def list_sessions(db: AsyncSession = Depends(get_session)) -> TelegramSessionListResponse:
    return await sessions_uc.get_list(db)


@router.post(
    "/sessions",
    response_model=TelegramSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить Telegram-сессию (StringSession от Telethon)",
)
async def add_session(
    body: TelegramSessionAddRequest,
    db: AsyncSession = Depends(get_session),
) -> TelegramSessionRead:
    return await sessions_uc.add(db, body)


@router.get(
    "/sessions/{session_id}",
    response_model=TelegramSessionRead,
    summary="Получить Telegram-сессию по ID",
)
async def get_session_by_id(
    session_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> TelegramSessionRead:
    return await sessions_uc.get_one(db, session_id)


@router.patch(
    "/sessions/{session_id}",
    response_model=TelegramSessionRead,
    summary="Обновить Telegram-сессию (активность, метка, телефон)",
)
async def update_session(
    body: TelegramSessionUpdateRequest,
    session_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> TelegramSessionRead:
    return await sessions_uc.update(db, session_id, body)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить Telegram-сессию",
)
async def delete_session(
    session_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> None:
    await sessions_uc.remove(db, session_id)


@router.post(
    "/sessions/{session_id}/check",
    response_model=TelegramSessionCheckResponse,
    summary="Проверить работоспособность Telegram-сессии",
)
async def check_session(
    session_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> TelegramSessionCheckResponse:
    return await sessions_uc.check(db, session_id)


# ── Resolve ───────────────────────────────────────────────────────────────────


@router.post(
    "/resolve",
    response_model=TelegramResolvedChannel,
    summary="Получить информацию о Telegram-канале по username или URL",
)
async def resolve_channel(
    body: TelegramResolveRequest,
    db: AsyncSession = Depends(get_session),
) -> TelegramResolvedChannel:
    return await fetch_uc.resolve(db, body)


# ── Sources: fetch ─────────────────────────────────────────────────────────────


@router.post(
    "/sources/{source_id}/fetch",
    response_model=TelegramFetchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ручной парсинг Telegram-канала с сохранением в БД",
)
async def fetch_telegram(
    body: TelegramFetchRequest,
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> TelegramFetchResult:
    return await fetch_uc.fetch(db, source_id, body)


@router.post(
    "/sources/{source_id}/fetch/preview",
    response_model=TelegramFetchPreviewResponse,
    summary="Предпросмотр постов Telegram-канала без сохранения в БД",
)
async def fetch_telegram_preview(
    body: TelegramFetchRequest,
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> TelegramFetchPreviewResponse:
    return await fetch_uc.fetch_preview(db, source_id, body)
