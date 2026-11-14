"""Cloud session/asset foundation: five tables and actor-aware idempotency.

降级守卫：新增业务表仍有记录，或幂等表出现 Edge 主体/新 operation/resource_kind 时，
downgrade 必须显式失败并报告受影响范围，不得静默丢弃。
"""
from alembic import op
import sqlalchemy as sa


revision = "20261112_0003"
down_revision = "20261110_0002"
branch_labels = None
depends_on = None

MEDIA_TABLES = (
    "training_sessions",
    "video_assets",
    "upload_sessions",
    "session_read_grants",
    "asset_read_grants",
)
NEW_OPERATIONS = ("training_session.create", "upload_intent.create")
NEW_RESOURCE_KINDS = ("training_session", "upload_session")
ALL_OPERATIONS = ("edge_node.create", "device.create", "edge_credential.issue") + NEW_OPERATIONS
ALL_RESOURCE_KINDS = ("edge_node", "device", "edge_credential") + NEW_RESOURCE_KINDS
FAILURE_REASONS = (
    "upload_aborted", "upload_expired", "session_cancelled", "upload_failed", "validation_failed",
)


def _in_list(values) -> str:
    return ", ".join(f"'{value}'" for value in values)


def idempotency_columns(actor_aware: bool = True) -> list:
    columns = [
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
    ]
    if actor_aware:
        columns.append(sa.Column("actor_kind", sa.String(16), nullable=False, server_default="user"))
    columns.append(sa.Column("user_id", sa.String(36), nullable=actor_aware))
    if actor_aware:
        columns.append(sa.Column("edge_node_id", sa.String(36)))
    columns.extend(
        [
            sa.Column("operation", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("resource_kind", sa.String(32), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ]
    )
    return columns


def idempotency_constraints(actor_aware: bool = True) -> list:
    constraints = [
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_idempotency_records_site_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_idempotency_records_user"
        ),
        sa.CheckConstraint(
            f"operation IN ({_in_list(ALL_OPERATIONS) if actor_aware else _in_list(ALL_OPERATIONS[:3])})",
            name="ck_idempotency_records_operation",
        ),
        sa.CheckConstraint(
            f"resource_kind IN ({_in_list(ALL_RESOURCE_KINDS) if actor_aware else _in_list(ALL_RESOURCE_KINDS[:3])})",
            name="ck_idempotency_records_kind",
        ),
        sa.CheckConstraint("length(key_hash) = 64", name="ck_idempotency_records_key_hash"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_idempotency_records_request_hash"),
    ]
    if actor_aware:
        constraints.extend(
            [
                sa.ForeignKeyConstraint(
                    ["tenant_id", "site_id", "edge_node_id"],
                    ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
                    ondelete="RESTRICT", name="fk_idempotency_records_edge_node_scope",
                ),
                sa.CheckConstraint(
                    "actor_kind IN ('user', 'edge_node')", name="ck_idempotency_records_actor_kind"
                ),
                sa.CheckConstraint(
                    "(actor_kind = 'user' AND user_id IS NOT NULL AND edge_node_id IS NULL) OR "
                    "(actor_kind = 'edge_node' AND user_id IS NULL AND edge_node_id IS NOT NULL)",
                    name="ck_idempotency_records_actor",
                ),
            ]
        )
    else:
        constraints.append(
            sa.UniqueConstraint(
                "tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash",
                name="uq_idempotency_scope_key",
            )
        )
    return constraints


def create_media_tables():
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(120)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "site_id", "id", name="uq_training_sessions_scope_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_training_sessions_site_scope",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_training_sessions_created_by",
        ),
        sa.CheckConstraint("title IS NULL OR length(trim(title)) BETWEEN 1 AND 120", name="ck_training_sessions_title"),
        sa.CheckConstraint(
            "status IN ('planned', 'recording', 'completed', 'cancelled')", name="ck_training_sessions_status"
        ),
        sa.CheckConstraint(
            "(status = 'planned' AND started_at IS NULL AND completed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'recording' AND started_at IS NOT NULL AND completed_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL)",
            name="ck_training_sessions_status_times",
        ),
        sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="ck_training_sessions_started_order"),
        sa.CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="ck_training_sessions_completed_order",
        ),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at", name="ck_training_sessions_cancelled_order"
        ),
    )
    op.create_index("ix_training_sessions_scope_cursor", "training_sessions", ["tenant_id", "site_id", "created_at", "id"])
    op.create_index(
        "ix_training_sessions_creator", "training_sessions",
        ["tenant_id", "site_id", "created_by_user_id", "created_at", "id"],
    )

    op.create_table(
        "video_assets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column("source_edge_node_id", sa.String(36)),
        sa.Column("source_device_id", sa.String(36)),
        sa.Column("derived_from_asset_id", sa.String(36)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.String(32)),
        sa.Column("capture_started_at_utc", sa.DateTime(timezone=True)),
        sa.Column("capture_ended_at_utc", sa.DateTime(timezone=True)),
        sa.Column("device_capture_started_at_raw", sa.String(64)),
        sa.Column("device_capture_ended_at_raw", sa.String(64)),
        sa.Column("device_time_basis", sa.String(16), nullable=False),
        sa.Column("device_timezone", sa.String(64)),
        sa.Column("device_utc_offset_minutes", sa.Integer()),
        sa.Column("video_timebase_kind", sa.String(16), nullable=False),
        sa.Column("video_timebase_metadata", sa.JSON()),
        sa.Column("device_clock_source", sa.String(16), nullable=False),
        sa.Column("device_clock_offset_ms", sa.Numeric(12, 3)),
        sa.Column("device_clock_accuracy_ms", sa.Numeric(12, 3)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("media_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "site_id", "session_id", "id", name="uq_video_assets_scope_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id"],
            ["training_sessions.tenant_id", "training_sessions.site_id", "training_sessions.id"],
            ondelete="RESTRICT", name="fk_video_assets_session_scope",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_video_assets_created_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "source_edge_node_id", "source_device_id"],
            ["devices.tenant_id", "devices.site_id", "devices.edge_node_id", "devices.id"],
            ondelete="RESTRICT", name="fk_video_assets_device_source",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "derived_from_asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_video_assets_derived_parent",
        ),
        sa.CheckConstraint("origin IN ('edge', 'manual', 'derived')", name="ck_video_assets_origin"),
        sa.CheckConstraint("status IN ('pending_upload', 'ready', 'failed')", name="ck_video_assets_status"),
        sa.CheckConstraint(
            f"failure_reason IS NULL OR failure_reason IN ({_in_list(FAILURE_REASONS)})",
            name="ck_video_assets_failure_reason",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND failure_reason IS NOT NULL) OR (status <> 'failed' AND failure_reason IS NULL)",
            name="ck_video_assets_failure_state",
        ),
        sa.CheckConstraint(
            "(origin = 'edge' AND source_edge_node_id IS NOT NULL AND source_device_id IS NOT NULL) OR "
            "(origin <> 'edge' AND source_edge_node_id IS NULL AND source_device_id IS NULL)",
            name="ck_video_assets_source_pair",
        ),
        sa.CheckConstraint(
            "(origin = 'manual' AND created_by_user_id IS NOT NULL) OR "
            "(origin <> 'manual' AND created_by_user_id IS NULL)",
            name="ck_video_assets_creator_by_origin",
        ),
        sa.CheckConstraint(
            "(origin = 'derived') = (derived_from_asset_id IS NOT NULL)", name="ck_video_assets_derived_pair"
        ),
        sa.CheckConstraint(
            "derived_from_asset_id IS NULL OR derived_from_asset_id <> id", name="ck_video_assets_derived_not_self"
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes > 0", name="ck_video_assets_size_positive"),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR (length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256))",
            name="ck_video_assets_checksum_format",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL "
            "AND size_bytes IS NOT NULL AND media_type IS NOT NULL)",
            name="ck_video_assets_ready_requires_verification",
        ),
        sa.CheckConstraint(
            "device_time_basis IN ('utc', 'offset', 'iana_timezone', 'unknown')", name="ck_video_assets_time_basis"
        ),
        sa.CheckConstraint(
            "video_timebase_kind IN ('relative', 'wall_clock', 'unknown')", name="ck_video_assets_timebase_kind"
        ),
        sa.CheckConstraint(
            "device_clock_source IN ('ntp', 'ptp', 'gps', 'manual', 'unknown')", name="ck_video_assets_clock_source"
        ),
        sa.CheckConstraint(
            "device_time_basis <> 'unknown' OR (device_timezone IS NULL AND device_utc_offset_minutes IS NULL "
            "AND capture_started_at_utc IS NULL AND capture_ended_at_utc IS NULL)",
            name="ck_video_assets_unknown_basis",
        ),
        sa.CheckConstraint(
            "device_time_basis <> 'utc' OR (device_timezone IS NULL "
            "AND (device_utc_offset_minutes IS NULL OR device_utc_offset_minutes = 0))",
            name="ck_video_assets_utc_basis",
        ),
        sa.CheckConstraint(
            "device_time_basis <> 'offset' OR (device_utc_offset_minutes IS NOT NULL AND device_timezone IS NULL)",
            name="ck_video_assets_offset_basis",
        ),
        sa.CheckConstraint(
            "device_time_basis <> 'iana_timezone' OR (device_timezone IS NOT NULL AND device_utc_offset_minutes IS NULL)",
            name="ck_video_assets_timezone_basis",
        ),
        sa.CheckConstraint(
            "device_utc_offset_minutes IS NULL OR device_utc_offset_minutes BETWEEN -840 AND 840",
            name="ck_video_assets_utc_offset_range",
        ),
        sa.CheckConstraint(
            "capture_started_at_utc IS NULL OR capture_ended_at_utc IS NULL "
            "OR capture_started_at_utc <= capture_ended_at_utc",
            name="ck_video_assets_capture_order",
        ),
        sa.CheckConstraint(
            "device_clock_accuracy_ms IS NULL OR device_clock_accuracy_ms >= 0",
            name="ck_video_assets_clock_accuracy",
        ),
        sa.CheckConstraint(
            "device_capture_started_at_raw IS NULL OR length(device_capture_started_at_raw) <= 64",
            name="ck_video_assets_started_raw_length",
        ),
        sa.CheckConstraint(
            "device_capture_ended_at_raw IS NULL OR length(device_capture_ended_at_raw) <= 64",
            name="ck_video_assets_ended_raw_length",
        ),
    )
    op.create_index(
        "ix_video_assets_session_cursor", "video_assets", ["tenant_id", "site_id", "session_id", "created_at", "id"]
    )
    op.create_index("ix_video_assets_creator", "video_assets", ["tenant_id", "site_id", "created_by_user_id"])

    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("initiator_user_id", sa.String(36)),
        sa.Column("initiator_edge_node_id", sa.String(36)),
        sa.Column("failure_reason", sa.String(32)),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expected_sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_upload_sessions_asset"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_asset_scope",
        ),
        sa.ForeignKeyConstraint(
            ["initiator_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_initiator_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "initiator_edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_initiator_node",
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'completing', 'completed', 'failed', 'aborted', 'expired')",
            name="ck_upload_sessions_status",
        ),
        sa.CheckConstraint(
            "(initiator_user_id IS NOT NULL AND initiator_edge_node_id IS NULL) OR "
            "(initiator_user_id IS NULL AND initiator_edge_node_id IS NOT NULL)",
            name="ck_upload_sessions_single_initiator",
        ),
        sa.CheckConstraint("expected_size_bytes > 0", name="ck_upload_sessions_expected_size"),
        sa.CheckConstraint(
            "length(expected_sha256) = 64 AND expected_sha256 = lower(expected_sha256)",
            name="ck_upload_sessions_expected_sha",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_upload_sessions_deadline"),
        sa.CheckConstraint(
            f"failure_reason IS NULL OR failure_reason IN ({_in_list(FAILURE_REASONS)})",
            name="ck_upload_sessions_failure_reason",
        ),
        sa.CheckConstraint(
            "(status IN ('failed', 'aborted', 'expired') AND failure_reason IS NOT NULL) OR "
            "(status NOT IN ('failed', 'aborted', 'expired') AND failure_reason IS NULL)",
            name="ck_upload_sessions_failure_state",
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)", name="ck_upload_sessions_completed_pair"
        ),
    )
    op.create_index(
        "ix_upload_sessions_scope_status", "upload_sessions",
        ["tenant_id", "site_id", "session_id", "status", "expires_at"],
    )

    op.create_table(
        "session_read_grants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("grantee_user_id", sa.String(36), nullable=False),
        sa.Column("granted_by_user_id", sa.String(36), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_user_id", sa.String(36)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id"],
            ["training_sessions.tenant_id", "training_sessions.site_id", "training_sessions.id"],
            ondelete="RESTRICT", name="fk_session_read_grants_session_scope",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_grantee"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_grantor"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_session_read_grants_revoker"
        ),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="ck_session_read_grants_deadline"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="ck_session_read_grants_revoked_order"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_session_read_grants_revocation_actor",
        ),
    )
    op.create_index(
        "uq_session_read_grants_active", "session_read_grants",
        ["tenant_id", "site_id", "session_id", "grantee_user_id"],
        unique=True, sqlite_where=sa.text("revoked_at IS NULL"), postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_session_read_grants_lookup", "session_read_grants",
        ["tenant_id", "site_id", "session_id", "grantee_user_id"],
    )

    op.create_table(
        "asset_read_grants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("grantee_user_id", sa.String(36), nullable=False),
        sa.Column("granted_by_user_id", sa.String(36), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_user_id", sa.String(36)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_asset_read_grants_asset_scope",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_grantee"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_grantor"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT", name="fk_asset_read_grants_revoker"
        ),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="ck_asset_read_grants_deadline"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="ck_asset_read_grants_revoked_order"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_asset_read_grants_revocation_actor",
        ),
    )
    op.create_index(
        "uq_asset_read_grants_active", "asset_read_grants",
        ["tenant_id", "site_id", "asset_id", "grantee_user_id"],
        unique=True, sqlite_where=sa.text("revoked_at IS NULL"), postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_asset_read_grants_lookup", "asset_read_grants",
        ["tenant_id", "site_id", "asset_id", "grantee_user_id"],
    )


