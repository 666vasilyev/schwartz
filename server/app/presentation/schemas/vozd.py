"""Схемы запросов проекта vozd."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VozdGroupParams(BaseModel):
    posts_per_source: int | None = Field(None, ge=1, le=1000, description="Постов на источник (100–1000)")
    comments_enabled: bool | None = Field(None, description="Собирать комментарии и участников")
    comments_per_post_limit: int | None = Field(None, ge=1, description="Лимит комментариев на пост (Telegram); пусто = все")
    collect_profiles: bool | None = Field(None, description="Собирать профили участников после сбора")
    profile_posts_limit: int | None = Field(None, ge=1, le=1000, description="Постов со стены пользователя")


class VozdSourceIn(BaseModel):
    url: str = Field(..., description="Ссылка на паблик VK или Telegram-канал")


class VozdGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Название социальной группы (оператор)")
    description: str | None = Field(None, description="Описание (оператор)")
    sources: list[VozdSourceIn] = Field(..., min_length=1, description="Состав: ссылки на группы/каналы")
    params: VozdGroupParams | None = None


class VozdGroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    params: VozdGroupParams | None = None


class VozdCollectRequest(VozdGroupParams):
    """Параметры прогона (перекрывают параметры группы)."""


class VozdSourceAdd(BaseModel):
    sources: list[VozdSourceIn] = Field(..., min_length=1)


VozdDict = dict[str, Any]
