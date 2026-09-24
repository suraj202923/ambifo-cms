from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class InviteCreate(BaseModel):
    customer_id: int
    recipient_email: EmailStr | None = None
    subject: str | None = None
    meeting_link: str
    agenda: str | None = None
    required_data: str | None = None
    scheduled_at: datetime | None = None


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    recipient_email: str
    subject: str
    meeting_link: str
    agenda: str | None = None
    required_data: str | None = None
    scheduled_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime


class AvailabilityCreate(BaseModel):
    customer_id: int
    recipient_email: EmailStr | None = None
    subject: str | None = None
    option_1_at: datetime
    option_2_at: datetime
    option_3_at: datetime
    expires_days: int = 7


class AvailabilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    customer_id: int
    customer_name: str | None = None
    recipient_email: str
    subject: str
    option_1_at: datetime
    option_2_at: datetime
    option_3_at: datetime
    customer_option_1_at: datetime | None = None
    customer_option_2_at: datetime | None = None
    customer_option_3_at: datetime | None = None
    extra_recipients: str | None = None
    customer_note: str | None = None
    customer_submitted_at: datetime | None = None
    selected_option: int | None = None
    selected_at: datetime | None = None
    expires_at: datetime | None = None
    status: str
    created_by: str | None = None
    created_at: datetime


class AvailabilitySelectIn(BaseModel):
    option: int  # 1|2|3


class AvailabilityFormIn(BaseModel):
    option_1_at: datetime
    option_2_at: datetime
    option_3_at: datetime
    extra_recipients: str | None = None
    customer_note: str | None = None