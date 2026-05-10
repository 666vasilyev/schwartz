"""Check whether a VK group is accessible via wall.get."""
from __future__ import annotations

from app.infrastructure.vk.client import VKApiError, VkAccessDenied, VkAuthError, wall_get
from app.presentation.schemas.vk import VkValidateRequest, VkValidateResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(body: VkValidateRequest) -> VkValidateResponse:
    try:
        resp = await wall_get(body.owner_id, count=1)
        accessible = "items" in resp
        return VkValidateResponse(accessible=accessible, owner_id=body.owner_id)
    except VkAccessDenied as exc:
        return VkValidateResponse(accessible=False, owner_id=body.owner_id, reason=str(exc))
    except VkAuthError as exc:
        return VkValidateResponse(accessible=False, owner_id=body.owner_id, reason=str(exc))
    except VKApiError as exc:
        return VkValidateResponse(accessible=False, owner_id=body.owner_id, reason=str(exc))
    except Exception as exc:
        logger.warning("vk_validate_error", owner_id=body.owner_id, error=str(exc))
        return VkValidateResponse(accessible=False, owner_id=body.owner_id, reason=str(exc))
