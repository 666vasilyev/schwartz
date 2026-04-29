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

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    destruct_threshold: float = 0.75
    POSTGRES_HOST: str = Field(default="localhost", alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="strag", alias="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="123", alias="POSTGRES_PASSWORD")

    # Опционально: тот же user-токен, что у клиента — чтобы при POST /sources сразу заполнить vk_owner_id
    vk_api_token: str = ""
    vk_api_version: str = "5.199"
    vk_api_base_url: str = "https://api.vk.com/method"

    # HTTP collector (client): GET /collect на сервере вызывает POST …/collect/public
    collector_base_url: str = Field(
        default="http://127.0.0.1:8080",
        description="База URL клиента-сборщика, например http://client:8080",
    )

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
