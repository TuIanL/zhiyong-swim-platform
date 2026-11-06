from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Input):
    email: str = Field(min_length=3, max_length=255)
    # 密码空格是密码本身，不使用自动 trim。
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or any(c.isspace() for c in value):
            raise ValueError("邮箱格式无效")
        local, domain = value.split("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("邮箱格式无效")
        return value

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("姓名不能为空")
        return value.strip()


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str


class SessionRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserRead


class TenantCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class TenantRead(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class MemberCreate(Input):
    user_id: UUID
    role: Literal["admin", "coach", "athlete"]


class MemberRole(Input):
    role: Literal["admin", "coach", "athlete"]


class MemberRead(BaseModel):
    user_id: str
    display_name: str
    role: str


class SiteCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=300)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("时区无效")
        return value


class SiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    tenant_id: str
    name: str
    address: str
    timezone: str


class SiteGrant(Input):
    user_id: UUID
