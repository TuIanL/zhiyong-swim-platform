"""PostgreSQL 专属：真实并发、降级守卫与受限外键（需专用可销毁实例）。"""
import threading
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from swimplatform.config import ROOT, Settings
from swimplatform.main import create_app

from pg_support import CONCURRENCY_POOL, run_concurrently

pytestmark = pytest.mark.postgresql

HEAD_REVISION = "20261112_0003"
REGISTRY_REVISION = "20261110_0002"
SHA = "a" * 64
META = {"device_time_basis": "unknown", "video_timebase_kind": "relative", "device_clock_source": "unknown"}


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/cloud/src/swimplatform/migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _pooled_app(database):
    application = create_app(Settings(database_url=database.app_url))
    application.state.engine.dispose()
    engine = create_engine(database.app_url, pool_pre_ping=True, **CONCURRENCY_POOL)
    from sqlalchemy.orm import sessionmaker

    application.state.engine = engine
    application.state.sessions = sessionmaker(engine, expire_on_commit=False)
    return application, engine


def seed_scope(client, account_factory, name="owner"):
    owner, headers = account_factory(name)
    coach, coach_headers = account_factory("coach")
    tenant = client.post("/api/v1/tenants", headers=headers, json={"name": "T", "slug": "team-a"}).json()
    site = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=headers, json={"name": "S1"}).json()
    client.post(
        f"/api/v1/tenants/{tenant['id']}/members", headers=headers,
        json={"user_id": coach["id"], "role": "coach"},
    )
    client.post(
        f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/members", headers=headers,
        json={"user_id": coach["id"]},
    )
    return {
        "owner": owner, "oh": headers, "coach": coach, "ch": coach_headers,
        "tenant": tenant, "site": site, "base": f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}",
    }


def make_session(client, org, key="pg-session-1"):
    response = client.post(
        org["base"] + "/training-sessions",
        headers={**org["ch"], "Idempotency-Key": key}, json={"title": "训练"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def intent_payload():
    return {
        "expected_size_bytes": 4096, "expected_sha256": SHA, "media_type": "video/mp4",
        "capture_metadata": dict(META),
    }


def test_concurrent_same_key_creates_one_intent_on_distinct_connections(pg_databases, seeded_account):
    database = pg_databases()
    application, engine = _pooled_app(database)
    pids = set()

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "upload_sessions" in lowered or "video_assets" in lowered:
            pids.add(connection.connection.driver_connection.info.backend_pid)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with TestClient(application) as client:
            org = seed_scope(
                client, lambda name: seeded_account(name, application=application)
            )
            session = make_session(client, org)
            url = org["base"] + f"/training-sessions/{session['id']}/upload-sessions"
            headers = {**org["ch"], "Idempotency-Key": "concurrent-intent-1"}
            body = intent_payload()

        def job(client):
            return client.post(url, headers=headers, json=body)

        results = run_concurrently(application, [job for _ in range(4)])
        assert all(response.status_code == 201 for response in results), [r.text for r in results]
        upload_ids = {response.json()["upload_session"]["id"] for response in results}
        assert len(upload_ids) == 1

        with application.state.sessions() as db:
            assert db.execute(text("SELECT count(*) FROM video_assets")).scalar_one() == 1
            assert db.execute(text("SELECT count(*) FROM upload_sessions")).scalar_one() == 1
            assert db.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one() == 1
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        engine.dispose()

    # 四个并发请求必须落在多个真实物理连接上，而不是单连接串行。
    assert len(pids) >= 2, pids


def test_concurrent_cancel_and_abort_leave_no_pending_asset(pg_databases, seeded_account):
    database = pg_databases()
    application, engine = _pooled_app(database)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            intent = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "race-intent-1"}, json=intent_payload(),
            ).json()
            session_url = org["base"] + f"/training-sessions/{session['id']}"
            upload_url = org["base"] + f"/upload-sessions/{intent['upload_session']['id']}/abort"
            asset_url = org["base"] + f"/video-assets/{intent['asset']['id']}"
            headers = org["ch"]

        barrier = threading.Barrier(2)

        def cancel(client):
            barrier.wait(timeout=15)
            return client.patch(session_url, headers=headers, json={"status": "cancelled"})

        def abort(client):
            barrier.wait(timeout=15)
            return client.post(upload_url, headers=headers)

        cancel_result, abort_result = run_concurrently(application, [cancel, abort])
        assert cancel_result.status_code == 200
        assert abort_result.status_code == 204

        with TestClient(application) as client:
            upload = client.get(
                org["base"] + f"/upload-sessions/{intent['upload_session']['id']}", headers=headers
            ).json()
            asset = client.get(asset_url, headers=headers).json()
            assert upload["status"] in {"failed", "aborted"}
            if upload["status"] == "failed":
                assert upload["failure_reason"] == "session_cancelled"
            assert asset["status"] == "failed"
            assert asset["failure_reason"] == upload["failure_reason"] or asset["failure_reason"] == "session_cancelled"
            with application.state.sessions() as db:
                assert db.execute(text(
                    "SELECT count(*) FROM video_assets WHERE status = 'pending_upload'"
                )).scalar_one() == 0
    finally:
        engine.dispose()


