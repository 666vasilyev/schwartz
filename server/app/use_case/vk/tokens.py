"""VK token management: add, list, check, rotate."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.vk_access_token import (
    activate_token,
    add_token,
    deactivate_token,
    get_token_by_id,
    list_tokens,
)
from app.infrastructure.vk.client import check_token_valid
from app.presentation.schemas.vk import (
    VkTokenAddRequest,
    VkTokenCheckRequest,
    VkTokenCheckResponse,
    VkTokenListResponse,
    VkTokenRead,
    VkTokenRotateResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def add(db: AsyncSession, body: VkTokenAddRequest) -> VkTokenRead:
    token = await add_token(db, body.access_token)
    return VkTokenRead.model_validate(token)


async def get_list(db: AsyncSession) -> VkTokenListResponse:
    tokens = await list_tokens(db)
    items = [VkTokenRead.model_validate(t) for t in tokens]
    return VkTokenListResponse(items=items, total=len(items))


async def check(body: VkTokenCheckRequest) -> VkTokenCheckResponse:
    result = await check_token_valid(body.access_token)
    return VkTokenCheckResponse(
        valid=result.get("valid", False),
        user=result.get("user"),
        reason=result.get("reason"),
        code=result.get("code"),
    )


async def rotate(
    db: AsyncSession,
    old_token_id: int,
    body: VkTokenAddRequest,
) -> VkTokenRotateResponse:
    """Deactivate old token and add the new one."""
    old = await get_token_by_id(db, old_token_id)
    if old is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Токен не найден")

    check_result = await check_token_valid(body.access_token)
    new_valid = check_result.get("valid", False)

    await deactivate_token(db, old_token_id)
    new_token = await add_token(db, body.access_token)

    return VkTokenRotateResponse(
        deactivated_id=old_token_id,
        new_id=new_token.id,
        new_token_valid=new_valid,
    )


async def toggle_active(db: AsyncSession, token_id: int, *, active: bool) -> VkTokenRead:
    fn = activate_token if active else deactivate_token
    found = await fn(db, token_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Токен не найден")
    token = await get_token_by_id(db, token_id)
    return VkTokenRead.model_validate(token)
