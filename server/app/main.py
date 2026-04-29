"""Точка входа для uvicorn: `uvicorn app.main:app` (Docker, локальный запуск)."""
from app.presentation.main import app

__all__ = ["app"]
