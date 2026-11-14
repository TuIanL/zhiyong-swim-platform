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


# ---- 训练会话与媒体（M2）------------------------------------------------


class SessionCreate(Input):
    title: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("会话标题不能为空")
        return value.strip() if value is not None else value


class SessionPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["planned", "recording", "completed", "cancelled"] | None = None

    @model_validator(mode="after")
    def require_writable_field(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("PATCH 必须至少包含一个非空可写字段")
        return self

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("会话标题不能为空")
        return value.strip() if value is not None else value


class GrantPut(Input):
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def aware_deadline(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("expires_at 必须包含时区偏移")
            return value.astimezone(UTC)
        return value


class CaptureMetadata(Input):
    # 设备时间输入是诊断原始文本；与普通字符串不同，空白是数据本身。
    device_capture_started_at_raw: Annotated[str | None, StringConstraints(strip_whitespace=False, max_length=64)] = None
    device_capture_ended_at_raw: Annotated[str | None, StringConstraints(strip_whitespace=False, max_length=64)] = None
    capture_started_at_utc: datetime | None = None
    capture_ended_at_utc: datetime | None = None
    device_time_basis: Literal["utc", "offset", "iana_timezone", "unknown"]
    device_timezone: str | None = Field(default=None, max_length=64)
    device_utc_offset_minutes: int | None = Field(default=None, ge=-840, le=840)
    video_timebase_kind: Literal["relative", "wall_clock", "unknown"]
    video_timebase_metadata: dict | None = None
    device_clock_source: Literal["ntp", "ptp", "gps", "manual", "unknown"] = "unknown"
    device_clock_offset_ms: float | None = None
    device_clock_accuracy_ms: float | None = Field(default=None, ge=0)

    @field_validator("capture_started_at_utc", "capture_ended_at_utc")
    @classmethod
    def aware_utc(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("capture_*_at_utc 必须包含时区偏移")
            return value.astimezone(UTC)
        return value

    @field_validator("device_timezone")
    @classmethod
    def valid_timezone(cls, value):
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("设备时区无效")
        return value

    @model_validator(mode="after")
    def consistent_time_basis(self):
        """基准、时区/偏移与 UTC 派生值之间不得矛盾；unknown 不生成 UTC。"""
        basis = self.device_time_basis
        if basis == "unknown":
            if self.device_timezone is not None or self.device_utc_offset_minutes is not None:
                raise ValueError("时间基准 unknown 时不得提供时区或偏移")
            if self.capture_started_at_utc is not None or self.capture_ended_at_utc is not None:
                raise ValueError("时间基准 unknown 时不得提供 UTC 时间")
        elif basis == "utc":
            if self.device_timezone is not None:
                raise ValueError("时间基准 utc 时不得提供设备时区")
            if self.device_utc_offset_minutes not in (None, 0):
                raise ValueError("时间基准 utc 时偏移只能为空或 0")
        elif basis == "offset":
            if self.device_utc_offset_minutes is None:
                raise ValueError("时间基准 offset 时必须提供 UTC 偏移")
            if self.device_timezone is not None:
                raise ValueError("时间基准 offset 时不得提供设备时区")
        elif basis == "iana_timezone":
            if self.device_timezone is None:
                raise ValueError("时间基准 iana_timezone 时必须提供设备时区")
            if self.device_utc_offset_minutes is not None:
                raise ValueError("时间基准 iana_timezone 时不得提供 UTC 偏移")

        if (
            self.capture_started_at_utc is not None
            and self.capture_ended_at_utc is not None
            and self.capture_started_at_utc > self.capture_ended_at_utc
        ):
            raise ValueError("采集开始时间不得晚于结束时间")

        if self.video_timebase_metadata is not None:
            serialized = json.dumps(self.video_timebase_metadata, separators=(",", ":"), sort_keys=True)
            if len(serialized.encode("utf-8")) > 8192:
                raise ValueError("video_timebase_metadata 超过 8KiB")
        return self


class UploadIntentCreate(Input):
    expected_size_bytes: int = Field(gt=0, le=2**53)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str | None = Field(default=None, min_length=1, max_length=128)
    capture_metadata: CaptureMetadata


class EdgeUploadIntentCreate(UploadIntentCreate):
    device_id: UUID


class TrainingSessionRead(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    created_by_user_id: str
    title: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssetRead(BaseModel):
    id: str
    tenant_id: str
    site_id: str
    session_id: str
    origin: str
    created_by_user_id: str | None
    source_edge_node_id: str | None
    source_device_id: str | None
    derived_from_asset_id: str | None
    status: str
    failure_reason: str | None
    capture_started_at_utc: datetime | None
    capture_ended_at_utc: datetime | None
    device_capture_started_at_raw: str | None
    device_capture_ended_at_raw: str | None
    device_time_basis: str
    device_timezone: str | None
    device_utc_offset_minutes: int | None
    video_timebase_kind: str
    video_timebase_metadata: dict | None
    device_clock_source: str
    device_clock_offset_ms: float | None
    device_clock_accuracy_ms: float | None
    received_at: datetime | None
    media_type: str | None
    size_bytes: int | None
    checksum_sha256: str | None
    created_at: datetime
    updated_at: datetime


class UploadSessionRead(BaseModel):
    id: str
    asset_id: str
    status: str
    initiator_user_id: str | None
    initiator_edge_node_id: str | None
    expected_size_bytes: int
    expected_sha256: str
    media_type: str | None
    expires_at: datetime
    confirmed_parts: list = []
    completed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class UploadIntentRead(BaseModel):
    upload_session: UploadSessionRead
    asset: AssetRead


class Page(BaseModel):
    items: list
    next_cursor: str | None = None
