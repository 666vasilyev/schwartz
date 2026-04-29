from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    vk_api_token: str = ""
    vk_api_version: str = "5.199"
    vk_api_base_url: str = "https://api.vk.com/method"
    vk_wall_owner_id: int | None = None
    # Сколько комментариев подтягивать на пост (wall.getComments)
    vk_comments_per_post: int = 20
    # Параллельные запросы комментариев (лимит нагрузки на API)
    vk_comment_fetch_concurrency: int = 5

    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
