"""Утилиты для надёжного парсинга JSON из ответов LLM.

Модели часто оборачивают JSON в markdown-блоки, добавляют пояснительный текст
до/после, или используют кириллические кавычки. Этот модуль пытается извлечь
JSON из «грязного» ответа несколькими способами.
"""
from __future__ import annotations

import json
import re


def extract_json(raw: str) -> object:
    """
    Попытаться распарсить JSON из строки ответа LLM.

    Порядок попыток:
    1. Прямой json.loads (если модель вернула чистый JSON)
    2. Вырезать ```json ... ``` или ``` ... ``` блок
    3. Найти первый {...} или [...] фрагмент в тексте regex-ом
    4. Если ничего не помогло — поднять ValueError с содержимым ответа
    """
    text = raw.strip()

    # 1. Прямой парсинг
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Markdown code block: ```json ... ``` или ``` ... ```
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Первый JSON-объект или массив в тексте
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass

    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot extract JSON from LLM response: {text[:300]!r}")
