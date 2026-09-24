from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, update
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .mixins import IDMixin, TimestampMixin


class CustomerDocument(IDMixin, Base):
    __tablename__ = "customer_documents"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    blob_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    storage_backend: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    docusign_envelope_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    docusign_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    docusign_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    docusign_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    docusign_signer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docusign_signer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signed_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CustomerDiagram(IDMixin, TimestampMixin, Base):
    __tablename__ = "customer_diagrams"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    diagram_name: Mapped[str] = mapped_column(String(160), nullable=False)
    macro_key: Mapped[str] = mapped_column(String(80), nullable=False)
    diagram_content: Mapped[str] = mapped_column(Text, nullable=False)
    aws_calculator_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class CustomerSOW(IDMixin, TimestampMixin, Base):
    __tablename__ = "customer_sows"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sow_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    master_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    selected_diagram_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    sow_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    docusign_envelope_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    docusign_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    docusign_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    docusign_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    docusign_signer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docusign_signer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signed_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class SOWMasterTemplate(IDMixin, TimestampMixin, Base):
    __tablename__ = "sow_master_templates"

    template_key: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, default="default", nullable=False
    )
    template_name: Mapped[str] = mapped_column(String(120), default="Default Template", nullable=False)
    section_about: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_offerings: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_business_background: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_project_overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_problem_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_document_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_proposed_solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_scope_schedule: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_project_governance: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_commercials_signoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    sections: Mapped[list["SOWMasterTemplateSection"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class SOWMasterTemplateSection(IDMixin, TimestampMixin, Base):
    __tablename__ = "sow_master_template_sections"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("sow_master_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)

    template: Mapped["SOWMasterTemplate"] = relationship(back_populates="sections")