from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------- Email
class EmailTemplateBase(BaseModel):
    name: str
    subject_template: str
    body_template: str
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    pass


class EmailTemplateUpdate(BaseModel):
    name: str | None = None
    subject_template: str | None = None
    body_template: str | None = None
    is_active: bool | None = None


class EmailTemplateOut(EmailTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    is_system: bool = False


class EmailSendIn(BaseModel):
    email_type: str = "general"
    recipient_email: EmailStr
    template_id: int | None = None
    subject: str | None = None
    body: str | None = None
    context: dict = Field(default_factory=dict)
    customer_id: int | None = None
    cc_emails: list[EmailStr] | None = None
    include_alternate_cc: bool = False


class EmailSendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient_email: str
    email_type: str
    subject: str
    status: str
    queue_status: str


BulkEmailMode = Literal[
    "all_customers",
    "all_leads",
    "customers_by_status",
    "customers_by_segment",
    "select_customers",
    "manual_emails",
]

LeadSendState = Literal["all", "emailed", "not_emailed"]


class EmailBulkSendIn(BaseModel):
    email_type: str = "bulk"
    template_id: int | None = None
    subject: str | None = None
    body: str | None = None
    mode: BulkEmailMode
    filter_value: str | None = None
    customer_ids: list[int] = Field(default_factory=list)
    lead_send_state: LeadSendState = "all"
    manual_emails: list[EmailStr] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    include_alternate_cc: bool = False


class EmailBulkResultOut(BaseModel):
    mode: str
    attempted: int
    queued: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class EmailLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int | None = None
    template_id: int | None = None
    recipient_email: str | None = None
    cc_emails: str | None = None
    bcc_emails: str | None = None
    email_type: str
    subject: str
    body: str
    status: str
    queue_status: str
    error_message: str | None = None
    retry_count: int
    created_at: datetime


class EmailLogPageOut(BaseModel):
    items: list[EmailLogOut]
    total: int
    page: int
    page_size: int


class EmailLogStatsOut(BaseModel):
    total: int
    sent: int
    dev_mode: int
    failed: int
    queued: int
    processing: int


class EmailSettingsOut(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_use_tls: bool
    smtp_mail_from: str
    smtp_password_set: bool
    app_base_url: str


class EmailSettingsUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    smtp_mail_from: str | None = None
    app_base_url: str | None = None


class EmailTestIn(BaseModel):
    to_email: EmailStr


class EmailTestTemplateIn(BaseModel):
    to_email: EmailStr
    template_id: int
    customer_id: int | None = None
    context: dict = Field(default_factory=dict)


class EmailTestResult(BaseModel):
    ok: bool
    status: str
    error: str | None = None


class EmailUnsubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    source: str | None = None
    unsubscribed_at: datetime


class EmailUnsubPageOut(BaseModel):
    items: list[EmailUnsubOut]
    total: int
    page: int
    page_size: int


class EmailCsvResultOut(BaseModel):
    execution_id: int
    total_rows: int
    valid_rows: int
    invalid_rows: int
    unsubscribed_rows: int
    queued: int
    errors: list[str] = Field(default_factory=list)


class EmailCsvExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int | None = None
    uploaded_filename: str
    total_rows: int
    unsubscribed_rows: int
    invalid_rows: int
    sent_rows: int
    failed_rows: int
    pending: int | None = None
    created_at: datetime


# ---------------------------------------------------------------- Documents / SOW
class SowSectionIn(BaseModel):
    title: str
    body: str


class SowGenerateIn(BaseModel):
    customer_id: int
    sow_title: str | None = None
    company: str | None = None
    sections: list[SowSectionIn] = Field(default_factory=list)


class SowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    sow_title: str | None = None
    version: str
    status: str
    content_html: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    original_filename: str
    storage_backend: str
    blob_url: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None
    description: str | None = None
    uploaded_by: str | None = None
    created_at: datetime


# ---------------------------------------------------------------- Diagrams
class DiagramGenerateIn(BaseModel):
    customer_id: int
    diagram_name: str
    macro_key: str = "default"
    title: str | None = None
    entities: list[str] = Field(default_factory=list)
    ai_generated: str | None = None
    aws_calculator_link: str | None = None


class DiagramSaveIn(BaseModel):
    customer_id: int
    diagram_name: str
    macro_key: str = "default"
    diagram_content: str
    aws_calculator_link: str | None = None


class DiagramUpdateIn(BaseModel):
    diagram_name: str | None = None
    diagram_content: str | None = None
    aws_calculator_link: str | None = None
    is_active: bool | None = None


class DiagramOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    diagram_name: str
    macro_key: str
    diagram_content: str
    aws_calculator_link: str | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- AI
class AiGenerateIn(BaseModel):
    provider: Literal["openai", "gemini"] = "openai"
    prompt: str
    api_key: str
    model: str | None = None
    max_tokens: int | None = Field(default=None, gt=0, le=8192)


class AiGenerateOut(BaseModel):
    content: str


# ---------------------------------------------------------------- CSV import
class CsvAnalyzeIn(BaseModel):
    content: str
    contains_header: bool = True


class CsvPreviewOut(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    row_count: int


class CsvImportIn(BaseModel):
    entity: Literal["customers", "leads"] = "customers"
    content: str
    contains_header: bool = True
    column_map: dict[str, str] = Field(default_factory=dict)


class ExcelImportIn(BaseModel):
    url: str
    sheet_name: str | None = None
    update_existing: bool = True
    column_map: dict[str, str] = Field(default_factory=dict)


class ImportResultOut(BaseModel):
    entity: str
    created: int
    created_ids: list[int]
    skipped: int
    updated: int = 0
    errors: list[str] = Field(default_factory=list)