from datetime import datetime
from enum import StrEnum
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.infrastructure.db.orm.session import Base


class SourceStatus(StrEnum):
    """Статус в UI (Figma: зел./оранж./крас. и сценарии play/pause)."""

    IDLE = "idle"  # ещё не запускали
    RUNNING = "running"  # идёт сбор
    OK = "ok"  # успех (зелёный)
    WARNING = "warning"  # предупреждение (оранжевый)
    ERROR = "error"  # ошибка (красный)
    PAUSED = "paused"  # на паузе


class Source(Base):
    """Источник для сборщика: VK, RSS/Atom и др.; общие поля + опционально extra (JSON)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # «Название сборщика» в UI
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # «Ссылка» — нормализованный URL (https://vk.com/… или URL ленты)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Тип источника: vk, rss, …
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="vk", index=True
    )
    # Произвольные метаданные (например заголовок ленты после collect)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # «Статус» — бейдж в списке источников
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SourceStatus.IDLE.value,
        index=True,
    )
    # owner_id стены wall.get: группа/паблик < 0, пользователь > 0
    vk_owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # «Дата» в таблице — последний успешный/завершённый запуск (nullable до первого)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Текст при status=error (и при необходимости при warning)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    schwartz_analysis: Mapped["SourceSchwartzAnalysis | None"] = relationship(
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )


class SourceSchwartzAnalysis(Base):
    """
    Агрегированные по источнику средние значения Шварца (последний прогон POST /analyze/source/…).
    Одна строка на источник: при новом анализе заменяется.
    """

    __tablename__ = "source_schwartz_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    self_direction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stimulation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hedonism: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    achievement: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    power: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    security: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conformity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tradition: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    benevolence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    universalism: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="schwartz_analysis")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Идентификатор записи вне платформы (guid RSS и т.д.); для VK можно не задавать
    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    vk_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    is_ad: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reactions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Полный снимок collect (в т.ч. дерево комментариев в JSON)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    comments: Mapped[list["PostComment"]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PostComment(Base):
    """Комментарий к посту (VK); ответы — через parent_id."""

    __tablename__ = "post_comments"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "source_comment_id",
            name="uq_post_comments_post_source_comment",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_comment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("post_comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    from_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    post: Mapped["Post"] = relationship(back_populates="comments")
