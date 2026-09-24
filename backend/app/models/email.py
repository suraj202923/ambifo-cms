from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .mixins import IDMixin


class EmailTemplate(IDMixin, Base):
    __tablename__ = "email_templates"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    subject_template: Mapped[str] = mapped_column(String(255), nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailLog(IDMixin, Base):
    __tablename__ = "email_logs"

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_templates.id"), nullable=True
    )
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cc_emails: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bcc_emails: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    queue_status: Mapped[str] = mapped_column(String(20), default="immediate", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    csv_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_bulk_csv_executions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    csv_execution: Mapped["EmailBulkCsvExecution | None"] = relationship(
        back_populates="logs"
    )


class EmailUnsubscribe(IDMixin, Base):
    __tablename__ = "email_unsubscribes"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unsubscribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailBulkCsvExecution(IDMixin, Base):
    __tablename__ = "email_bulk_csv_executions"

    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_templates.id"), nullable=True
    )
    uploaded_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    bad_log_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    success_log_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsubscribed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    logs: Mapped[list["EmailLog"]] = relationship(back_populates="csv_execution")