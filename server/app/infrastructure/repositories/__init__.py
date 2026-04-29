"""Репозитории доступа к сущностям БД (по одному модулю на сущность/группу)."""
from .common import utcnow
from .post import (
    get_post_by_id,
    get_post_by_source_and_external,
    get_post_by_vk_id,
    get_recent_posts,
    list_posts_by_owner_id,
    list_posts_by_source_id,
    save_post,
)
from .post_comment import replace_comments_from_vk_collect
from .source import (
    add_source,
    count_sources,
    delete_source,
    get_source_by_id,
    list_sources,
    update_source,
)
from .source_schwartz import (
    get_source_schwartz_by_source_id,
    replace_source_schwartz,
)

__all__ = [
    "add_source",
    "count_sources",
    "delete_source",
    "get_post_by_id",
    "get_post_by_source_and_external",
    "get_post_by_vk_id",
    "get_recent_posts",
    "get_source_by_id",
    "get_source_schwartz_by_source_id",
    "list_posts_by_owner_id",
    "list_posts_by_source_id",
    "list_sources",
    "replace_comments_from_vk_collect",
    "replace_source_schwartz",
    "save_post",
    "update_source",
    "utcnow",
]
