"""Схемы запросов проекта vozd."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class VozdGroupParams(BaseModel):
    posts_per_source: int | None = Field(None, ge=1, le=1000, description="Постов на источник (100–1000)")
    comments_enabled: bool | None = Field(None, description="Собирать комментарии и участников")
    comments_per_post_limit: int | None = Field(None, ge=1, description="Лимит комментариев на пост (Telegram); пусто = все")
    collect_profiles: bool | None = Field(None, description="Собирать профили участников после сбора")
    profile_posts_limit: int | None = Field(None, ge=1, le=1000, description="Постов со стены пользователя")
    comments_refresh_days: int | None = Field(
        None,
        ge=0,
        le=365,
        description="Заново собирать комментарии постов младше N дней (0 — не пересобирать). "
        "Для автосбора по умолчанию 7",
    )


class VozdSchedule(BaseModel):
    """Автосбор группы по расписанию."""

    enabled: bool | None = Field(None, description="Включить/выключить автосбор")
    interval_hours: int | None = Field(None, ge=1, le=720, description="Интервал между запусками, часы (по умолчанию 24)")


class VozdSourceIn(BaseModel):
    url: str = Field(..., description="Ссылка на паблик VK или Telegram-канал")


class VozdGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Название социальной группы (оператор)")
    description: str | None = Field(None, description="Описание (оператор)")
    sources: list[VozdSourceIn] = Field(..., min_length=1, description="Состав: ссылки на группы/каналы")
    params: VozdGroupParams | None = None
    schedule: VozdSchedule | None = None


class VozdGroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    params: VozdGroupParams | None = None
    schedule: VozdSchedule | None = None


class VozdCollectRequest(VozdGroupParams):
    """Параметры прогона (перекрывают параметры группы)."""


class VozdSourceAdd(BaseModel):
    sources: list[VozdSourceIn] = Field(..., min_length=1)


class VozdBlacklistUserAdd(BaseModel):
    uid: str = Field(
        ...,
        pattern=r"^(vk|tg|telegram):\d+$",
        description="Универсальный ID пользователя: vk:123 или tg:456",
    )
    note: str | None = Field(None, max_length=1000, description="Заметка (необязательно)")


class VozdBlacklistWordsAdd(BaseModel):
    words: list[str] = Field(..., min_length=1, max_length=200, description="Слова или короткие фразы")


VozdDict = dict[str, Any]


class VozdAnalyticsRequest(BaseModel):
    """Расчёт списка метрик аналитики за один вызов."""

    metrics: list[str] = Field(..., min_length=1, max_length=200, description="ID метрик из каталога: I.1, II.28, III.14 …")
    window_days: int | None = Field(None, ge=1, le=3650, description="Окно расчёта: последние N дней (без окна — все данные)")
    date_from: datetime | None = Field(None, description="Начало окна (приоритетнее window_days)")
    date_to: datetime | None = Field(None, description="Конец окна")
    sample_size: int = Field(200, ge=10, le=2000, description="Для LLM-метрик: сколько текстов брать (топ по вовлечённости)")
    sample_recent_days: int = Field(7, ge=0, le=365, description="Для LLM-метрик: плюс все тексты за последние N дней")
    refresh: bool = Field(False, description="Пересчитать LLM-метрики, игнорируя кэш")
    provider: str | None = None
    model: str | None = None


class VozdAnalyticsExpertInput(BaseModel):
    value: Any = Field(None, description="Оценка эксперта: число, строка, объект или список")
    justification: str | None = Field(None, max_length=10000)
    expert: str | None = Field(None, max_length=255, description="Кто дал оценку")
