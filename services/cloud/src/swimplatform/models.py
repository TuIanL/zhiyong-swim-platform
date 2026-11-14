from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("tenant_id", "id"), UniqueConstraint("tenant_id", "name"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class SiteMembership(Base):
    __tablename__ = "site_memberships"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["tenant_memberships.tenant_id", "tenant_memberships.user_id"], ondelete="CASCADE"),
    )
    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class EdgeNode(Base):
    __tablename__ = "edge_nodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "id", name="uq_edge_nodes_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_edge_nodes_site_scope",
        ),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_edge_nodes_name"),
        CheckConstraint("status IN ('pending', 'active', 'disabled')", name="ck_edge_nodes_status"),
        CheckConstraint("config_revision >= 1", name="ck_edge_nodes_config_revision"),
        CheckConstraint(
            "applied_config_revision IS NULL OR applied_config_revision >= 0",
            name="ck_edge_nodes_applied_config_revision",
        ),
        CheckConstraint("credential_generation >= 0", name="ck_edge_nodes_credential_generation"),
        CheckConstraint(
            "health_status IS NULL OR health_status IN ('ok', 'degraded', 'unknown')",
            name="ck_edge_nodes_health_status",
        ),
        CheckConstraint(
            "software_version IS NULL OR length(software_version) BETWEEN 1 AND 64",
            name="ck_edge_nodes_software_version",
        ),
        CheckConstraint(
            "observed_at_raw IS NULL OR length(observed_at_raw) <= 128",
            name="ck_edge_nodes_observed_at_raw",
        ),
        Index("ix_edge_nodes_tenant_site_status", "tenant_id", "site_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    applied_config_revision: Mapped[int | None] = mapped_column(Integer)
    software_version: Mapped[str | None] = mapped_column(String(64))
    health_status: Mapped[str | None] = mapped_column(String(16))
    observed_at_raw: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_edge_nodes_created_by_user"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "edge_node_id", "id", name="uq_devices_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_devices_edge_node_scope",
        ),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_devices_name"),
        CheckConstraint("kind = 'camera'", name="ck_devices_kind"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_devices_status"),
        CheckConstraint(
            "hardware_serial IS NULL OR length(hardware_serial) BETWEEN 1 AND 120",
            name="ck_devices_hardware_serial",
        ),
        Index("ix_devices_tenant_site_node_status", "tenant_id", "site_id", "edge_node_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    edge_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="camera")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    hardware_serial: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class EdgeCredential(Base):
    __tablename__ = "edge_credentials"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_edge_credentials_token_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_edge_credentials_edge_node_scope",
        ),
        ForeignKeyConstraint(
            ["issued_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_edge_credentials_issued_by_user",
        ),
        ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT",
            name="fk_edge_credentials_revoked_by_user",
        ),
        CheckConstraint("generation >= 0", name="ck_edge_credentials_generation"),
        CheckConstraint("length(token_hash) = 64", name="ck_edge_credentials_token_hash"),
        CheckConstraint("expires_at > issued_at", name="ck_edge_credentials_deadline"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= issued_at", name="ck_edge_credentials_revocation_time"
        ),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_edge_credentials_revocation_actor",
        ),
        Index("ix_edge_credentials_node_generation", "tenant_id", "site_id", "edge_node_id", "generation"),
        Index("uq_edge_credentials_scope_id", "tenant_id", "site_id", "edge_node_id", "id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    edge_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[str | None] = mapped_column(String(36))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_idempotency_records_site_scope",
        ),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_idempotency_records_user"
        ),
        # Edge 上传意图没有用户主体，因此按主体区分的键域必须同时约束节点归属。
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_idempotency_records_edge_node_scope",
        ),
        CheckConstraint("actor_kind IN ('user', 'edge_node')", name="ck_idempotency_records_actor_kind"),
        CheckConstraint(
            "(actor_kind = 'user' AND user_id IS NOT NULL AND edge_node_id IS NULL) OR "
            "(actor_kind = 'edge_node' AND user_id IS NULL AND edge_node_id IS NOT NULL)",
            name="ck_idempotency_records_actor",
        ),
        CheckConstraint(
            "operation IN ('edge_node.create', 'device.create', 'edge_credential.issue', "
            "'training_session.create', 'upload_intent.create')",
            name="ck_idempotency_records_operation",
        ),
        CheckConstraint(
            "resource_kind IN ('edge_node', 'device', 'edge_credential', 'training_session', 'upload_session')",
            name="ck_idempotency_records_kind",
        ),
        CheckConstraint("length(key_hash) = 64", name="ck_idempotency_records_key_hash"),
        CheckConstraint("length(request_hash) = 64", name="ck_idempotency_records_request_hash"),
        Index(
            "uq_idempotency_user_scope_key",
            "tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash",
            unique=True, sqlite_where=text("actor_kind = 'user'"),
            postgresql_where=text("actor_kind = 'user'"),
        ),
        Index(
            "uq_idempotency_edge_scope_key",
            "tenant_id", "site_id", "edge_node_id", "operation", "target_id", "key_hash",
            unique=True, sqlite_where=text("actor_kind = 'edge_node'"),
            postgresql_where=text("actor_kind = 'edge_node'"),
        ),
        Index("ix_idempotency_records_resource", "resource_kind", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="user", server_default="user")
    user_id: Mapped[str | None] = mapped_column(String(36))
    edge_node_id: Mapped[str | None] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