def test_concurrent_grant_writes_keep_one_active_row(pg_databases, seeded_account):
    database = pg_databases()
    application, engine = _pooled_app(database)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            url = org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['coach']['id']}"
            headers = org["oh"]

        def job(client):
            return client.put(url, headers=headers, json={})

        results = run_concurrently(application, [job for _ in range(4)])
        assert all(response.status_code == 204 for response in results), [r.text for r in results]
        with application.state.sessions() as db:
            assert db.execute(text(
                "SELECT count(*) FROM session_read_grants WHERE revoked_at IS NULL"
            )).scalar_one() == 1
    finally:
        engine.dispose()


def test_downgrade_refuses_when_media_rows_exist(pg_databases, seeded_account):
    database = pg_databases()
    application = create_app(Settings(database_url=database.app_url))
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            make_session(client, org)
    finally:
        application.state.engine.dispose()

    config = alembic_config(database.migration_url)
    with pytest.raises(Exception) as failure:
        command.downgrade(config, REGISTRY_REVISION)
    assert "拒绝降级" in str(failure.value)
    assert "training_sessions" in str(failure.value)

    engine = create_engine(database.migration_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM swim_cloud.alembic_version"
            )).scalar_one() == HEAD_REVISION
    finally:
        engine.dispose()


def test_downgrade_refuses_edge_actor_idempotency_rows(pg_databases):
    database = pg_databases(migrate=True, grant=False)
    engine = create_engine(database.migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO swim_cloud.tenants (id, name, slug, created_at) VALUES ('t-1','T','t-1',now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.sites (id, tenant_id, name, address, timezone, created_at) "
                "VALUES ('s-1','t-1','S1','','UTC',now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
                "VALUES ('u-1','edge@example.test','E','x',true,0,now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.edge_nodes "
                "(id, tenant_id, site_id, name, status, config_revision, credential_generation, "
                " created_by_user_id, created_at, updated_at) "
                "VALUES ('n-1','t-1','s-1','N1','active',1,0,'u-1',now(),now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.idempotency_records "
                "(id, tenant_id, site_id, actor_kind, user_id, edge_node_id, operation, target_id, key_hash, "
                " request_hash, resource_kind, resource_id, created_at) "
                "VALUES ('i-edge','t-1','s-1','edge_node',NULL,'n-1','upload_intent.create','x',:key,:request,"
                " 'upload_session','r-1',now())"
            ), {"key": "k" * 64, "request": "r" * 64})
    finally:
        engine.dispose()

    config = alembic_config(database.migration_url)
    with pytest.raises(Exception) as failure:
        command.downgrade(config, REGISTRY_REVISION)
    message = str(failure.value)
    assert "拒绝降级" in message
    assert "idempotency_records.edge_node" in message


def test_allowed_downgrade_keeps_legacy_user_idempotency(pg_databases, pg_environment):
    database = pg_databases(migrate=True, grant=False)
    engine = create_engine(database.migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO swim_cloud.tenants (id, name, slug, created_at) VALUES ('t-1','T','t-1',now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.sites (id, tenant_id, name, address, timezone, created_at) "
                "VALUES ('s-1','t-1','S1','','UTC',now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
                "VALUES ('u-1','legacy@example.test','L','x',true,0,now())"
            ))
            connection.execute(text(
                "INSERT INTO swim_cloud.idempotency_records "
                "(id, tenant_id, site_id, actor_kind, user_id, edge_node_id, operation, target_id, key_hash, "
                " request_hash, resource_kind, resource_id, created_at) "
                "VALUES ('i-1','t-1','s-1','user','u-1',NULL,'edge_node.create','s-1',:key,:request,'edge_node','r-1',now())"
            ), {"key": "a" * 64, "request": "b" * 64})
    finally:
        engine.dispose()

    config = alembic_config(database.migration_url)
    command.downgrade(config, REGISTRY_REVISION)

    engine = create_engine(database.migration_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM swim_cloud.alembic_version"
            )).scalar_one() == REGISTRY_REVISION
            assert connection.execute(text(
                "SELECT key_hash FROM swim_cloud.idempotency_records"
            )).scalar_one() == "a" * 64
    finally:
        engine.dispose()

    from swimplatform.migrate import migrate_database

    migrate_database(database.migration_url)
    pg_environment.grant_application(database)


def test_site_with_sessions_cannot_be_deleted(pg_databases, seeded_account):
    database = pg_databases()
    application = create_app(Settings(database_url=database.app_url))
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            make_session(client, org)
    finally:
        application.state.engine.dispose()

    engine = create_engine(database.admin_url)
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM swim_cloud.sites WHERE id = :id"), {"id": org["site"]["id"]}
                )
    finally:
        engine.dispose()


def test_idempotency_columns_and_partial_indexes(pg_databases, pg_environment):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        with engine.connect() as connection:
            columns = connection.execute(text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'swim_cloud' AND table_name = 'idempotency_records'"
            )).fetchall()
            mapping = {name: nullable for name, nullable in columns}
            assert mapping["actor_kind"] == "NO"
            assert mapping["user_id"] == "YES"
            assert mapping["edge_node_id"] == "YES"

            indexes = connection.execute(text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'swim_cloud' AND tablename = 'idempotency_records'"
            )).fetchall()
            definitions = {name: definition for name, definition in indexes}
            assert "uq_idempotency_user_scope_key" in definitions
            assert "uq_idempotency_edge_scope_key" in definitions
            assert "actor_kind" in definitions["uq_idempotency_user_scope_key"]
            assert "actor_kind" in definitions["uq_idempotency_edge_scope_key"]
    finally:
        engine.dispose()
