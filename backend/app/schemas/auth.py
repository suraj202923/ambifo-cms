from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str | None = None
    is_admin: bool
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str | None = None
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class AdminUserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str | None = None
    is_admin: bool = False


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    new_password: str | None = None