def create_actor_aware_idempotency_indexes(*, include_resource_index: bool = False):
    """两条部分唯一索引按主体分区。

    PostgreSQL 路径保留 0002 已建的 ix_idempotency_records_resource；只有 SQLite
    整表重建后需要重新创建它，否则会重复建索引。
    """
    op.create_index(
        "uq_idempotency_user_scope_key", "idempotency_records",
        ["tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash"],
        unique=True, sqlite_where=sa.text("actor_kind = 'user'"), postgresql_where=sa.text("actor_kind = 'user'"),
    )
    op.create_index(
        "uq_idempotency_edge_scope_key", "idempotency_records",
        ["tenant_id", "site_id", "edge_node_id", "operation", "target_id", "key_hash"],
        unique=True,
        sqlite_where=sa.text("actor_kind = 'edge_node'"),
        postgresql_where=sa.text("actor_kind = 'edge_node'"),
    )
    if include_resource_index:
        op.create_index("ix_idempotency_records_resource", "idempotency_records", ["resource_kind", "resource_id"])


def upgrade_postgres_idempotency():
    op.add_column(
        "idempotency_records",
        sa.Column("actor_kind", sa.String(16), nullable=False, server_default="user"),
    )
    op.add_column("idempotency_records", sa.Column("edge_node_id", sa.String(36)))
    op.alter_column("idempotency_records", "user_id", existing_type=sa.String(36), nullable=True)
    op.drop_constraint("uq_idempotency_scope_key", "idempotency_records", type_="unique")
    op.create_foreign_key(
        "fk_idempotency_records_edge_node_scope", "idempotency_records", "edge_nodes",
        ["tenant_id", "site_id", "edge_node_id"], ["tenant_id", "site_id", "id"], ondelete="RESTRICT",
    )
    op.drop_constraint("ck_idempotency_records_operation", "idempotency_records", type_="check")
    op.create_check_constraint(
        "ck_idempotency_records_operation",
        "idempotency_records",
        f"operation IN ({_in_list(ALL_OPERATIONS)})",
    )
    op.drop_constraint("ck_idempotency_records_kind", "idempotency_records", type_="check")
    op.create_check_constraint(
        "ck_idempotency_records_kind",
        "idempotency_records",
        f"resource_kind IN ({_in_list(ALL_RESOURCE_KINDS)})",
    )
    op.create_check_constraint(
        "ck_idempotency_records_actor_kind", "idempotency_records", "actor_kind IN ('user', 'edge_node')"
    )
    op.create_check_constraint(
        "ck_idempotency_records_actor",
        "idempotency_records",
        "(actor_kind = 'user' AND user_id IS NOT NULL AND edge_node_id IS NULL) OR "
        "(actor_kind = 'edge_node' AND user_id IS NULL AND edge_node_id IS NOT NULL)",
    )
    create_actor_aware_idempotency_indexes()


