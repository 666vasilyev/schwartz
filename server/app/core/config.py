from functools import lru_cache
from pydantic import Field
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "ollama"
    llm_model: str = "gemma4:31b"

    # Ollama — локальный сервер с открытыми моделями
    ollama_base_url: str = "http://10.0.21.10:11434/v1"

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = "https://api.openai.com/v1"

    # Прокси для Telegram MTProto (например socks5://host-gateway:1080)
    proxy: str = ""

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    destruct_threshold: float = 0.75
    POSTGRES_HOST: str = Field(default="localhost", alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="strag", alias="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="123", alias="POSTGRES_PASSWORD")

    # Токены VK только из таблицы vk_access_tokens (см. миграции)
    vk_api_version: str = "5.199"
    vk_api_base_url: str = "https://api.vk.com/method"

    # Telegram MTProto (Telethon) — для сбора с Telegram-каналов
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_string: str = ""  # StringSession от Telethon

    # HTTP collector (client): GET /collect на сервере вызывает POST …/collect/public
    collector_base_url: str = Field(
        default="http://127.0.0.1:8080",
        description="База URL клиента-сборщика, например http://client:8080",
    )
    # Тот же секрет, что у collector; пустой — без заголовка Authorization (локальная разработка)
    collector_shared_secret: str = ""

    # ── Clustering / embeddings ────────────────────────────────────────────
    # Имя модели sentence-transformers; должно соответствовать embedding_dim
    embedding_model_name: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768
    # Максимальная длина текста, отдаваемая модели (символы, не токены).
    embedding_max_chars: int = 2000
    # Сколько постов считать за один вызов encode(); подбирается под RAM/CPU
    embedding_batch_size: int = 32

    # Порог cosine similarity для отнесения поста к существующему сюжету.
    # 1.0 — идентично, 0.0 — ортогонально. 0.78–0.85 — типовой диапазон для новостей.
    cluster_similarity_threshold: float = 0.82
    # Скользящее окно для поиска кандидатов-кластеров (дней).
    cluster_window_days: int = 7
    # Минимум постов в сюжете, чтобы он считался "созревшим" (для тренд-выборки).
    cluster_min_size_for_trending: int = 3
    # Период фоновой задачи кластеризации (секунды).
    clustering_tick_seconds: int = 120
    # Максимум постов, обрабатываемых за один тик (защита от длинных батчей).
    clustering_batch_size: int = 200
    # Включена ли фоновая задача кластеризации (в тестах можно выключить).
    clustering_enabled: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        # Используем psycopg (синхронный) вместо asyncpg из-за проблем совместимости с Python 3.14
        user_quoted = quote_plus(self.POSTGRES_USER)
        password_quoted = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg://{user_quoted}:{password_quoted}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    
    @property
    def SYNC_DATABASE_URL(self) -> str:
        user_quoted = quote_plus(self.POSTGRES_USER)
        password_quoted = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg://{user_quoted}:{password_quoted}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )



@lru_cache
def get_settings() -> Settings:
    return Settings()
