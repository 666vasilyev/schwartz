"""Abstract base for LLM provider adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Единый интерфейс для всех LLM-провайдеров."""

    @abstractmethod
    async def ask(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant.",
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        """Вернуть текстовый ответ модели."""

    @abstractmethod
    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> Any:
        """Вернуть распарсенный JSON-ответ модели."""