def upgrade_sqlite_idempotency():
    """SQLite 不能原地改 CHECK/唯一约束，按官方 batch 语义重建整表并原样复制数据。"""
    op.create_table(
        "idempotency_records_new",
        *idempotency_columns(actor_aware=True),
        *idempotency_constraints(actor_aware=True),
    )
    op.execute(
        "INSERT INTO idempotency_records_new "
        "(id, tenant_id, site_id, actor_kind, user_id, edge_node_id, operation, target_id, "
        " key_hash, request_hash, resource_kind, resource_id, created_at) "
        "SELECT id, tenant_id, site_id, 'user', user_id, NULL, operation, target_id, "
        "       key_hash, request_hash, resource_kind, resource_id, created_at "
        "FROM idempotency_records"
    )
    op.drop_table("idempotency_records")
    op.rename_table("idempotency_records_new", "idempotency_records")
    create_actor_aware_idempotency_indexes(include_resource_index=True)


def upgrade():
    create_media_tables()
    if op.get_bind().dialect.name == "sqlite":
        upgrade_sqlite_idempotency()
    else:
        upgrade_postgres_idempotency()


def guard_downgrade():
    """降级前显式报告受影响范围；有任何需保留记录就失败，绝不静默丢弃。"""
    bind = op.get_bind()
    blocking = {}
    for table in MEDIA_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            blocking[table] = int(count)
    edge_actor = bind.execute(
        sa.text("SELECT count(*) FROM idempotency_records WHERE actor_kind = 'edge_node'")
    ).scalar_one()
    if edge_actor:
        blocking["idempotency_records.edge_node"] = int(edge_actor)
    new_operation = bind.execute(
        sa.text(
            "SELECT count(*) FROM idempotency_records WHERE operation IN "
            f"({_in_list(NEW_OPERATIONS)}) OR resource_kind IN ({_in_list(NEW_RESOURCE_KINDS)})"
        )
    ).scalar_one()
    if new_operation:
        blocking["idempotency_records.new_operation"] = int(new_operation)
    if blocking:
        details = ", ".join(f"{name}={count}" for name, count in sorted(blocking.items()))
        raise RuntimeError(
            "拒绝降级到 20261110_0002：仍有需保留的业务记录或新主体幂等记录（"
            f"{details}）。请先导出并处置这些记录，不能声明无损降级。"
        )


