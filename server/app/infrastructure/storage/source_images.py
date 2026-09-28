"""
Хранение загружаемых картинок источников на локальном диске.

Файлы лежат в MEDIA_ROOT/sources/<source_id>.<ext> (одна картинка на источник,
новая загрузка перезаписывает старую). MEDIA_ROOT должен быть на персистентном
volume (см. docker-compose.yml: media_uploads) — иначе картинки пропадут при
пересборке контейнера.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

_ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_BYTES = 5 * 1024 * 1024  # 5 МБ


def _sources_dir() -> Path:
    d = Path(get_settings().media_root) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_image_path(filename: str) -> Path:
    return _sources_dir() / filename


async def save_source_image(source_id: int, file: UploadFile) -> str:
    """Валидирует и сохраняет файл, возвращает имя файла для Source.image_filename."""
    ext = _ALLOWED_CONTENT_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Допустимые форматы изображения: JPEG, PNG, WEBP, GIF",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Пустой файл")
    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Максимальный размер изображения — {_MAX_BYTES // (1024 * 1024)} МБ",
        )

    # Если раньше было изображение с другим расширением (например .png -> .jpg) —
    # подчищаем, иначе на диске останется висеть неиспользуемый файл.
    for old in _sources_dir().glob(f"{source_id}.*"):
        old.unlink(missing_ok=True)

    filename = f"{source_id}{ext}"
    source_image_path(filename).write_bytes(content)
    return filename


def delete_source_image_file(filename: str | None) -> None:
    if not filename:
        return
    source_image_path(filename).unlink(missing_ok=True)
