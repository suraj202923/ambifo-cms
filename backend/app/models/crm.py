from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .mixins import IDMixin, TimestampMixin


class Customer(IDMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    alternate_emails: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cloud: Mapped[str | None] = mapped_column(String(80), nullable=True)
    main_page_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aws_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aws_calculator_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    segment: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    deal_status: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_planned: Mapped[str | None] = mapped_column(Text, nullable=True)
    assign_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    assigned_to: Mapped["User | None"] = relationship("User", foreign_keys=[assign_to_user_id])
    history_entries: Mapped[list["OpportunityHistory"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    financial_profile: Mapped["OpportunityFinancial | None"] = relationship(
        back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )


class OpportunityHistory(IDMixin, Base):
    __tablename__ = "opportunity_histories"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    changed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    tag_name: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    changes_summary: Mapped[str] = mapped_column(Text, nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    customer: Mapped["Customer"] = relationship(back_populates="history_entries")


class Lead(IDMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    lead_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    lead_status: Mapped[str] = mapped_column(String(40), default="new", nullable=False)
    last_emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_email_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True
    )

    converted_customer: Mapped["Customer | None"] = relationship(
        "Customer", foreign_keys=[converted_customer_id]
    )


class OpportunityStatus(IDMixin, Base):
    __tablename__ = "opportunity_statuses"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#8a8f98", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OpportunitySegment(IDMixin, Base):
    __tablename__ = "opportunity_segments"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    credit_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    credit_on_arr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credit_percentage_customer: Mapped[float | None] = mapped_column(Float, nullable=True)
    credit_percentage_ambifo: Mapped[float | None] = mapped_column(Float, nullable=True)
    credit_basis_mrr: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    credit_basis_arr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OpportunityFinancial(IDMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_financials"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    expected_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_arr: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_credit_customer: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_credit_ambifo: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_arr: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_credit_customer: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_credit_ambifo: Mapped[float | None] = mapped_column(Float, nullable=True)
    credits_requested: Mapped[float | None] = mapped_column(Float, nullable=True)
    credits_gets: Mapped[float | None] = mapped_column(Float, nullable=True)
    phases_to_distribute: Mapped[int | None] = mapped_column(Integer, nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="financial_profile")


class OpportunityCloudOperator(IDMixin, Base):
    __tablename__ = "opportunity_cloud_operators"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OpportunityUpdateTag(IDMixin, Base):
    __tablename__ = "opportunity_update_tags"

    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#6b7280", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PartnerReferenceContact(IDMixin, TimestampMixin, Base):
    __tablename__ = "partner_reference_contacts"

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id"), nullable=True, index=True
    )
    partner_name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(160), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    customer: Mapped["Customer | None"] = relationship("Customer")


class PartnerReferenceActivity(IDMixin, Base):
    __tablename__ = "partner_reference_activities"

    reference_contact_id: Mapped[int] = mapped_column(
        ForeignKey("partner_reference_contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(40), default="note", nullable=False)
    activity_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PartnerReferenceOpportunity(IDMixin, Base):
    __tablename__ = "partner_reference_opportunities"

    reference_contact_id: Mapped[int] = mapped_column(
        ForeignKey("partner_reference_contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("reference_contact_id", "customer_id", name="uq_ref_contact_customer"),
    )