SESSION_STATUSES = ("planned", "recording", "completed", "cancelled")
ASSET_STATUSES = ("pending_upload", "ready", "failed")
UPLOAD_STATUSES = ("uploading", "completing", "completed", "failed", "aborted", "expired")
FAILURE_REASONS = (
    "upload_aborted", "upload_expired", "session_cancelled", "upload_failed", "validation_failed",
)


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "id", name="uq_training_sessions_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_training_sessions_site_scope",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_training_sessions_created_by",
        ),
        CheckConstraint("title IS NULL OR length(trim(title)) BETWEEN 1 AND 120", name="ck_training_sessions_title"),
        CheckConstraint(
            "status IN ('planned', 'recording', 'completed', 'cancelled')", name="ck_training_sessions_status"
        ),
        CheckConstraint(
            "(status = 'planned' AND started_at IS NULL AND completed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'recording' AND started_at IS NOT NULL AND completed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL)",
            name="ck_training_sessions_status_times",
        ),
        CheckConstraint("started_at IS NULL OR started_at >= created_at", name="ck_training_sessions_started_order"),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="ck_training_sessions_completed_order",
        ),
        CheckConstraint("cancelled_at IS NULL OR cancelled_at >= created_at", name="ck_training_sessions_cancelled_order"),
        Index("ix_training_sessions_scope_cursor", "tenant_id", "site_id", "created_at", "id"),
        Index("ix_training_sessions_creator", "tenant_id", "site_id", "created_by_user_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class VideoAsset(Base):
    __tablename__ = "video_assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "session_id", "id", name="uq_video_assets_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id"],
            ["training_sessions.tenant_id", "training_sessions.site_id", "training_sessions.id"],
            ondelete="RESTRICT", name="fk_video_assets_session_scope",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_video_assets_created_by",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "source_edge_node_id", "source_device_id"],
            ["devices.tenant_id", "devices.site_id", "devices.edge_node_id", "devices.id"],
            ondelete="RESTRICT", name="fk_video_assets_device_source",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "derived_from_asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_video_assets_derived_parent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "id", "storage_object_ref"],
            ["media_objects.tenant_id", "media_objects.site_id", "media_objects.session_id",
             "media_objects.asset_id", "media_objects.id"],
            ondelete="RESTRICT", name="fk_video_assets_storage_object_scope", use_alter=True,
        ),
        CheckConstraint("origin IN ('edge', 'manual', 'derived')", name="ck_video_assets_origin"),
        CheckConstraint("status IN ('pending_upload', 'ready', 'failed')", name="ck_video_assets_status"),
        CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('upload_aborted', 'upload_expired', 'session_cancelled', 'upload_failed', 'validation_failed')",
            name="ck_video_assets_failure_reason",
        ),
        CheckConstraint(
            "(status = 'failed' AND failure_reason IS NOT NULL) OR (status <> 'failed' AND failure_reason IS NULL)",
            name="ck_video_assets_failure_state",
        ),
        CheckConstraint(
            "(origin = 'edge' AND source_edge_node_id IS NOT NULL AND source_device_id IS NOT NULL) OR "
            "(origin <> 'edge' AND source_edge_node_id IS NULL AND source_device_id IS NULL)",
            name="ck_video_assets_source_pair",
        ),
        CheckConstraint(
            "(origin = 'manual' AND created_by_user_id IS NOT NULL) OR "
            "(origin <> 'manual' AND created_by_user_id IS NULL)",
            name="ck_video_assets_creator_by_origin",
        ),
        CheckConstraint(
            "(origin = 'derived') = (derived_from_asset_id IS NOT NULL)", name="ck_video_assets_derived_pair"
        ),
        CheckConstraint(
            "derived_from_asset_id IS NULL OR derived_from_asset_id <> id", name="ck_video_assets_derived_not_self"
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes > 0", name="ck_video_assets_size_positive"
        ),
        CheckConstraint(
            "checksum_sha256 IS NULL OR (length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256))",
            name="ck_video_assets_checksum_format",
        ),
        # 「无整对象校验不得 ready」写成库层约束，而不是仅靠代码约定。
        CheckConstraint(
            "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL "
            "AND size_bytes IS NOT NULL AND media_type IS NOT NULL AND storage_object_ref IS NOT NULL "
            "AND verified_size_bytes IS NOT NULL AND verified_media_type IS NOT NULL AND verified_at IS NOT NULL "
            "AND size_bytes = verified_size_bytes AND media_type = verified_media_type)",
            name="ck_video_assets_ready_requires_verification",
        ),
        CheckConstraint(
            "status = 'ready' OR (storage_object_ref IS NULL AND verified_size_bytes IS NULL "
            "AND verified_media_type IS NULL AND verified_at IS NULL)",
            name="ck_video_assets_unverified_has_no_reference",
        ),
        CheckConstraint("device_time_basis IN ('utc', 'offset', 'iana_timezone', 'unknown')", name="ck_video_assets_time_basis"),
        CheckConstraint("video_timebase_kind IN ('relative', 'wall_clock', 'unknown')", name="ck_video_assets_timebase_kind"),
        CheckConstraint(
            "device_clock_source IN ('ntp', 'ptp', 'gps', 'manual', 'unknown')", name="ck_video_assets_clock_source"
        ),
        CheckConstraint(
            "device_time_basis <> 'unknown' OR (device_timezone IS NULL AND device_utc_offset_minutes IS NULL "
            "AND capture_started_at_utc IS NULL AND capture_ended_at_utc IS NULL)",
            name="ck_video_assets_unknown_basis",
        ),
        CheckConstraint(
            "device_time_basis <> 'utc' OR (device_timezone IS NULL "
            "AND (device_utc_offset_minutes IS NULL OR device_utc_offset_minutes = 0))",
            name="ck_video_assets_utc_basis",
        ),
        CheckConstraint(
            "device_time_basis <> 'offset' OR (device_utc_offset_minutes IS NOT NULL AND device_timezone IS NULL)",
            name="ck_video_assets_offset_basis",
        ),
        CheckConstraint(
            "device_time_basis <> 'iana_timezone' OR (device_timezone IS NOT NULL AND device_utc_offset_minutes IS NULL)",
            name="ck_video_assets_timezone_basis",
        ),
        CheckConstraint(
            "device_utc_offset_minutes IS NULL OR device_utc_offset_minutes BETWEEN -840 AND 840",
            name="ck_video_assets_utc_offset_range",
        ),
        CheckConstraint(
            "capture_started_at_utc IS NULL OR capture_ended_at_utc IS NULL "
            "OR capture_started_at_utc <= capture_ended_at_utc",
            name="ck_video_assets_capture_order",
        ),
        CheckConstraint(
            "device_clock_accuracy_ms IS NULL OR device_clock_accuracy_ms >= 0",
            name="ck_video_assets_clock_accuracy",
        ),
        CheckConstraint(
            "device_capture_started_at_raw IS NULL OR length(device_capture_started_at_raw) <= 64",
            name="ck_video_assets_started_raw_length",
        ),
        CheckConstraint(
            "device_capture_ended_at_raw IS NULL OR length(device_capture_ended_at_raw) <= 64",
            name="ck_video_assets_ended_raw_length",
        ),
        Index("ix_video_assets_session_cursor", "tenant_id", "site_id", "session_id", "created_at", "id"),
        Index("ix_video_assets_creator", "tenant_id", "site_id", "created_by_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36))
    source_edge_node_id: Mapped[str | None] = mapped_column(String(36))
    source_device_id: Mapped[str | None] = mapped_column(String(36))
    derived_from_asset_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_upload")
    failure_reason: Mapped[str | None] = mapped_column(String(32))
    capture_started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_ended_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_capture_started_at_raw: Mapped[str | None] = mapped_column(String(64))
    device_capture_ended_at_raw: Mapped[str | None] = mapped_column(String(64))
    device_time_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    device_timezone: Mapped[str | None] = mapped_column(String(64))
    device_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer)
    video_timebase_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    video_timebase_metadata: Mapped[dict | None] = mapped_column(JSON)
    device_clock_source: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    device_clock_offset_ms: Mapped[float | None] = mapped_column(Numeric(12, 3))
    device_clock_accuracy_ms: Mapped[float | None] = mapped_column(Numeric(12, 3))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    media_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_object_ref: Mapped[str | None] = mapped_column(String(36))
    verified_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    verified_media_type: Mapped[str | None] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class UploadSession(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_upload_sessions_asset"),
        UniqueConstraint(
            "tenant_id", "site_id", "session_id", "asset_id", "id", name="uq_upload_sessions_scope_asset_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_asset_scope",
        ),
        ForeignKeyConstraint(
            ["initiator_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_initiator_user",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "initiator_edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_initiator_node",
        ),
        CheckConstraint(
            "status IN ('uploading', 'completing', 'completed', 'failed', 'aborted', 'expired')",
            name="ck_upload_sessions_status",
        ),
        CheckConstraint(
            "(initiator_user_id IS NOT NULL AND initiator_edge_node_id IS NULL) OR "
            "(initiator_user_id IS NULL AND initiator_edge_node_id IS NOT NULL)",
            name="ck_upload_sessions_single_initiator",
        ),
        CheckConstraint("expected_size_bytes > 0", name="ck_upload_sessions_expected_size"),
        CheckConstraint(
            "(part_size_bytes IS NULL AND part_count IS NULL) OR "
            "(part_size_bytes IS NOT NULL AND part_size_bytes > 0 AND part_count IS NOT NULL "
            "AND part_count BETWEEN 1 AND 10000)", name="ck_upload_sessions_layout_pair",
        ),
        CheckConstraint(
            "(complete_manifest_hash IS NULL AND complete_requested_at IS NULL) OR "
            "(complete_manifest_hash IS NOT NULL AND length(complete_manifest_hash) = 64 "
            "AND complete_requested_at IS NOT NULL)", name="ck_upload_sessions_manifest_pair",
        ),
        CheckConstraint(
            "status NOT IN ('completing', 'completed') OR complete_manifest_hash IS NOT NULL",
            name="ck_upload_sessions_complete_requires_manifest",
        ),
        CheckConstraint(
            "length(expected_sha256) = 64 AND expected_sha256 = lower(expected_sha256)",
            name="ck_upload_sessions_expected_sha",
        ),
        CheckConstraint("expires_at > created_at", name="ck_upload_sessions_deadline"),
        CheckConstraint(
            "failure_reason IS NULL OR failure_reason IN "
            "('upload_aborted', 'upload_expired', 'session_cancelled', 'upload_failed', 'validation_failed')",
            name="ck_upload_sessions_failure_reason",
        ),
        CheckConstraint(
            "(status IN ('failed', 'aborted', 'expired') AND failure_reason IS NOT NULL) OR "
            "(status NOT IN ('failed', 'aborted', 'expired') AND failure_reason IS NULL)",
            name="ck_upload_sessions_failure_state",
        ),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)", name="ck_upload_sessions_completed_pair"
        ),
        Index("ix_upload_sessions_scope_status", "tenant_id", "site_id", "session_id", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploading")
    initiator_user_id: Mapped[str | None] = mapped_column(String(36))
    initiator_edge_node_id: Mapped[str | None] = mapped_column(String(36))
    failure_reason: Mapped[str | None] = mapped_column(String(32))
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)

    part_size_bytes: Mapped[int | None] = mapped_column(Integer)
    part_count: Mapped[int | None] = mapped_column(Integer)
    complete_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    complete_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaObject(Base):
    __tablename__ = "media_objects"
    __table_args__ = (
        UniqueConstraint("upload_session_id", name="uq_media_objects_upload_session"),
        UniqueConstraint(
            "tenant_id", "site_id", "session_id", "asset_id", "id", name="uq_media_objects_scope_asset_id"
        ),
        UniqueConstraint("tenant_id", "site_id", "id", name="uq_media_objects_scope_id"),
        UniqueConstraint("provider_profile", "bucket", "object_key", name="uq_media_objects_location"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_media_objects_asset_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "upload_session_id"],
            ["upload_sessions.tenant_id", "upload_sessions.site_id", "upload_sessions.session_id",
             "upload_sessions.asset_id", "upload_sessions.id"],
            ondelete="RESTRICT", name="fk_media_objects_upload_scope",
        ),
        CheckConstraint(
            "phase IN ('reserved', 'preparing', 'uploading', 'assembled', 'verified', 'delete_pending', 'deleted')",
            name="ck_media_objects_phase",
        ),
        CheckConstraint("generation >= 1", name="ck_media_objects_generation"),
        CheckConstraint("observed_size_bytes IS NULL OR observed_size_bytes > 0", name="ck_media_objects_observed_size"),
        CheckConstraint(
            "observed_sha256 IS NULL OR (length(observed_sha256) = 64 AND observed_sha256 = lower(observed_sha256))",
            name="ck_media_objects_observed_sha256",
        ),
        CheckConstraint(
            "phase <> 'verified' OR (observed_size_bytes IS NOT NULL AND observed_sha256 IS NOT NULL "
            "AND observed_media_type IS NOT NULL AND verified_at IS NOT NULL AND object_version IS NOT NULL)",
            name="ck_media_objects_verified_fields",
        ),
        CheckConstraint("phase NOT IN ('assembled', 'verified') OR object_version IS NOT NULL",
                        name="ck_media_objects_exact_version_required"),
        CheckConstraint("phase <> 'deleted' OR deleted_at IS NOT NULL", name="ck_media_objects_deleted_time"),
        Index("ix_media_objects_phase_updated", "phase", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    upload_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_upload_id: Mapped[str | None] = mapped_column(String(512))
    object_version: Mapped[str | None] = mapped_column(String(512))
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="reserved")
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    observed_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    observed_sha256: Mapped[str | None] = mapped_column(String(64))
    observed_media_type: Mapped[str | None] = mapped_column(String(128))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_signed_write_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assembled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class UploadPart(Base):
    __tablename__ = "upload_parts"
    __table_args__ = (
        UniqueConstraint("upload_session_id", "part_number", name="uq_upload_parts_number"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "upload_session_id"],
            ["upload_sessions.tenant_id", "upload_sessions.site_id", "upload_sessions.session_id",
             "upload_sessions.asset_id", "upload_sessions.id"],
            ondelete="RESTRICT", name="fk_upload_parts_upload_scope",
        ),
        CheckConstraint("part_number BETWEEN 1 AND 10000", name="ck_upload_parts_number"),
        CheckConstraint("expected_size_bytes > 0", name="ck_upload_parts_expected_size"),
        CheckConstraint("actual_size_bytes IS NULL OR actual_size_bytes > 0", name="ck_upload_parts_actual_size"),
        CheckConstraint("state IN ('registered', 'confirmed', 'stale')", name="ck_upload_parts_state"),
        CheckConstraint(
            "(state = 'registered' AND etag IS NULL AND actual_size_bytes IS NULL AND confirmed_at IS NULL) OR "
            "(state IN ('confirmed', 'stale') AND etag IS NOT NULL AND actual_size_bytes IS NOT NULL "
            "AND confirmed_at IS NOT NULL)", name="ck_upload_parts_confirmation_fields",
        ),
        CheckConstraint("etag IS NULL OR length(etag) BETWEEN 1 AND 512", name="ck_upload_parts_etag_length"),
        Index("ix_upload_parts_scope_state", "tenant_id", "site_id", "upload_session_id", "state", "part_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    upload_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    etag: Mapped[str | None] = mapped_column(String(512))
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class MediaJob(Base):
    __tablename__ = "media_jobs"
    __table_args__ = (
        UniqueConstraint("object_id", "kind", name="uq_media_jobs_object_kind"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "object_id"],
            ["media_objects.tenant_id", "media_objects.site_id", "media_objects.session_id",
             "media_objects.asset_id", "media_objects.id"],
            ondelete="RESTRICT", name="fk_media_jobs_object_scope",
        ),
        ForeignKeyConstraint(["accepted_user_id"], ["users.id"], ondelete="RESTRICT",
                             name="fk_media_jobs_accepted_user"),
        # Deliberately not an FK: logout must be able to delete this auth session and
        # thereby invalidate a pending completion before its final ready commit.
        ForeignKeyConstraint(["tenant_id", "site_id", "accepted_edge_node_id"],
                             ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
                             ondelete="RESTRICT", name="fk_media_jobs_edge_node_scope"),
        ForeignKeyConstraint(["tenant_id", "site_id", "accepted_edge_node_id", "accepted_credential_id"],
                             ["edge_credentials.tenant_id", "edge_credentials.site_id",
                              "edge_credentials.edge_node_id", "edge_credentials.id"],
                             ondelete="RESTRICT", name="fk_media_jobs_credential_scope"),
        CheckConstraint("kind IN ('initialize', 'complete', 'cleanup')", name="ck_media_jobs_kind"),
        CheckConstraint("state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed')", name="ck_media_jobs_state"),
        CheckConstraint("attempts >= 0 AND generation >= 1", name="ck_media_jobs_attempts_generation"),
        CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_media_jobs_lease_pair",
        ),
        CheckConstraint(
            "(kind = 'complete' AND ((accepted_actor_kind = 'user' AND accepted_user_id IS NOT NULL "
            "AND accepted_auth_session_hash IS NOT NULL AND accepted_edge_node_id IS NULL "
            "AND accepted_credential_id IS NULL) OR (accepted_actor_kind = 'edge_node' "
            "AND accepted_user_id IS NULL AND accepted_auth_session_hash IS NULL "
            "AND accepted_edge_node_id IS NOT NULL AND accepted_credential_id IS NOT NULL))) OR "
            "(kind <> 'complete' AND accepted_actor_kind IS NULL AND accepted_user_id IS NULL "
            "AND accepted_auth_session_hash IS NULL AND accepted_edge_node_id IS NULL "
            "AND accepted_credential_id IS NULL)", name="ck_media_jobs_accepted_actor",
        ),
        Index("ix_media_jobs_state_next_lease", "state", "next_attempt_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    accepted_actor_kind: Mapped[str | None] = mapped_column(String(16))
    accepted_user_id: Mapped[str | None] = mapped_column(String(36))
    accepted_auth_session_hash: Mapped[str | None] = mapped_column(String(64))
    accepted_edge_node_id: Mapped[str | None] = mapped_column(String(36))
    accepted_credential_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class MediaCleanupCandidate(Base):
    __tablename__ = "media_cleanup_candidates"
    __table_args__ = (
        UniqueConstraint("identity_hash", name="uq_media_cleanup_identity_hash"),
        ForeignKeyConstraint(["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
                             ondelete="RESTRICT", name="fk_media_cleanup_site_scope"),
        ForeignKeyConstraint(["tenant_id", "site_id", "object_id"],
                             ["media_objects.tenant_id", "media_objects.site_id", "media_objects.id"],
                             ondelete="RESTRICT", name="fk_media_cleanup_object_scope"),
        CheckConstraint("kind IN ('multipart', 'object')", name="ck_media_cleanup_kind"),
        CheckConstraint("state IN ('observed', 'queued', 'running', 'retry_wait', 'deleted', 'failed', 'manual')",
                        name="ck_media_cleanup_state"),
        CheckConstraint("attempts >= 0 AND generation >= 1", name="ck_media_cleanup_attempts_generation"),
        CheckConstraint("last_seen_at >= first_seen_at AND not_before >= first_seen_at",
                        name="ck_media_cleanup_observation_order"),
        CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)",
            name="ck_media_cleanup_lease_pair",
        ),
        CheckConstraint("(object_id IS NULL) = (session_id IS NULL AND asset_id IS NULL)",
                        name="ck_media_cleanup_object_scope_pair"),
        Index("ix_media_cleanup_state_deadline", "state", "not_before", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(36))
    session_id: Mapped[str | None] = mapped_column(String(36))
    asset_id: Mapped[str | None] = mapped_column(String(36))
    provider_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    upload_id: Mapped[str | None] = mapped_column(String(512))
    object_version: Mapped[str | None] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)


