"""
Загрузчик промптов LLM из отдельных файлов (server/prompts/*.txt) — а не из
константных строк в коде.

Смысл: промпты должны быть редактируемы без пересборки образа (см.
docker-compose.yml — server/prompts смонтирован bind-mount'ом внутрь
контейнера) и должны быть видны через API (см.
presentation/api/routes/llm_settings.py — GET /api/v1/llm/prompts).

Намеренно БЕЗ кэширования (в отличие от lemma_scorer._load_index с
lru_cache): весь смысл фичи — редактировать файл на диске и сразу увидеть
эффект без рестарта сервера.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


class PromptNotFoundError(ValueError):
    """Файл промпта с таким именем не найден в PROMPTS_ROOT."""


def _prompts_dir() -> Path:
    return Path(get_settings().prompts_root)


def _prompt_path(name: str) -> Path:
    # Разрешаем передавать имя как с расширением, так и без — но всегда
    # только простое имя файла (без поддиректорий) во избежание path traversal.
    safe_name = Path(name).name
    if not safe_name.endswith(".txt"):
        safe_name = f"{safe_name}.txt"
    return _prompts_dir() / safe_name


def prompt_file_path(name: str) -> Path:
    """Путь к файлу промпта на диске (для отображения «внутреннего расположения» на фронте)."""
    return _prompt_path(name)


def load_prompt(name: str) -> str:
    """Читает промпт из файла как есть, без .format(). Для статических промптов
    (могут содержать «живые» фигурные скобки — примеры JSON в тексте)."""
    path = _prompt_path(name)
    if not path.is_file():
        raise PromptNotFoundError(f"Файл промпта не найден: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: object) -> str:
    """Читает промпт-шаблон и подставляет {placeholder}. Для динамических
    промптов (lemma_llm_extractor) — литеральные фигурные скобки в самом
    файле должны быть экранированы как {{ / }}."""
    return load_prompt(name).format(**kwargs)


def list_prompts() -> list[dict]:
    """Перечисляет все *.txt файлы в PROMPTS_ROOT — имя, файл, путь на диске,
    размер, время изменения. Для «внутреннего расположения» промптов на фронте."""
    d = _prompts_dir()
    if not d.is_dir():
        return []
    items: list[dict] = []
    for path in sorted(d.glob("*.txt")):
        stat = path.stat()
        items.append(
            {
                "name": path.stem,
                "filename": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
    return items
