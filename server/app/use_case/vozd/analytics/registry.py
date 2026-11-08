"""Реестр калькуляторов метрик: id метрики → асинхронная функция `(ctx) -> JSON-значение`."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


class MetricUnavailable(Exception):
    """Данных для метрики нет (поле не собирается, источник недоступен) — не ошибка расчёта."""


class InsufficientData(Exception):
    """Данных слишком мало для осмысленного расчёта (нужен больший период/объём)."""


Calc = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Registered:
    fn: Calc
    llm: bool = False
    note: str | None = None


REGISTRY: dict[str, Registered] = {}


def calculator(*metric_ids: str, llm: bool = False, note: str | None = None) -> Callable[[Calc], Calc]:
    """Зарегистрировать функцию как калькулятор одной или нескольких метрик.

    Функция получает `AnalyticsContext` и возвращает JSON-совместимое значение;
    id запрошенной метрики доступен как `ctx.metric_id`."""

    def deco(fn: Calc) -> Calc:
        for mid in metric_ids:
            REGISTRY[mid] = Registered(fn, llm, note)
        return fn

    return deco
