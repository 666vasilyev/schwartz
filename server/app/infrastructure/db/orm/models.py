from datetime import datetime
from enum import StrEnum
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.core.config import get_settings
from app.infrastructure.db.orm.session import Base

_settings = get_settings()
EMBEDDING_DIM = _settings.embedding_dim


class SourceType(StrEnum):
    VK_GROUP = "vk_group"
    VK_PUBLIC = "vk_public"
    RSS = "rss"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"
    BLOCKED = "blocked"
    DELETED = "deleted"


class SourceCategory(StrEnum):
    """Оставлен для обратной совместимости. Новые категории — в таблице source_categories."""
    RU_SMI = "ru_smi"
    UA_SMI = "ua_smi"
    FOREIGN_SMI = "foreign_smi"


class SourceCategoryModel(Base):
    """Категория источника — управляемая сущность (CRUD через API)."""

    __tablename__ = "source_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sources: Mapped[list["Source"]] = relationship(back_populates="source_category")


class Source(Base):
    """Источник для сборщика: VK группа/паблик, RSS/Atom и др."""

    __tablename__ = "sources"
    __table_args__ = (
        Index(
            "uq_sources_platform_external_id",
            "platform",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_sources_platform_username",
            "platform",
            "username",
            unique=True,
            postgresql_where=text("username IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Granular type: vk_group, vk_public, rss
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Platform bucket: "vk" or "rss"
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Screen name / slug (e.g. "durov", "public123")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Platform-specific external ID (VK owner_id as string, RSS feed ID)
    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SourceStatus.ACTIVE.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Auth / token required flag
    auth_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Policy configs (JSON dicts)
    collection_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    media_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Hints for downstream processors
    language_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    region_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # User/org binding
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # FK to managed source_categories table
    category_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("source_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_category: Mapped["SourceCategoryModel | None"] = relationship(
        back_populates="sources"
    )

    # Rich metadata fetched from the source (VK group info, RSS feed title, etc.)
    source_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Legacy fields kept for backward compatibility with collect logic
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="vk", index=True)
    vk_owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Schedule group tag (for group-level schedule rules)
    schedule_group: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    audit_logs: Mapped[list["SourceAuditLog"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SourceAuditLog(Base):
    """Журнал изменений источника: включение, отключение, расписание, токены."""

    __tablename__ = "source_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # enable | disable | pause | schedule_changed | credentials_changed | settings_changed
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="audit_logs")


class SourceSchwartzAnalysis(Base):
    """
    Агрегированные по источнику средние значения Шварца.
    Одна строка на источник; при новом анализе заменяется.
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


class JobType(StrEnum):
    MANUAL_FETCH = "manual_fetch"
    SCHEDULED_FETCH = "scheduled_fetch"
    HISTORICAL_FETCH = "historical_fetch"
    METADATA_REFRESH = "metadata_refresh"
    MEDIA_DOWNLOAD = "media_download"
    RETRY_FAILED = "retry_failed"


class JobStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULER = "scheduler"
    API = "api"
    SYSTEM = "system"
    RETRY = "retry"


class CollectionJob(Base):
    """Задача сбора: полная история, статус, статистика, повторные попытки."""

    __tablename__ = "collection_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=JobStatus.CREATED.value, index=True
    )
    trigger_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TriggerType.MANUAL.value
    )
    # 1 = highest priority, 10 = lowest
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    requested_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Public-safe error (no sensitive data, no traceback)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    logs: Mapped[list["CollectionJobLog"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CollectionJobLog(Base):
    """Структурированные события выполнения задачи (без traceback)."""

    __tablename__ = "collection_job_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("collection_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["CollectionJob"] = relationship(back_populates="logs")


class DeadLetterJob(Base):
    """Задачи, исчерпавшие все попытки выполнения."""

    __tablename__ = "dead_letter_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("collection_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VkAccessToken(Base):
    """User access token VK: ротация по полю usage (меньше — приоритетнее)."""

    __tablename__ = "vk_access_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScheduleRuleType(StrEnum):
    SOURCE = "source"      # per source
    PLATFORM = "platform"  # all sources on a platform
    GROUP = "group"        # named group of sources


class ScheduleRule(Base):
    """
    Scheduling rule for collection jobs.
    Specificity order: source > group > platform (most specific wins).
    """

    __tablename__ = "schedule_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Target: exactly one of these is set depending on rule_type
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    group_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Interval config (minutes)
    base_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10080)  # 1 week

    # Error backoff
    error_backoff_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    max_error_backoff_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=480)

    # Priority boost: reduces interval for high-priority sources
    priority_boost_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Night mode: extend interval during off-hours
    night_mode_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    night_start_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=23)
    night_end_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    night_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)

    # Rate limiting
    max_jobs_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    logs: Mapped[list["ScheduleLog"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ScheduleLog(Base):
    """Record of each scheduler firing: which rule, which source, outcome."""

    __tablename__ = "schedule_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("schedule_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("collection_jobs.id", ondelete="SET NULL"), nullable=True
    )
    # scheduled | manual | error_recovery | skipped_rate_limit | skipped_night_mode
    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="scheduled")
    calculated_interval_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    rule: Mapped["ScheduleRule | None"] = relationship(back_populates="logs")


# ─── Clustering / embeddings ───────────────────────────────────────────────


class StoryClusterStatus(StrEnum):
    ACTIVE = "active"      # ещё могут приходить новые посты
    ARCHIVED = "archived"  # вне окна, не пополняется


class PostEmbedding(Base):
    """
    Эмбеддинг текста поста. Отдельная таблица, чтобы:
      - не утяжелять `posts` тяжёлым VECTOR-столбцом;
      - легко перегенерировать при смене модели (truncate + перерасчёт);
      - индексировать HNSW только по эмбеддингам.
    """

    __tablename__ = "post_embeddings"

    post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Хэш входного текста — чтобы понимать, что пост менялся и эмбеддинг устарел
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StoryCluster(Base):
    """
    Сюжетный кластер: несколько постов из разных источников об одном событии.
    Центроид пересчитывается онлайн при добавлении поста.
    """

    __tablename__ = "story_clusters"
    __table_args__ = (
        Index("ix_story_clusters_status_last_seen", "status", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    centroid: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    # Имя модели, которой считался центроид; при смене — кластер инвалидируется
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Человекочитаемое имя/заголовок сюжета (генерится LLM один раз и обновляется)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Сводка-сюжет (1–3 предложения, опционально от LLM)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Динамические темы/ярлыки от LLM, например ["конфликт", "энергетика"]
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=StoryClusterStatus.ACTIVE.value, index=True
    )

    posts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sources_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Когда последний раз обновляли title/summary/topics через LLM
    labels_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    assignments: Mapped[list["PostClusterAssignment"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PostClusterAssignment(Base):
    """
    Назначение поста сюжетному кластеру (N:1). Пост может принадлежать только одному
    активному сюжету. При перекластеризации история ассайнментов не хранится —
    просто перезаписывается.
    """

    __tablename__ = "post_cluster_assignments"
    __table_args__ = (
        Index(
            "ix_pca_cluster_id_assigned_at",
            "cluster_id",
            "assigned_at",
        ),
    )

    post_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cluster_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("story_clusters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    cluster: Mapped["StoryCluster"] = relationship(back_populates="assignments")