class SessionReadGrant(Base):
    __tablename__ = "session_read_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id"],
            ["training_sessions.tenant_id", "training_sessions.site_id", "training_sessions.id"],
            ondelete="RESTRICT", name="fk_session_read_grants_session_scope",
        ),
        ForeignKeyConstraint(
            ["grantee_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_grantee"
        ),
        ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_grantor"
        ),
        ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_revoker"
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="ck_session_read_grants_deadline"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="ck_session_read_grants_revoked_order"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_session_read_grants_revocation_actor",
        ),
        Index(
            "uq_session_read_grants_active",
            "tenant_id", "site_id", "session_id", "grantee_user_id",
            unique=True, sqlite_where=text("revoked_at IS NULL"), postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_session_read_grants_lookup", "tenant_id", "site_id", "session_id", "grantee_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    grantee_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[str | None] = mapped_column(String(36))


class AssetReadGrant(Base):
    __tablename__ = "asset_read_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_asset_read_grants_asset_scope",
        ),
        ForeignKeyConstraint(
            ["grantee_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_grantee"
        ),
        ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_grantor"
        ),
        ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_revoker"
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="ck_asset_read_grants_deadline"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="ck_asset_read_grants_revoked_order"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_asset_read_grants_revocation_actor",
        ),
        Index(
            "uq_asset_read_grants_active",
            "tenant_id", "site_id", "asset_id", "grantee_user_id",
            unique=True, sqlite_where=text("revoked_at IS NULL"), postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_asset_read_grants_lookup", "tenant_id", "site_id", "asset_id", "grantee_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    grantee_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[str | None] = mapped_column(String(36))
