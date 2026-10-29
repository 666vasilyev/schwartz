"""
Проект «воздействие» (vozd) — /api/v1/vozd

Социальные группы (название/описание — оператор, состав — паблики VK и каналы Telegram),
фоновый сбор, данные группы с участниками и JSON-дамп.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.session import get_db
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.presentation.api.dependencies import get_current_user
from app.presentation.schemas.vozd import (
    VozdBlacklistUserAdd,
    VozdBlacklistWordsAdd,
    VozdCollectRequest,
    VozdGroupCreate,
    VozdGroupUpdate,
    VozdSourceAdd,
)
from app.use_case.vozd import dataset as dataset_uc
from app.use_case.vozd import dump as dump_uc
from app.use_case.vozd import groups as uc


async def get_vozd_session() -> AsyncGenerator[AsyncSession, None]:
    """Сессия со scope проекта vozd (обычные сессии видят только wall)."""
    async for session in get_db():
        use_project_scope(session, PROJECT_VOZD)
        yield session


router = APIRouter(prefix="/api/v1/vozd", tags=["Vozd"], dependencies=[Depends(get_current_user)])


@router.post("/groups", status_code=status.HTTP_201_CREATED, summary="Создать социальную группу")
async def create_group(body: VozdGroupCreate, db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.create_group(db, body)


@router.get("/groups", summary="Список социальных групп мониторинга")
async def list_groups(
    q: str | None = Query(None, max_length=255, description="Поиск по названию и описанию; без q — все группы"),
    skip: int = Query(0, ge=0, description="Сколько групп пропустить (для бесконечной прокрутки)"),
    limit: int = Query(50, ge=1, le=200, description="Сколько групп вернуть"),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    return await uc.list_groups(db, q=q, skip=skip, limit=limit)


@router.get("/groups/{group_id}", summary="Группа: название, описание, состав, статистика")
async def get_group(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.group_detail(db, group_id)


@router.patch("/groups/{group_id}", summary="Изменить название, описание, параметры сбора")
async def update_group(
    body: VozdGroupUpdate, group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.update_group(db, group_id, body)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить группу (мягко)")
async def delete_group(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> Response:
    await uc.delete_group(db, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/groups/{group_id}/sources", summary="Добавить паблики/каналы в состав группы")
async def add_sources(
    body: VozdSourceAdd, group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.add_sources(db, group_id, body.sources)


@router.delete("/groups/{group_id}/sources/{source_id}", summary="Убрать источник из состава группы")
async def remove_source(
    group_id: int = Path(..., ge=1), source_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.remove_source(db, group_id, source_id)


@router.get("/groups/{group_id}/data", summary="Данные группы: посты, комментарии, участники (постранично)")
async def group_data(
    group_id: int = Path(..., ge=1),
    posts_skip: int = Query(0, ge=0),
    posts_limit: int = Query(50, ge=0, le=500),
    users_skip: int = Query(0, ge=0),
    users_limit: int = Query(100, ge=0, le=1000),
    include_profiles: bool = Query(True, description="Включить профили участников (группы, друзья, посты)"),
    users_q: str | None = Query(
        None, max_length=255, description="Поиск среди участников: имя, фамилия, username, id или uid (vk:123)"
    ),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    return await uc.group_data(
        db,
        group_id,
        posts_skip=posts_skip,
        posts_limit=posts_limit,
        users_skip=users_skip,
        users_limit=users_limit,
        include_profiles=include_profiles,
        users_q=users_q,
    )


@router.get("/groups/{group_id}/dump", summary="JSON-дамп всех данных группы (потоком)")
async def group_dump(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> StreamingResponse:
    await uc.group_detail(db, group_id)  # 404 до начала стрима
    return StreamingResponse(
        dump_uc.iter_dump(group_id),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=vozd_group_{group_id}.json"},
    )


@router.post("/groups/{group_id}/collect", status_code=status.HTTP_202_ACCEPTED, summary="Запустить сбор (фоновый прогон)")
async def collect(
    body: VozdCollectRequest | None = None,
    group_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    return await uc.start_collect(db, group_id, body or VozdCollectRequest())


@router.get("/groups/{group_id}/runs", summary="История прогонов группы")
async def list_runs(
    group_id: int = Path(..., ge=1), limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.list_runs(db, group_id, limit)


@router.get("/runs/{run_id}", summary="Статус и прогресс прогона")
async def get_run(run_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.get_run(db, run_id)


@router.post("/runs/{run_id}/cancel", summary="Отменить прогон")
async def cancel_run(run_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.cancel_run(db, run_id)


@router.get("/users/{platform}/{external_id}", summary="Профиль пользователя и что/где он писал")
async def get_user(
    platform: str = Path(..., pattern="^(vk|telegram)$"),
    external_id: int = Path(..., ge=1),
    group_id: int | None = Query(None, ge=1, description="Ограничить одной социальной группой"),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    if platform not in ("vk", "telegram"):
        raise HTTPException(status_code=422, detail="platform: vk | telegram")
    return await uc.user_profile(db, platform, external_id, group_id)


# ── чёрные списки группы ────────────────────────────────────────────────────


@router.get("/groups/{group_id}/blacklist/users", summary="Чёрный список пользователей группы")
async def blacklist_users(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.blacklist_users(db, group_id)


@router.post("/groups/{group_id}/blacklist/users", summary="Добавить пользователя в чёрный список группы")
async def blacklist_add_user(
    body: VozdBlacklistUserAdd, group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.blacklist_add_user(db, group_id, body.uid, body.note)


@router.delete("/groups/{group_id}/blacklist/users/{uid}", summary="Убрать пользователя из чёрного списка (uid: vk:123)")
async def blacklist_remove_user(
    group_id: int = Path(..., ge=1), uid: str = Path(...), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.blacklist_remove_user(db, group_id, uid)


@router.get("/groups/{group_id}/blacklist/words", summary="Чёрный список слов группы")
async def blacklist_words(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    return await uc.blacklist_words(db, group_id)


@router.post("/groups/{group_id}/blacklist/words", summary="Добавить слова в чёрный список группы")
async def blacklist_add_words(
    body: VozdBlacklistWordsAdd, group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.blacklist_add_words(db, group_id, body.words)


@router.delete("/groups/{group_id}/blacklist/words/{word_id}", summary="Убрать слово из чёрного списка")
async def blacklist_remove_word(
    group_id: int = Path(..., ge=1), word_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await uc.blacklist_remove_word(db, group_id, word_id)


_DATASET_DOC = (
    "Датасет группы: название, описание, ресурсы (паблики) и комментаторы по убыванию числа комментариев — "
    "у каждого его комментарии (с указанием паблика) и информация о пользователе."
)


@router.get("/groups/{group_id}/dataset", summary="Датасет группы по id", description=_DATASET_DOC)
async def group_dataset_by_id(
    group_id: int = Path(..., ge=1),
    min_comments: int = Query(1, ge=1, description="Минимум комментариев у комментатора"),
    skip: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=5000, description="Сколько комментаторов вернуть (по умолчанию все)"),
    include: str = Query("groups", description="Что добавить к профилю: groups, friends, posts (через запятую), all или none"),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    group = await uc._get_group(db, group_id)
    return await dataset_uc.build_dataset(
        db, group, min_comments=min_comments, skip=skip, limit=limit, include=dataset_uc.parse_include(include)
    )


# Регистрируется последним: путь из одного сегмента не должен перехватывать /groups, /runs, /users.
@router.get("/{group_name}", summary="Датасет группы по названию", description=_DATASET_DOC)
async def group_dataset_by_name(
    group_name: str = Path(..., min_length=1, description="Название социальной группы (URL-кодированное)"),
    min_comments: int = Query(1, ge=1, description="Минимум комментариев у комментатора"),
    skip: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=5000, description="Сколько комментаторов вернуть (по умолчанию все)"),
    include: str = Query("groups", description="Что добавить к профилю: groups, friends, posts (через запятую), all или none"),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    include_parts = dataset_uc.parse_include(include)
    group = await dataset_uc.get_group_by_name(db, group_name)
    return await dataset_uc.build_dataset(
        db, group, min_comments=min_comments, skip=skip, limit=limit, include=include_parts
    )
