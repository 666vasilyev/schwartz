from pydantic import BaseModel, Field


class LLMModelGroup(BaseModel):
    """Группа моделей одного провайдера (для отображения на фронте «папкой»)."""
    label: str = Field(description="Отображаемое название провайдера")
    models: list[str] = Field(description="Список доступных моделей")


class LLMCatalogResponse(BaseModel):
    """Каталог всех провайдеров и их моделей."""
    providers: dict[str, LLMModelGroup] = Field(
        description="Ключ — идентификатор провайдера (openai, deepseek, gigachat, yandexgpt)"
    )


class LLMActiveResponse(BaseModel):
    """Текущий активный провайдер и модель."""
    provider: str = Field(description="Идентификатор активного провайдера")
    model: str = Field(description="Активная модель")
    label: str = Field(description="Отображаемое название провайдера")


class LLMActiveRequest(BaseModel):
    """Запрос на смену провайдера / модели."""
    provider: str = Field(description="Идентификатор провайдера")
    model: str = Field(description="Название модели")
