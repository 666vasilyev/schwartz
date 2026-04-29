from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.orm.session import Base


class VkAccessToken(Base):
    """Строки таблицы vk_access_tokens — дубль схемы server/app/.../models.py."""

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
