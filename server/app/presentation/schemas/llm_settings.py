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


class LLMPromptInfo(BaseModel):
    """Один промпт — метаданные (без содержимого, для списка)."""
    name: str = Field(description="Имя промпта (без расширения .txt) — используется в GET /prompts/{name}")
    filename: str = Field(description="Имя файла на диске")
    path: str = Field(description="Полный путь к файлу на сервере (внутри контейнера)")
    size_bytes: int = Field(description="Размер файла в байтах")
    modified_at: float = Field(description="Время последнего изменения файла (unix timestamp)")


class LLMPromptListResponse(BaseModel):
    """Список всех промптов, найденных в PROMPTS_ROOT."""
    prompts: list[LLMPromptInfo] = Field(description="Список промптов")


class LLMPromptContentResponse(BaseModel):
    """Содержимое одного промпта — текст файла как есть."""
    name: str = Field(description="Имя промпта")
    path: str = Field(description="Путь к файлу на сервере")
    content: str = Field(description="Содержимое файла как есть (без подстановки плейсхолдеров)")