def downgrade_postgres_idempotency():
    op.drop_index("uq_idempotency_edge_scope_key", table_name="idempotency_records")
    op.drop_index("uq_idempotency_user_scope_key", table_name="idempotency_records")
    op.drop_constraint("ck_idempotency_records_actor", "idempotency_records", type_="check")
    op.drop_constraint("ck_idempotency_records_actor_kind", "idempotency_records", type_="check")
    op.drop_constraint("ck_idempotency_records_operation", "idempotency_records", type_="check")
    op.create_check_constraint(
        "ck_idempotency_records_operation",
        "idempotency_records",
        f"operation IN ({_in_list(ALL_OPERATIONS[:3])})",
    )
    op.drop_constraint("ck_idempotency_records_kind", "idempotency_records", type_="check")
    op.create_check_constraint(
        "ck_idempotency_records_kind",
        "idempotency_records",
        f"resource_kind IN ({_in_list(ALL_RESOURCE_KINDS[:3])})",
    )
    op.alter_column("idempotency_records", "user_id", existing_type=sa.String(36), nullable=False)
    op.drop_constraint("fk_idempotency_records_edge_node_scope", "idempotency_records", type_="foreignkey")
    op.drop_column("idempotency_records", "edge_node_id")
    op.drop_column("idempotency_records", "actor_kind")
    op.create_unique_constraint(
        "uq_idempotency_scope_key", "idempotency_records",
        ["tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash"],
    )


