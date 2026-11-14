"""五张新表与幂等扩展的库层约束（SQLite 与 PostgreSQL 共享）。

这些用例直接写库，验证的是数据库本身拒绝非法状态，而不是 API 校验；
不得被当作业务闭环证据（业务路径见 test_media_foundation/authorization）。
"""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
SHA = "a" * 64

SESSION_SQL = (
    "INSERT INTO training_sessions "
    "(id, tenant_id, site_id, created_by_user_id, title, status, started_at, completed_at, cancelled_at, created_at, updated_at) "
    "VALUES (:id, :tid, :sid, :uid, :title, :status, :started, :completed, :cancelled, :created, :updated)"
)
ASSET_SQL = (
    "INSERT INTO video_assets "
    "(id, tenant_id, site_id, session_id, origin, created_by_user_id, source_edge_node_id, source_device_id, "
    " derived_from_asset_id, status, failure_reason, capture_started_at_utc, capture_ended_at_utc, "
    " device_capture_started_at_raw, device_capture_ended_at_raw, device_time_basis, device_timezone, "
    " device_utc_offset_minutes, video_timebase_kind, video_timebase_metadata, device_clock_source, "
    " device_clock_offset_ms, device_clock_accuracy_ms, received_at, media_type, size_bytes, checksum_sha256, "
    " created_at, updated_at) "
    "VALUES (:id, :tid, :sid, :session, :origin, :creator, :node, :device, :derived, :status, :reason, "
    " :cap_start, :cap_end, :raw_start, :raw_end, :basis, :tz, :offset, :timebase, NULL, :clock, NULL, NULL, "
    " :received, :media, :size, :checksum, :created, :updated)"
)
UPLOAD_SQL = (
    "INSERT INTO upload_sessions "
    "(id, tenant_id, site_id, session_id, asset_id, status, initiator_user_id, initiator_edge_node_id, "
    " failure_reason, expected_size_bytes, expected_sha256, media_type, expires_at, completed_at, created_at, updated_at) "
    "VALUES (:id, :tid, :sid, :session, :asset, :status, :user, :node, :reason, :size, :sha, 'video/mp4', "
    " :expires, :completed, :created, :updated)"
)
GRANT_SQL = (
    "INSERT INTO session_read_grants "
    "(id, tenant_id, site_id, session_id, grantee_user_id, granted_by_user_id, granted_at, updated_at, expires_at, revoked_at, revoked_by_user_id) "
    "VALUES (:id, :tid, :sid, :session, :grantee, :grantor, :now, :now, NULL, :revoked, :revoker)"
)
IDEMPOTENCY_SQL = (
    "INSERT INTO idempotency_records "
    "(id, tenant_id, site_id, actor_kind, user_id, edge_node_id, operation, target_id, key_hash, request_hash, "
    " resource_kind, resource_id, created_at) "
    "VALUES (:id, :tid, :sid, :actor, :user, :node, :operation, :target, :key, :request, :kind, :resource, :now)"
)


@pytest.fixture
def scope(app):
    ids = {name: str(uuid4()) for name in ("tenant", "site", "user", "session", "asset", "grantee")}
    with app.state.engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO tenants (id, name, slug, created_at) VALUES (:id, 'T', 'team-a', :now)"
        ), {"id": ids["tenant"], "now": NOW})
        connection.execute(text(
            "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
            "VALUES (:id, :tid, 'S1', '', 'Asia/Shanghai', :now)"
        ), {"id": ids["site"], "tid": ids["tenant"], "now": NOW})
        for key in ("user", "grantee"):
            connection.execute(text(
                "INSERT INTO users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
                "VALUES (:id, :email, 'U', 'x', true, 0, :now)"
            ), {"id": ids[key], "email": f"{ids[key]}@example.test", "now": NOW})
        connection.execute(text(SESSION_SQL), {
            "id": ids["session"], "tid": ids["tenant"], "sid": ids["site"], "uid": ids["user"],
            "title": "T", "status": "planned", "started": None, "completed": None, "cancelled": None,
            "created": NOW, "updated": NOW,
        })
        connection.execute(text(ASSET_SQL), asset_params(ids))
    return ids


def asset_params(ids, **overrides):
    params = {
        "id": ids["asset"], "tid": ids["tenant"], "sid": ids["site"], "session": ids["session"],
        "origin": "manual", "creator": ids["user"], "node": None, "device": None, "derived": None,
        "status": "pending_upload", "reason": None, "cap_start": None, "cap_end": None,
        "raw_start": None, "raw_end": None, "basis": "unknown", "tz": None, "offset": None,
        "timebase": "unknown", "clock": "unknown", "received": None, "media": None, "size": None,
        "checksum": None, "created": NOW, "updated": NOW,
    }
    params.update(overrides)
    return params


def insert_asset(app, ids, **overrides):
    row_id = overrides.pop("id", str(uuid4()))
    with app.state.engine.begin() as connection:
        connection.execute(text(ASSET_SQL), asset_params(ids, id=row_id, **overrides))


def test_ready_requires_server_verified_metadata(app, scope):
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, status="ready")

    with pytest.raises(IntegrityError):
        insert_asset(app, scope, status="ready", checksum=SHA, received=NOW, media="video/mp4")

    insert_asset(
        app, scope, status="ready", checksum=SHA, received=NOW, media="video/mp4", size=1024
    )


def test_failure_reason_pairs_with_status(app, scope):
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, status="failed")
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, status="pending_upload", reason="upload_aborted")
    insert_asset(app, scope, status="failed", reason="upload_aborted")


