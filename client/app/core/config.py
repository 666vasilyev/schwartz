from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    POSTGRES_HOST: str = Field(default="localhost", alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="strag", alias="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="123", alias="POSTGRES_PASSWORD")

    vk_api_version: str = "5.199"
    vk_api_base_url: str = "https://api.vk.com/method"
    vk_wall_owner_id: int | None = None
    # Сколько комментариев подтягивать на пост (wall.getComments)
    vk_comments_per_post: int = 20
    # Параллельные запросы комментариев (лимит нагрузки на API)
    vk_comment_fetch_concurrency: int = 5

    app_env: str = "development"
    log_level: str = "INFO"
    # Совпадает с server.collector_shared_secret; пустой — не требовать Bearer к POST /collect*
    collector_shared_secret: str = ""

    # Прокси для исходящих запросов: Telegram MTProto (например socks5://127.0.0.1:1080)
    proxy: str = ""

    # Telegram MTProto (Telethon)
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_string: str = ""  # StringSession от Telethon

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        user_quoted = quote_plus(self.POSTGRES_USER)
        password_quoted = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg://{user_quoted}:{password_quoted}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