def downgrade_sqlite_idempotency():
    op.create_table(
        "idempotency_records_old",
        *idempotency_columns(actor_aware=False),
        *idempotency_constraints(actor_aware=False),
    )
    op.execute(
        "INSERT INTO idempotency_records_old "
        "(id, tenant_id, site_id, user_id, operation, target_id, key_hash, request_hash, "
        " resource_kind, resource_id, created_at) "
        "SELECT id, tenant_id, site_id, user_id, operation, target_id, key_hash, request_hash, "
        "       resource_kind, resource_id, created_at "
        "FROM idempotency_records"
    )
    op.drop_table("idempotency_records")
    op.rename_table("idempotency_records_old", "idempotency_records")
    op.create_index("ix_idempotency_records_resource", "idempotency_records", ["resource_kind", "resource_id"])


def downgrade():
    guard_downgrade()
    if op.get_bind().dialect.name == "sqlite":
        downgrade_sqlite_idempotency()
    else:
        downgrade_postgres_idempotency()
    for table in reversed(MEDIA_TABLES):
        if table == "asset_read_grants":
            op.drop_index("ix_asset_read_grants_lookup", table_name=table)
            op.drop_index("uq_asset_read_grants_active", table_name=table)
        elif table == "session_read_grants":
            op.drop_index("ix_session_read_grants_lookup", table_name=table)
            op.drop_index("uq_session_read_grants_active", table_name=table)
        elif table == "upload_sessions":
            op.drop_index("ix_upload_sessions_scope_status", table_name=table)
        elif table == "video_assets":
            op.drop_index("ix_video_assets_creator", table_name=table)
            op.drop_index("ix_video_assets_session_cursor", table_name=table)
        elif table == "training_sessions":
            op.drop_index("ix_training_sessions_creator", table_name=table)
            op.drop_index("ix_training_sessions_scope_cursor", table_name=table)
        op.drop_table(table)