def test_source_pairing_follows_origin(app, scope):
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, origin="edge", creator=None)
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, origin="manual", creator=scope["user"], node=str(uuid4()), device=str(uuid4()))
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, origin="manual", creator=None)


def test_derived_reference_must_stay_in_scope(app, scope):
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, origin="derived", creator=None)

    # 自引用必须被拒绝（父引用等于自身）。
    self_ref = str(uuid4())
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, id=self_ref, origin="derived", creator=None, derived=self_ref)

    # 同 Session 的既有父引用是允许的结构（ready 前置不在本片校验）。
    insert_asset(app, scope, origin="derived", creator=None, derived=scope["asset"])

    other_session = str(uuid4())
    with app.state.engine.begin() as connection:
        connection.execute(text(SESSION_SQL), {
            "id": other_session, "tid": scope["tenant"], "sid": scope["site"], "uid": scope["user"],
            "title": "T2", "status": "planned", "started": None, "completed": None, "cancelled": None,
            "created": NOW, "updated": NOW,
        })
    # 跨 Session 的派生父引用必须被复合外键拒绝。
    with pytest.raises(IntegrityError):
        insert_asset(app, scope, origin="derived", creator=None, derived=scope["asset"], session=other_session)


def test_session_status_and_times_must_agree(app, scope):
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(SESSION_SQL), {
                "id": str(uuid4()), "tid": scope["tenant"], "sid": scope["site"], "uid": scope["user"],
                "title": "bad", "status": "completed", "started": NOW, "completed": None, "cancelled": None,
                "created": NOW, "updated": NOW,
            })
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(SESSION_SQL), {
                "id": str(uuid4()), "tid": scope["tenant"], "sid": scope["site"], "uid": scope["user"],
                "title": "bad", "status": "planned", "started": NOW, "completed": None, "cancelled": None,
                "created": NOW, "updated": NOW,
            })


def test_upload_session_has_exactly_one_initiator(app, scope):
    base = {
        "tid": scope["tenant"], "sid": scope["site"], "session": scope["session"], "asset": scope["asset"],
        "status": "uploading", "reason": None, "size": 1024, "sha": SHA,
        "expires": datetime(2026, 11, 13, 10, 0, tzinfo=UTC), "completed": None,
        "created": NOW, "updated": NOW,
    }
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(UPLOAD_SQL), {**base, "id": str(uuid4()), "user": None, "node": None})
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(UPLOAD_SQL), {**base, "id": str(uuid4()), "user": scope["user"], "node": str(uuid4())})
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(UPLOAD_SQL), {**base, "id": str(uuid4()), "user": scope["user"], "node": None,
                                                  "expires": NOW})
    with app.state.engine.begin() as connection:
        connection.execute(text(UPLOAD_SQL), {**base, "id": str(uuid4()), "user": scope["user"], "node": None})


def test_only_one_active_grant_per_grantee(app, scope):
    params = {
        "tid": scope["tenant"], "sid": scope["site"], "session": scope["session"],
        "grantee": scope["grantee"], "grantor": scope["user"], "now": NOW,
    }
    with app.state.engine.begin() as connection:
        connection.execute(text(GRANT_SQL), {**params, "id": str(uuid4()), "revoked": None, "revoker": None})

    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(GRANT_SQL), {**params, "id": str(uuid4()), "revoked": None, "revoker": None})

    # 软撤销后可以重新授予，历史行保留。
    with app.state.engine.begin() as connection:
        connection.execute(text(
            "UPDATE session_read_grants SET revoked_at = :now, revoked_by_user_id = :revoker WHERE session_id = :session"
        ), {"now": NOW, "revoker": scope["user"], "session": scope["session"]})
        connection.execute(text(GRANT_SQL), {**params, "id": str(uuid4()), "revoked": None, "revoker": None})


def test_idempotency_actor_pairing_and_vocabulary(app, scope):
    base = {
        "tid": scope["tenant"], "sid": scope["site"], "target": scope["session"],
        "key": "k" * 64, "request": "r" * 64, "now": NOW,
    }
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(IDEMPOTENCY_SQL), {
                **base, "id": str(uuid4()), "actor": "user", "user": None, "node": None,
                "operation": "upload_intent.create", "kind": "upload_session", "resource": scope["asset"],
            })
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(IDEMPOTENCY_SQL), {
                **base, "id": str(uuid4()), "actor": "edge_node", "user": scope["user"], "node": str(uuid4()),
                "operation": "upload_intent.create", "kind": "upload_session", "resource": scope["asset"],
            })
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as connection:
            connection.execute(text(IDEMPOTENCY_SQL), {
                **base, "id": str(uuid4()), "actor": "user", "user": scope["user"], "node": None,
                "operation": "unknown.operation", "kind": "upload_session", "resource": scope["asset"],
            })

    # 既有 Registry 词表与新增词表都必须仍然可写入。
    with app.state.engine.begin() as connection:
        for index, (operation, kind) in enumerate((
            ("edge_node.create", "edge_node"),
            ("training_session.create", "training_session"),
            ("upload_intent.create", "upload_session"),
        )):
            connection.execute(text(IDEMPOTENCY_SQL), {
                **base, "id": str(uuid4()), "actor": "user", "user": scope["user"], "node": None,
                "operation": operation, "kind": kind, "resource": str(uuid4()),
                "key": f"{index}" * 64, "request": f"{index}" * 64,
            })
