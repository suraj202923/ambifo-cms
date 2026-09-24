from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .mixins import IDMixin, TimestampMixin


class User(IDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)