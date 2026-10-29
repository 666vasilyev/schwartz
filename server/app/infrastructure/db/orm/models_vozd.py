"""Модели проекта «воздействие» (vozd): социальные группы, участники, профили, прогоны."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.orm.session import Base


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage:
    POSTS = "posts"
    COMMENTS = "comments"
    PROFILES = "profiles"
    DONE = "done"


social_group_sources = Table(
    "social_group_sources",
    Base.metadata,
    Column("group_id", Integer, ForeignKey("social_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", Integer, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_social_group_sources_source_id", "source_id"),
)


class SocialGroup(Base):
    """Социальная группа: название/описание задаёт оператор, состав — набор источников."""

    __tablename__ = "social_groups"
    __table_args__ = (
        Index(
            "uq_social_groups_name",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # posts_per_source, comments_enabled, collect_profiles, profile_posts_limit …
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VozdUser(Base):
    """Пользователь соцсети (участник обсуждений, автор). Уникален по (platform, external_id)."""

    __tablename__ = "vozd_users"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_vozd_users_platform_external"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # vk | telegram
    external_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # pending | ok | closed | deleted | banned | unavailable
    profile_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    friends_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    groups_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    posts_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VozdUserGroup(Base):
    __tablename__ = "vozd_user_groups"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vozd_users.id", ondelete="CASCADE"), primary_key=True
    )
    group_external_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    screen_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)


class VozdUserFriend(Base):
    __tablename__ = "vozd_user_friends"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vozd_users.id", ondelete="CASCADE"), primary_key=True
    )
    friend_external_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class VozdUserPost(Base):
    """Пост со стены пользователя (собственный или репост)."""

    __tablename__ = "vozd_user_posts"
    __table_args__ = (
        UniqueConstraint("user_id", "owner_id", "vk_post_id", name="uq_vozd_user_posts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vozd_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vk_post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_repost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    repost_of: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reactions: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class VozdRun(Base):
    """Прогон сбора для социальной группы: стадия, прогресс, чекпойнты."""

    __tablename__ = "vozd_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=RunStatus.QUEUED, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default=RunStage.POSTS)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VozdBlacklistUser(Base):
    """Чёрный список пользователей социальной группы: скрываются из выдачи и статистики."""

    __tablename__ = "vozd_blacklist_users"
    __table_args__ = (
        UniqueConstraint("group_id", "platform", "external_id", name="uq_vozd_blacklist_users"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # vk | telegram
    external_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VozdBlacklistWord(Base):
    """Чёрный список слов социальной группы: посты и комментарии с этими словами (с учётом словоформ)
    скрываются из выдачи и статистики."""

    __tablename__ = "vozd_blacklist_words"
    __table_args__ = (UniqueConstraint("group_id", "lemma", name="uq_vozd_blacklist_words"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    word: Mapped[str] = mapped_column(String(255), nullable=False)  # как ввёл оператор
    lemma: Mapped[str] = mapped_column(String(255), nullable=False)  # начальная форма (для сопоставления)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
