from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .mixins import IDMixin


class SystemSetting(IDMixin, Base):
    __tablename__ = "system_settings"

    setting_key: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    setting_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    @classmethod
    def normalize_value(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)