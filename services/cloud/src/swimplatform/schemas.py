import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


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


class EdgeNodeCreate(Input):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("节点名称不能为空")
        return value.strip()


class EdgeNodePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["pending", "active", "disabled"] | None = None

    @model_validator(mode="after")
    def require_nonempty_patch(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("PATCH必须至少包含一个非空可修改字段")
        return self

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("节点名称不能为空")
        return value.strip() if value is not None else value


class DeviceCreate(Input):
    edge_node_id: UUID
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["camera"] = "camera"
    hardware_serial: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("设备名称不能为空")
        return value.strip()


class DevicePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def require_nonempty_patch(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("PATCH必须至少包含一个非空可修改字段")
        return self

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("设备名称不能为空")
        return value.strip() if value is not None else value


class EdgeCredentialIssue(Input):
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def explicit_deadline_must_have_timezone(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("expires_at必须包含时区偏移")
            return value.astimezone(UTC)
        return value


class EdgeNodeRead(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    name: str
    status: str
    config_revision: int
    applied_config_revision: int | None
    last_seen_at: datetime | None
    online: bool
    software_version: str | None
    health_status: str | None
    observed_at_raw: str | None
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime


class DeviceRead(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    edge_node_id: str
    name: str
    kind: str
    status: str
    hardware_serial: str | None
    created_at: datetime
    updated_at: datetime


class EdgeCredentialRead(BaseModel):
    id: str
    edge_node_id: str
    generation: int
    issued_at: datetime
    expires_at: datetime
    issued_by_user_id: str
    revoked_at: datetime | None
    revoked_by_user_id: str | None


class EdgeCredentialIssued(EdgeCredentialRead):
    token: str


class HeartbeatHealth(Input):
    software_version: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["ok", "degraded", "unknown"] | None = None


class HeartbeatRequest(Input):
    reported_config_revision: int | None = Field(default=None, ge=0)
    # Device clock input is diagnostic raw text; unlike other strings, whitespace is data.
    observed_at_raw: Annotated[str | None, StringConstraints(strip_whitespace=False, max_length=128)] = None
    health: HeartbeatHealth | None = None

    @model_validator(mode="after")
    def bounded_health_payload(self):
        serialized = json.dumps(self.model_dump(mode="json", exclude_unset=True), separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 8192:
            raise ValueError("heartbeat健康摘要超过8KiB")
        return self


class HeartbeatRead(BaseModel):
    edge_node_id: str
    last_seen_at: datetime
    online: bool
    heartbeat_interval_seconds: int = 30
    online_window_seconds: int = 90
