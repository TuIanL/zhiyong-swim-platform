"""M3 private media transfer support tables and immutable verification references.

Downgrade refuses to discard any media transfer evidence or completed upload record.
SQLite keeps FK enforcement enabled and temporarily snapshots only child-row values
while rebuilding the Asset parent table; the operation remains one explicit DDL txn.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261114_0004"
down_revision = "20261112_0003"
branch_labels = None
depends_on = None

NEW_OPERATION = "upload.complete"
PREVIOUS_OPERATIONS = (
    "edge_node.create", "device.create", "edge_credential.issue",
    "training_session.create", "upload_intent.create",
)
FAILURE_REASONS = "'upload_aborted', 'upload_expired', 'session_cancelled', 'upload_failed', 'validation_failed'"


def _in_list(values):
    return ", ".join("'" + value + "'" for value in values)


def _assert_no_unsupported_existing_assets():
    bind = op.get_bind()
    ready = bind.execute(sa.text("SELECT count(*) FROM video_assets WHERE status = 'ready'")).scalar_one()
    if ready:
        raise RuntimeError(f"拒绝M3迁移：发现 {ready} 条既有ready资产，必须先提供真实验证与对象绑定证据")
    derived = bind.execute(sa.text(
        "SELECT count(*) FROM video_assets WHERE derived_from_asset_id IS NOT NULL"
    )).scalar_one()
    if derived:
        raise RuntimeError(f"拒绝SQLite父表重建：发现 {derived} 条既有派生引用，需要单独迁移设计")


def _create_upload_sessions(*, m3=True):
    columns = [
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
    ]
    if m3:
        columns.extend([
            sa.Column("part_size_bytes", sa.Integer()),
            sa.Column("part_count", sa.Integer()),
            sa.Column("complete_manifest_hash", sa.String(64)),
            sa.Column("complete_requested_at", sa.DateTime(timezone=True)),
        ])
    columns.extend([
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ])
    constraints = [
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", name="uq_upload_sessions_asset"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_upload_sessions_asset_scope",
        ),
        sa.ForeignKeyConstraint(["initiator_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_upload_sessions_initiator_user"),
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
            f"failure_reason IS NULL OR failure_reason IN ({FAILURE_REASONS})",
            name="ck_upload_sessions_failure_reason",
        ),
        sa.CheckConstraint(
            "(status IN ('failed', 'aborted', 'expired') AND failure_reason IS NOT NULL) OR "
            "(status NOT IN ('failed', 'aborted', 'expired') AND failure_reason IS NULL)",
            name="ck_upload_sessions_failure_state",
        ),
        sa.CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)",
                           name="ck_upload_sessions_completed_pair"),
    ]
    if m3:
        constraints.extend([
            sa.UniqueConstraint("tenant_id", "site_id", "session_id", "asset_id", "id",
                                name="uq_upload_sessions_scope_asset_id"),
            sa.CheckConstraint(
                "(part_size_bytes IS NULL AND part_count IS NULL) OR "
                "(part_size_bytes IS NOT NULL AND part_size_bytes > 0 AND part_count IS NOT NULL "
                "AND part_count BETWEEN 1 AND 10000)", name="ck_upload_sessions_layout_pair",
            ),
            sa.CheckConstraint(
                "(complete_manifest_hash IS NULL AND complete_requested_at IS NULL) OR "
                "(complete_manifest_hash IS NOT NULL AND length(complete_manifest_hash) = 64 "
                "AND complete_requested_at IS NOT NULL)", name="ck_upload_sessions_manifest_pair",
            ),
            sa.CheckConstraint(
                "status NOT IN ('completing', 'completed') OR complete_manifest_hash IS NOT NULL",
                name="ck_upload_sessions_complete_requires_manifest",
            ),
        ])
    op.create_table("upload_sessions", *columns, *constraints)
    op.create_index("ix_upload_sessions_scope_status", "upload_sessions",
                    ["tenant_id", "site_id", "session_id", "status", "expires_at"])


def _create_asset_read_grants():
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
        sa.ForeignKeyConstraint(["grantee_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_asset_read_grants_grantee"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_asset_read_grants_grantor"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_asset_read_grants_revoker"),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > granted_at",
                           name="ck_asset_read_grants_deadline"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at",
                           name="ck_asset_read_grants_revoked_order"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL)",
            name="ck_asset_read_grants_revocation_actor",
        ),
    )
    op.create_index("uq_asset_read_grants_active", "asset_read_grants",
                    ["tenant_id", "site_id", "asset_id", "grantee_user_id"], unique=True,
                    sqlite_where=sa.text("revoked_at IS NULL"), postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_asset_read_grants_lookup", "asset_read_grants",
                    ["tenant_id", "site_id", "asset_id", "grantee_user_id"])


def _create_media_objects():
    op.create_table(
        "media_objects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("upload_session_id", sa.String(36), nullable=False),
        sa.Column("provider_profile", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("provider_upload_id", sa.String(512)),
        sa.Column("object_version", sa.String(512)),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("observed_size_bytes", sa.BigInteger()),
        sa.Column("observed_sha256", sa.String(64)),
        sa.Column("observed_media_type", sa.String(128)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_signed_write_expires_at", sa.DateTime(timezone=True)),
        sa.Column("assembled_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_session_id", name="uq_media_objects_upload_session"),
        sa.UniqueConstraint("tenant_id", "site_id", "session_id", "asset_id", "id",
                            name="uq_media_objects_scope_asset_id"),
        sa.UniqueConstraint("tenant_id", "site_id", "id", name="uq_media_objects_scope_id"),
        sa.UniqueConstraint("provider_profile", "bucket", "object_key", name="uq_media_objects_location"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id"],
            ["video_assets.tenant_id", "video_assets.site_id", "video_assets.session_id", "video_assets.id"],
            ondelete="RESTRICT", name="fk_media_objects_asset_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "upload_session_id"],
            ["upload_sessions.tenant_id", "upload_sessions.site_id", "upload_sessions.session_id",
             "upload_sessions.asset_id", "upload_sessions.id"],
            ondelete="RESTRICT", name="fk_media_objects_upload_scope",
        ),
        sa.CheckConstraint("phase IN ('reserved','preparing','uploading','assembled','verified','delete_pending','deleted')",
                           name="ck_media_objects_phase"),
        sa.CheckConstraint("generation >= 1", name="ck_media_objects_generation"),
        sa.CheckConstraint("observed_size_bytes IS NULL OR observed_size_bytes > 0",
                           name="ck_media_objects_observed_size"),
        sa.CheckConstraint(
            "observed_sha256 IS NULL OR (length(observed_sha256) = 64 AND observed_sha256 = lower(observed_sha256))",
            name="ck_media_objects_observed_sha256"),
        sa.CheckConstraint(
            "phase <> 'verified' OR (observed_size_bytes IS NOT NULL AND observed_sha256 IS NOT NULL "
            "AND observed_media_type IS NOT NULL AND verified_at IS NOT NULL AND object_version IS NOT NULL)",
            name="ck_media_objects_verified_fields"),
        sa.CheckConstraint("phase NOT IN ('assembled','verified') OR object_version IS NOT NULL",
                           name="ck_media_objects_exact_version_required"),
        sa.CheckConstraint("phase <> 'deleted' OR deleted_at IS NOT NULL", name="ck_media_objects_deleted_time"),
    )
    op.create_index("ix_media_objects_phase_updated", "media_objects", ["phase", "updated_at"])


def _create_upload_parts():
    op.create_table(
        "upload_parts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("upload_session_id", sa.String(36), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("etag", sa.String(512)),
        sa.Column("actual_size_bytes", sa.BigInteger()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_session_id", "part_number", name="uq_upload_parts_number"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "upload_session_id"],
            ["upload_sessions.tenant_id", "upload_sessions.site_id", "upload_sessions.session_id",
             "upload_sessions.asset_id", "upload_sessions.id"],
            ondelete="RESTRICT", name="fk_upload_parts_upload_scope"),
        sa.CheckConstraint("part_number BETWEEN 1 AND 10000", name="ck_upload_parts_number"),
        sa.CheckConstraint("expected_size_bytes > 0", name="ck_upload_parts_expected_size"),
        sa.CheckConstraint("actual_size_bytes IS NULL OR actual_size_bytes > 0", name="ck_upload_parts_actual_size"),
        sa.CheckConstraint("state IN ('registered', 'confirmed', 'stale')", name="ck_upload_parts_state"),
        sa.CheckConstraint(
            "(state = 'registered' AND etag IS NULL AND actual_size_bytes IS NULL AND confirmed_at IS NULL) OR "
            "(state IN ('confirmed', 'stale') AND etag IS NOT NULL AND actual_size_bytes IS NOT NULL "
            "AND confirmed_at IS NOT NULL)", name="ck_upload_parts_confirmation_fields"),
        sa.CheckConstraint("etag IS NULL OR length(etag) BETWEEN 1 AND 512", name="ck_upload_parts_etag_length"),
    )
    op.create_index("ix_upload_parts_scope_state", "upload_parts",
                    ["tenant_id", "site_id", "upload_session_id", "state", "part_number"])


def _create_media_jobs():
    op.create_table(
        "media_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("accepted_actor_kind", sa.String(16)),
        sa.Column("accepted_user_id", sa.String(36)),
        sa.Column("accepted_auth_session_hash", sa.String(64)),
        sa.Column("accepted_edge_node_id", sa.String(36)),
        sa.Column("accepted_credential_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_id", "kind", name="uq_media_jobs_object_kind"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_id", "session_id", "asset_id", "object_id"],
            ["media_objects.tenant_id", "media_objects.site_id", "media_objects.session_id",
             "media_objects.asset_id", "media_objects.id"], ondelete="RESTRICT",
            name="fk_media_jobs_object_scope"),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_media_jobs_accepted_user"),
        # accepted_auth_session_hash is an identity snapshot, not an FK: logout must
        # delete AuthSession so the final worker recheck can reject the old identity.
        sa.ForeignKeyConstraint(["tenant_id", "site_id", "accepted_edge_node_id"],
                                ["edge_nodes.tenant_id", "edge_nodes.site_id", "edge_nodes.id"],
                                ondelete="RESTRICT", name="fk_media_jobs_edge_node_scope"),
        sa.ForeignKeyConstraint(["tenant_id", "site_id", "accepted_edge_node_id", "accepted_credential_id"],
                                ["edge_credentials.tenant_id", "edge_credentials.site_id",
                                 "edge_credentials.edge_node_id", "edge_credentials.id"],
                                ondelete="RESTRICT", name="fk_media_jobs_credential_scope"),
        sa.CheckConstraint("kind IN ('initialize', 'complete', 'cleanup')", name="ck_media_jobs_kind"),
        sa.CheckConstraint("state IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed')",
                           name="ck_media_jobs_state"),
        sa.CheckConstraint("attempts >= 0 AND generation >= 1", name="ck_media_jobs_attempts_generation"),
        sa.CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)", name="ck_media_jobs_lease_pair"),
        sa.CheckConstraint(
            "(kind = 'complete' AND ((accepted_actor_kind = 'user' AND accepted_user_id IS NOT NULL "
            "AND accepted_auth_session_hash IS NOT NULL AND accepted_edge_node_id IS NULL "
            "AND accepted_credential_id IS NULL) OR (accepted_actor_kind = 'edge_node' "
            "AND accepted_user_id IS NULL AND accepted_auth_session_hash IS NULL "
            "AND accepted_edge_node_id IS NOT NULL AND accepted_credential_id IS NOT NULL))) OR "
            "(kind <> 'complete' AND accepted_actor_kind IS NULL AND accepted_user_id IS NULL "
            "AND accepted_auth_session_hash IS NULL AND accepted_edge_node_id IS NULL "
            "AND accepted_credential_id IS NULL)", name="ck_media_jobs_accepted_actor"),
    )
    op.create_index("ix_media_jobs_state_next_lease", "media_jobs", ["state", "next_attempt_at", "lease_until"])


def _create_media_cleanup_candidates():
    op.create_table(
        "media_cleanup_candidates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("object_id", sa.String(36)),
        sa.Column("session_id", sa.String(36)),
        sa.Column("asset_id", sa.String(36)),
        sa.Column("provider_profile", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("upload_id", sa.String(512)),
        sa.Column("object_version", sa.String(512)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_hash", name="uq_media_cleanup_identity_hash"),
        sa.ForeignKeyConstraint(["tenant_id", "site_id"], ["sites.tenant_id", "sites.id"],
                                ondelete="RESTRICT", name="fk_media_cleanup_site_scope"),
        sa.ForeignKeyConstraint(["tenant_id", "site_id", "object_id"],
                                ["media_objects.tenant_id", "media_objects.site_id", "media_objects.id"],
                                ondelete="RESTRICT", name="fk_media_cleanup_object_scope"),
        sa.CheckConstraint("kind IN ('multipart', 'object')", name="ck_media_cleanup_kind"),
        sa.CheckConstraint("state IN ('observed', 'queued', 'running', 'retry_wait', 'deleted', 'failed', 'manual')",
                           name="ck_media_cleanup_state"),
        sa.CheckConstraint("attempts >= 0 AND generation >= 1", name="ck_media_cleanup_attempts_generation"),
        sa.CheckConstraint("last_seen_at >= first_seen_at AND not_before >= first_seen_at",
                           name="ck_media_cleanup_observation_order"),
        sa.CheckConstraint(
            "(state = 'running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'running' AND lease_token IS NULL AND lease_until IS NULL)", name="ck_media_cleanup_lease_pair"),
        sa.CheckConstraint("(object_id IS NULL) = (session_id IS NULL AND asset_id IS NULL)",
                           name="ck_media_cleanup_object_scope_pair"),
    )
    op.create_index("ix_media_cleanup_state_deadline", "media_cleanup_candidates",
                    ["state", "not_before", "next_attempt_at"])


def _sqlite_snapshot_children_and_rebuild_asset(*, upgrade: bool):
    """Rebuild the Asset parent while FKs remain ON and preserving all child values."""
    bind = op.get_bind()
    bind.exec_driver_sql(
        "CREATE TABLE _m3_upload_sessions_backup AS SELECT * FROM upload_sessions"
    )
    bind.exec_driver_sql(
        "CREATE TABLE _m3_asset_read_grants_backup AS SELECT * FROM asset_read_grants"
    )
    op.drop_table("asset_read_grants")
    op.drop_table("upload_sessions")
    with op.batch_alter_table("video_assets", recreate="always",
                              reflect_kwargs={"resolve_fks": False}) as batch:
        if upgrade:
            batch.add_column(sa.Column("storage_object_ref", sa.String(36)))
            batch.add_column(sa.Column("verified_size_bytes", sa.BigInteger()))
            batch.add_column(sa.Column("verified_media_type", sa.String(128)))
            batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True)))
            batch.drop_constraint("ck_video_assets_ready_requires_verification", type_="check")
            batch.create_check_constraint(
                "ck_video_assets_ready_requires_verification",
                "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL "
                "AND size_bytes IS NOT NULL AND media_type IS NOT NULL AND storage_object_ref IS NOT NULL "
                "AND verified_size_bytes IS NOT NULL AND verified_media_type IS NOT NULL AND verified_at IS NOT NULL "
                "AND size_bytes = verified_size_bytes AND media_type = verified_media_type)",
            )
            batch.create_check_constraint(
                "ck_video_assets_unverified_has_no_reference",
                "status = 'ready' OR (storage_object_ref IS NULL AND verified_size_bytes IS NULL "
                "AND verified_media_type IS NULL AND verified_at IS NULL)",
            )
        else:
            batch.drop_constraint("fk_video_assets_storage_object_scope", type_="foreignkey")
            batch.drop_constraint("ck_video_assets_unverified_has_no_reference", type_="check")
            batch.drop_constraint("ck_video_assets_ready_requires_verification", type_="check")
            batch.drop_column("storage_object_ref")
            batch.drop_column("verified_size_bytes")
            batch.drop_column("verified_media_type")
            batch.drop_column("verified_at")
            batch.create_check_constraint(
                "ck_video_assets_ready_requires_verification",
                "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL "
                "AND size_bytes IS NOT NULL AND media_type IS NOT NULL)",
            )
    _create_upload_sessions(m3=upgrade)
    copy_columns = (
        "id, tenant_id, site_id, session_id, asset_id, status, initiator_user_id, initiator_edge_node_id, "
        "failure_reason, expected_size_bytes, expected_sha256, media_type, expires_at, completed_at, created_at, updated_at"
    )
    bind.exec_driver_sql(f"INSERT INTO upload_sessions ({copy_columns}) SELECT {copy_columns} FROM _m3_upload_sessions_backup")
    op.drop_table("_m3_upload_sessions_backup")
    _create_asset_read_grants()
    grant_columns = (
        "id, tenant_id, site_id, session_id, asset_id, grantee_user_id, granted_by_user_id, granted_at, "
        "updated_at, expires_at, revoked_at, revoked_by_user_id"
    )
    bind.exec_driver_sql(f"INSERT INTO asset_read_grants ({grant_columns}) "
                         f"SELECT {grant_columns} FROM _m3_asset_read_grants_backup")
    op.drop_table("_m3_asset_read_grants_backup")


def _extend_idempotency(*, upgrade: bool):
    replacement = (*PREVIOUS_OPERATIONS, NEW_OPERATION) if upgrade else PREVIOUS_OPERATIONS
    with op.batch_alter_table("idempotency_records", recreate="always") as batch:
        batch.drop_constraint("ck_idempotency_records_operation", type_="check")
        batch.create_check_constraint("ck_idempotency_records_operation",
                                      f"operation IN ({_in_list(replacement)})")


def _sqlite_add_asset_storage_fk():
    # SQLite cannot add a table FK in place. Snapshot/drop existing children so the
    # parent can be rebuilt with FK enforcement on, then restore every child value.
    bind = op.get_bind()
    bind.exec_driver_sql("CREATE TABLE _m3_fk_upload_backup AS SELECT * FROM upload_sessions")
    bind.exec_driver_sql("CREATE TABLE _m3_fk_grant_backup AS SELECT * FROM asset_read_grants")
    op.drop_table("asset_read_grants")
    op.drop_table("upload_sessions")
    with op.batch_alter_table("video_assets", recreate="always",
                              reflect_kwargs={"resolve_fks": False}) as batch:
        batch.create_foreign_key(
            "fk_video_assets_storage_object_scope", "media_objects",
            ["tenant_id", "site_id", "session_id", "id", "storage_object_ref"],
            ["tenant_id", "site_id", "session_id", "asset_id", "id"], ondelete="RESTRICT",
        )
    _create_upload_sessions(m3=True)
    upload_columns = (
        "id, tenant_id, site_id, session_id, asset_id, status, initiator_user_id, initiator_edge_node_id, "
        "failure_reason, expected_size_bytes, expected_sha256, media_type, expires_at, completed_at, "
        "part_size_bytes, part_count, complete_manifest_hash, complete_requested_at, created_at, updated_at"
    )
    bind.exec_driver_sql(f"INSERT INTO upload_sessions ({upload_columns}) "
                         f"SELECT {upload_columns} FROM _m3_fk_upload_backup")
    op.drop_table("_m3_fk_upload_backup")
    _create_asset_read_grants()
    grant_columns = (
        "id, tenant_id, site_id, session_id, asset_id, grantee_user_id, granted_by_user_id, granted_at, "
        "updated_at, expires_at, revoked_at, revoked_by_user_id"
    )
    bind.exec_driver_sql(f"INSERT INTO asset_read_grants ({grant_columns}) "
                         f"SELECT {grant_columns} FROM _m3_fk_grant_backup")
    op.drop_table("_m3_fk_grant_backup")


def upgrade_postgres():
    op.add_column("upload_sessions", sa.Column("part_size_bytes", sa.Integer()))
    op.add_column("upload_sessions", sa.Column("part_count", sa.Integer()))
    op.add_column("upload_sessions", sa.Column("complete_manifest_hash", sa.String(64)))
    op.add_column("upload_sessions", sa.Column("complete_requested_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_upload_sessions_scope_asset_id", "upload_sessions",
                                ["tenant_id", "site_id", "session_id", "asset_id", "id"])
    op.create_check_constraint("ck_upload_sessions_layout_pair", "upload_sessions",
        "(part_size_bytes IS NULL AND part_count IS NULL) OR (part_size_bytes IS NOT NULL AND part_size_bytes > 0 "
        "AND part_count IS NOT NULL AND part_count BETWEEN 1 AND 10000)")
    op.create_check_constraint("ck_upload_sessions_manifest_pair", "upload_sessions",
        "(complete_manifest_hash IS NULL AND complete_requested_at IS NULL) OR "
        "(complete_manifest_hash IS NOT NULL AND length(complete_manifest_hash) = 64 AND complete_requested_at IS NOT NULL)")
    op.create_check_constraint("ck_upload_sessions_complete_requires_manifest", "upload_sessions",
        "status NOT IN ('completing', 'completed') OR complete_manifest_hash IS NOT NULL")
    op.create_index("uq_edge_credentials_scope_id", "edge_credentials",
                    ["tenant_id", "site_id", "edge_node_id", "id"], unique=True)
    _create_media_objects()
    _create_upload_parts()
    _create_media_jobs()
    _create_media_cleanup_candidates()
    op.add_column("video_assets", sa.Column("storage_object_ref", sa.String(36)))
    op.add_column("video_assets", sa.Column("verified_size_bytes", sa.BigInteger()))
    op.add_column("video_assets", sa.Column("verified_media_type", sa.String(128)))
    op.add_column("video_assets", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_video_assets_ready_requires_verification", "video_assets", type_="check")
    op.create_check_constraint("ck_video_assets_ready_requires_verification", "video_assets",
        "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL AND size_bytes IS NOT NULL "
        "AND media_type IS NOT NULL AND storage_object_ref IS NOT NULL AND verified_size_bytes IS NOT NULL "
        "AND verified_media_type IS NOT NULL AND verified_at IS NOT NULL AND size_bytes = verified_size_bytes "
        "AND media_type = verified_media_type)")
    op.create_check_constraint("ck_video_assets_unverified_has_no_reference", "video_assets",
        "status = 'ready' OR (storage_object_ref IS NULL AND verified_size_bytes IS NULL "
        "AND verified_media_type IS NULL AND verified_at IS NULL)")
    op.create_foreign_key("fk_video_assets_storage_object_scope", "video_assets", "media_objects",
        ["tenant_id", "site_id", "session_id", "id", "storage_object_ref"],
        ["tenant_id", "site_id", "session_id", "asset_id", "id"], ondelete="RESTRICT")


def upgrade():
    _assert_no_unsupported_existing_assets()
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_snapshot_children_and_rebuild_asset(upgrade=True)
        op.create_index("uq_edge_credentials_scope_id", "edge_credentials",
                        ["tenant_id", "site_id", "edge_node_id", "id"], unique=True)
        _create_media_objects()
        _create_upload_parts()
        _create_media_jobs()
        _create_media_cleanup_candidates()
        _sqlite_add_asset_storage_fk()
    else:
        upgrade_postgres()
    _extend_idempotency(upgrade=True)
    if op.get_bind().dialect.name == "sqlite":
        violations = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"M3迁移后SQLite外键检查失败：{violations[:5]}")


def _guard_downgrade():
    bind = op.get_bind()
    blocking = {}
    for table in ("media_objects", "upload_parts", "media_jobs", "media_cleanup_candidates"):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            blocking[table] = int(count)
    completed = bind.execute(sa.text(
        "SELECT count(*) FROM idempotency_records WHERE operation = 'upload.complete'"
    )).scalar_one()
    if completed:
        blocking["idempotency_records.upload.complete"] = int(completed)
    references = bind.execute(sa.text(
        "SELECT count(*) FROM video_assets WHERE storage_object_ref IS NOT NULL "
        "OR verified_at IS NOT NULL OR status = 'ready'"
    )).scalar_one()
    if references:
        blocking["video_assets.verified_reference_or_ready"] = int(references)
    if blocking:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(blocking.items()))
        raise RuntimeError(f"拒绝降级：仍有需保留的媒体传输记录（{detail}）；先导出并处置，不删除物理对象")


def downgrade_postgres():
    op.drop_constraint("fk_video_assets_storage_object_scope", "video_assets", type_="foreignkey")
    op.drop_constraint("ck_video_assets_unverified_has_no_reference", "video_assets", type_="check")
    op.drop_constraint("ck_video_assets_ready_requires_verification", "video_assets", type_="check")
    op.create_check_constraint("ck_video_assets_ready_requires_verification", "video_assets",
        "status <> 'ready' OR (checksum_sha256 IS NOT NULL AND received_at IS NOT NULL "
        "AND size_bytes IS NOT NULL AND media_type IS NOT NULL)")
    for column in ("storage_object_ref", "verified_size_bytes", "verified_media_type", "verified_at"):
        op.drop_column("video_assets", column)
    for table in ("media_cleanup_candidates", "media_jobs", "upload_parts", "media_objects"):
        op.drop_table(table)
    op.drop_index("uq_edge_credentials_scope_id", table_name="edge_credentials")
    op.drop_constraint("ck_upload_sessions_complete_requires_manifest", "upload_sessions", type_="check")
    op.drop_constraint("ck_upload_sessions_manifest_pair", "upload_sessions", type_="check")
    op.drop_constraint("ck_upload_sessions_layout_pair", "upload_sessions", type_="check")
    op.drop_constraint("uq_upload_sessions_scope_asset_id", "upload_sessions", type_="unique")
    for column in ("part_size_bytes", "part_count", "complete_manifest_hash", "complete_requested_at"):
        op.drop_column("upload_sessions", column)


def downgrade():
    _guard_downgrade()
    _extend_idempotency(upgrade=False)
    if op.get_bind().dialect.name == "sqlite":
        for table in ("media_cleanup_candidates", "media_jobs", "upload_parts", "media_objects"):
            op.drop_table(table)
        op.drop_index("uq_edge_credentials_scope_id", table_name="edge_credentials")
        _sqlite_snapshot_children_and_rebuild_asset(upgrade=False)
    else:
        downgrade_postgres()
