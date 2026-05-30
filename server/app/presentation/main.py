from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.application.services.content.clustering_runner import runner as clustering_runner
from app.application.services.content import embedder
from app.application.services.scheduler.runner import scheduler
from app.application.services.worker.runner import worker as collection_worker
from app.core.config import get_settings
from app.presentation.api.routes import collect, content, sources
from app.presentation.api.routes.clusters import router as clusters_router
from app.presentation.api.routes.source_categories import router as source_categories_router
from app.presentation.api.routes.collection import router as collection_router
from app.presentation.api.routes.posts import router as posts_router
from app.presentation.api.routes.schedule import router as schedule_router
from app.presentation.api.routes.vk import router as vk_router
from app.presentation.middleware.request_logging import RequestLoggingMiddleware
from app.utils.log_events import Events
from app.utils.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(Events.WORKER_HEARTBEAT, message="Application startup", environment=settings.app_env)
    if settings.clustering_enabled:
        # Прогреваем модель заранее — чтобы первый запрос к /clusters/run
        # не тратил 10+ секунд на загрузку и не гонялся с фоновым runner'ом.
        # Не падаем при ошибке: модель подгрузится лениво при первом запросе.
        import asyncio
        try:
            await asyncio.to_thread(embedder._get_model)
        except Exception as exc:
            logger.warning("embedder_warmup_failed", error=str(exc))
    collection_worker.start()
    scheduler.start()
    clustering_runner.start()
    yield
    logger.info(Events.WORKER_SHUTDOWN, message="Application shutdown")
    await clustering_runner.stop()
    await scheduler.stop()
    await collection_worker.stop()


app = FastAPI(
    title="Destructive Content Analyzer",
    description=(
        "Detects destructive social-media content and identifies psychologically "
        "vulnerable users using LLM and PostgreSQL."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        Events.HTTP_REQUEST_ERROR,
        message="Unhandled server error",
        path=request.url.path,
        method=request.method,
        error_code=type(exc).__name__,
        error_message=str(exc)[:500],
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# Register routers
app.include_router(content.router)
app.include_router(sources.router)
app.include_router(posts_router)
app.include_router(collect.router)
app.include_router(collection_router)
app.include_router(vk_router)
app.include_router(schedule_router)
app.include_router(clusters_router)
app.include_router(source_categories_router)


@app.get("/health", tags=["Health"], summary="Liveness probe")
async def health() -> dict:
    return {
        "status": "ok",
        "env": settings.app_env,
        "worker": {
            "id": collection_worker.worker_id,
            "running": collection_worker.is_running,
            "active_jobs": collection_worker.running_jobs,
        },
        "scheduler": scheduler.state(),
        "clustering": clustering_runner.state(),
    }
