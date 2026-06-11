"""LLM settings API — /api/v1/llm

GET  /api/v1/llm/models   — каталог провайдеров и моделей (для фронта: папки + элементы)
GET  /api/v1/llm/active   — активный провайдер и модель
PATCH /api/v1/llm/active  — сменить провайдер/модель в рантайме
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.infrastructure.clients import llm_registry
from app.presentation.schemas.llm_settings import (
    LLMActiveRequest,
    LLMActiveResponse,
    LLMCatalogResponse,
    LLMModelGroup,
)

router = APIRouter(prefix="/api/v1/llm", tags=["LLM Settings"])


@router.get(
    "/models",
    response_model=LLMCatalogResponse,
    summary="Каталог LLM-провайдеров и доступных моделей",
)
def get_llm_models() -> LLMCatalogResponse:
    """Возвращает все провайдеры с вложенным списком моделей (структура «папки»)."""
    providers = {
        key: LLMModelGroup(label=val["label"], models=val["models"])
        for key, val in llm_registry.MODELS_CATALOG.items()
    }
    return LLMCatalogResponse(providers=providers)


@router.get(
    "/active",
    response_model=LLMActiveResponse,
    summary="Активный LLM-провайдер и модель",
)
def get_active_llm() -> LLMActiveResponse:
    provider_name, model = llm_registry.get_active()
    label = llm_registry.MODELS_CATALOG.get(provider_name, {}).get("label", provider_name)
    return LLMActiveResponse(provider=provider_name, model=model, label=label)


@router.patch(
    "/active",
    response_model=LLMActiveResponse,
    summary="Сменить активный LLM-провайдер / модель",
)
def set_active_llm(body: LLMActiveRequest) -> LLMActiveResponse:
    """
    Меняет провайдер и модель в рантайме (до перезапуска сервера).
    Для сохранения между перезапусками — обновите .env (LLM_PROVIDER, LLM_MODEL).
    """
    try:
        llm_registry.set_active(body.provider, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    label = llm_registry.MODELS_CATALOG.get(body.provider, {}).get("label", body.provider)
    return LLMActiveResponse(provider=body.provider, model=body.model, label=label)
