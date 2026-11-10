"""Cloud Edge Registry; retain the published six-table revision unchanged."""
from alembic import op
import sqlalchemy as sa


revision = "20261110_0002"
down_revision = "20261106_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "edge_nodes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("config_revision", sa.Integer(), nullable=False),
        sa.Column("applied_config_revision", sa.Integer()),
        sa.Column("software_version", sa.String(64)),
        sa.Column("health_status", sa.String(16)),
        sa.Column("observed_at_raw", sa.String(128)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "site_id", "id", name="uq_edge_nodes_scope_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_edge_nodes_site_scope",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_edge_nodes_created_by_user",
        ),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_edge_nodes_name"),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled')", name="ck_edge_nodes_status"),
        sa.CheckConstraint("config_revision >= 1", name="ck_edge_nodes_config_revision"),
        sa.CheckConstraint(
            "applied_config_revision IS NULL OR applied_config_revision >= 0",
            name="ck_edge_nodes_applied_config_revision",
        ),
        sa.CheckConstraint("credential_generation >= 0", name="ck_edge_nodes_credential_generation"),
        sa.CheckConstraint(
            "health_status IS NULL OR health_status IN ('ok', 'degraded', 'unknown')",
            name="ck_edge_nodes_health_status",
        ),
        sa.CheckConstraint(
            "software_version IS NULL OR length(software_version) BETWEEN 1 AND 64",
            name="ck_edge_nodes_software_version",
        ),
        sa.CheckConstraint(
            "observed_at_raw IS NULL OR length(observed_at_raw) <= 128",
            name="ck_edge_nodes_observed_at_raw",
        ),
    )
    op.create_index("ix_edge_nodes_tenant_site_status", "edge_nodes", ["tenant_id", "site_id", "status"])

    op.create_table(
        "devices",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("edge_node_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("hardware_serial", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "site_id", "edge_node_id", "id", name="uq_devices_scope_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_devices_edge_node_scope",
        ),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_devices_name"),
        sa.CheckConstraint("kind = 'camera'", name="ck_devices_kind"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_devices_status"),
        sa.CheckConstraint(
            "hardware_serial IS NULL OR length(hardware_serial) BETWEEN 1 AND 120",
            name="ck_devices_hardware_serial",
        ),
    )
    op.create_index(
        "ix_devices_tenant_site_node_status", "devices", ["tenant_id", "site_id", "edge_node_id", "status"]
    )

    op.create_table(
        "edge_credentials",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("edge_node_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by_user_id", sa.String(36), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_user_id", sa.String(36)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_edge_credentials_token_hash"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "edge_node_id"],
            ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
            ondelete="RESTRICT", name="fk_edge_credentials_edge_node_scope",
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_edge_credentials_issued_by_user",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"], ["users.id"],
            ondelete="RESTRICT", name="fk_edge_credentials_revoked_by_user",
        ),
        sa.CheckConstraint("generation >= 0", name="ck_edge_credentials_generation"),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_edge_credentials_token_hash"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_edge_credentials_deadline"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= issued_at", name="ck_edge_credentials_revocation_time"
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_edge_credentials_revocation_actor",
        ),
    )
    op.create_index(
        "ix_edge_credentials_node_generation", "edge_credentials",
        ["tenant_id", "site_id", "edge_node_id", "generation"],
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_kind", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "site_id", "user_id", "operation", "target_id", "key_hash",
            name="uq_idempotency_scope_key",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
            ondelete="RESTRICT", name="fk_idempotency_records_site_scope",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_idempotency_records_user"
        ),
        sa.CheckConstraint(
            "operation IN ('edge_node.create', 'device.create', 'edge_credential.issue')",
            name="ck_idempotency_records_operation",
        ),
        sa.CheckConstraint(
            "resource_kind IN ('edge_node', 'device', 'edge_credential')",
            name="ck_idempotency_records_kind",
        ),
        sa.CheckConstraint("length(key_hash) = 64", name="ck_idempotency_records_key_hash"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_idempotency_records_request_hash"),
    )
    op.create_index("ix_idempotency_records_resource", "idempotency_records", ["resource_kind", "resource_id"])


def downgrade():
    op.drop_index("ix_idempotency_records_resource", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_edge_credentials_node_generation", table_name="edge_credentials")
    op.drop_table("edge_credentials")
    op.drop_index("ix_devices_tenant_site_node_status", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_edge_nodes_tenant_site_status", table_name="edge_nodes")
    op.drop_table("edge_nodes")
