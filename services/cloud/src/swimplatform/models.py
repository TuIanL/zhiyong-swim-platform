from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
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
        UniqueConstraint(
            "tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash",
            name="uq_idempotency_scope_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_idempotency_records_site_scope",
        ),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_idempotency_records_user"
        ),
        CheckConstraint(
            "operation IN ('edge_node.create', 'device.create', 'edge_credential.issue')",
            name="ck_idempotency_records_operation",
        ),
        CheckConstraint("resource_kind IN ('edge_node', 'device', 'edge_credential')", name="ck_idempotency_records_kind"),
        CheckConstraint("length(key_hash) = 64", name="ck_idempotency_records_key_hash"),
        CheckConstraint("length(request_hash) = 64", name="ck_idempotency_records_request_hash"),
        Index("ix_idempotency_records_resource", "resource_kind", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    site_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now)
