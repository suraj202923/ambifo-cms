from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class CustomerBase(BaseModel):
    account_name: str | None = None
    customer_name: str
    designation: str | None = None
    email: EmailStr
    alternate_emails: str | None = None
    phone: str | None = None
    cloud: str | None = None
    main_page_address: str | None = None
    billing: str | None = None
    city: str | None = None
    aws_id: str | None = None
    aws_calculator_link: str | None = None
    opportunity_id: str | None = None
    segment: str | None = None
    deal_status: str | None = None
    comment: str | None = None
    next_action_planned: str | None = None
    assign_to_user_id: int | None = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    account_name: str | None = None
    customer_name: str | None = None
    designation: str | None = None
    email: EmailStr | None = None
    alternate_emails: str | None = None
    phone: str | None = None
    cloud: str | None = None
    main_page_address: str | None = None
    billing: str | None = None
    city: str | None = None
    aws_id: str | None = None
    aws_calculator_link: str | None = None
    opportunity_id: str | None = None
    segment: str | None = None
    deal_status: str | None = None
    comment: str | None = None
    next_action_planned: str | None = None
    assign_to_user_id: int | None = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class HistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    changed_by: str | None = None
    action: str
    tag_name: str | None = None
    changes_summary: str
    remark: str | None = None
    created_at: datetime


class HistoryCreate(BaseModel):
    action: str
    tag_name: str | None = None
    changes_summary: str
    remark: str | None = None


class BulkUpdate(BaseModel):
    customer_ids: list[int] = []
    filter_search: str | None = None
    filter_segment: str | None = None
    filter_deal_status: str | None = None
    deal_status: str | None = None
    segment: str | None = None
    assign_to_user_id: int | None = None


class FinancialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    expected_mrr: float | None = None
    expected_arr: float | None = None
    expected_credit_customer: float | None = None
    expected_credit_ambifo: float | None = None
    actual_mrr: float | None = None
    actual_arr: float | None = None
    actual_credit_customer: float | None = None
    actual_credit_ambifo: float | None = None
    credits_requested: float | None = None
    credits_gets: float | None = None
    phases_to_distribute: int | None = None


class FinancialUpdate(BaseModel):
    expected_mrr: float | None = None
    expected_arr: float | None = None
    expected_credit_customer: float | None = None
    expected_credit_ambifo: float | None = None
    actual_mrr: float | None = None
    actual_arr: float | None = None
    actual_credit_customer: float | None = None
    actual_credit_ambifo: float | None = None
    credits_requested: float | None = None
    credits_gets: float | None = None
    phases_to_distribute: int | None = None


class StatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    credit_percentage: float | None = None
    credit_on_arr: bool
    credit_percentage_customer: float | None = None
    credit_percentage_ambifo: float | None = None
    credit_basis_mrr: bool
    credit_basis_arr: bool
    is_active: bool


class CloudOperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UpdateTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class LeadBase(BaseModel):
    lead_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    city: str | None = None
    source: str | None = None
    tags: str | None = None
    notes: str | None = None
    lead_status: str = "new"


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    lead_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    company: str | None = None
    city: str | None = None
    source: str | None = None
    tags: str | None = None
    notes: str | None = None
    lead_status: str | None = None
    is_active: bool | None = None


class LeadOut(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    last_emailed_at: datetime | None = None
    last_email_status: str | None = None
    converted_at: datetime | None = None
    converted_customer_id: int | None = None
    created_at: datetime
    updated_at: datetime