"""
Structured log event name constants.
Always pass as the first positional arg to the logger:
    logger.info(Events.COLLECTION_JOB_FINISHED, message="...", job_id=...)
"""


class Events:
    # ── Collection jobs ────────────────────────────────────────────────────
    COLLECTION_JOB_CREATED = "collection.job.created"
    COLLECTION_JOB_QUEUED = "collection.job.queued"
    COLLECTION_JOB_STARTED = "collection.job.started"
    COLLECTION_JOB_FINISHED = "collection.job.finished"
    COLLECTION_JOB_FAILED = "collection.job.failed"
    COLLECTION_JOB_CANCELLED = "collection.job.cancelled"
    COLLECTION_JOB_TIMEOUT = "collection.job.timeout"

    # ── Source lifecycle ───────────────────────────────────────────────────
    COLLECTION_SOURCE_LOCKED = "collection.source.locked"
    COLLECTION_SOURCE_UNLOCKED = "collection.source.unlocked"
    COLLECTION_SOURCE_SKIPPED = "collection.source.skipped_already_running"
    COLLECTION_SOURCE_VALIDATION_STARTED = "collection.source.validation.started"
    COLLECTION_SOURCE_VALIDATION_FINISHED = "collection.source.validation.finished"

    # ── Telegram ───────────────────────────────────────────────────────────
    COLLECTION_TELEGRAM_CONNECT_STARTED = "collection.telegram.connect.started"
    COLLECTION_TELEGRAM_CONNECT_FAILED = "collection.telegram.connect.failed"
    COLLECTION_TELEGRAM_FETCH_STARTED = "collection.telegram.fetch.started"
    COLLECTION_TELEGRAM_FETCH_FINISHED = "collection.telegram.fetch.finished"
    COLLECTION_TELEGRAM_FLOOD_WAIT = "collection.telegram.flood_wait"

    # ── VK ─────────────────────────────────────────────────────────────────
    COLLECTION_VK_TOKEN_INVALID = "collection.vk.token.invalid"
    COLLECTION_VK_RATE_LIMIT = "collection.vk.rate_limit"
    COLLECTION_VK_FETCH_STARTED = "collection.vk.fetch.started"
    COLLECTION_VK_FETCH_FINISHED = "collection.vk.fetch.finished"

    # ── News / HTTP ────────────────────────────────────────────────────────
    COLLECTION_NEWS_HTTP_REQUEST = "collection.news.http.request"
    COLLECTION_NEWS_HTTP_FAILED = "collection.news.http.failed"
    COLLECTION_NEWS_PARSE_FAILED = "collection.news.parse.failed"

    # ── Normalize & dedup ─────────────────────────────────────────────────
    COLLECTION_NORMALIZE_STARTED = "collection.normalize.started"
    COLLECTION_NORMALIZE_FAILED = "collection.normalize.failed"
    COLLECTION_DEDUP_STARTED = "collection.dedup.started"
    COLLECTION_DEDUP_FINISHED = "collection.dedup.finished"

    # ── Media ──────────────────────────────────────────────────────────────
    COLLECTION_MEDIA_DETECTED = "collection.media.detected"
    COLLECTION_MEDIA_DOWNLOAD_STARTED = "collection.media.download.started"
    COLLECTION_MEDIA_DOWNLOAD_FINISHED = "collection.media.download.finished"
    COLLECTION_MEDIA_DOWNLOAD_FAILED = "collection.media.download.failed"

    # ── State ──────────────────────────────────────────────────────────────
    COLLECTION_STATE_UPDATED = "collection.state.updated"
    COLLECTION_STATE_ROLLBACK = "collection.state.rollback"

    # ── Scheduler ──────────────────────────────────────────────────────────
    SCHEDULER_TICK = "scheduler.tick"
    SCHEDULER_SOURCE_DUE = "scheduler.source.due"
    SCHEDULER_JOB_ENQUEUED = "scheduler.job.enqueued"

    # ── Worker ─────────────────────────────────────────────────────────────
    WORKER_HEARTBEAT = "worker.heartbeat"
    WORKER_SHUTDOWN = "worker.shutdown"
    WORKER_UNEXPECTED_ERROR = "worker.unexpected_error"

    # ── HTTP requests (middleware) ─────────────────────────────────────────
    HTTP_REQUEST_STARTED = "http.request.started"
    HTTP_REQUEST_FINISHED = "http.request.finished"
    HTTP_REQUEST_ERROR = "http.request.error"
