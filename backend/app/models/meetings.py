from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .mixins import IDMixin


class MeetingInvite(IDMixin, Base):
    __tablename__ = "meeting_invites"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    meeting_link: Mapped[str] = mapped_column(Text, nullable=False)
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeetingAvailabilityRequest(IDMixin, Base):
    __tablename__ = "meeting_availability_requests"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    option_1_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    option_2_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    option_3_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    customer_option_1_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_option_2_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    customer_option_3_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra_recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selected_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="sent", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)