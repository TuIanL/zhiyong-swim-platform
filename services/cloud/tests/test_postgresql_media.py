"""PostgreSQL 专属：真实并发、降级守卫与受限外键（需专用可销毁实例）。"""
import threading
import time
from hashlib import sha256
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from swimplatform.config import ROOT, Settings
from swimplatform.main import create_app
from swimplatform.media_transfer import (
    _claim_job, _finalize_ready, _job_current, cleanup_candidates, sweep_expired,
)
from swimplatform.models import (
    IdempotencyRecord, MediaCleanupCandidate, MediaJob, MediaObject, UploadPart, UploadSession, VideoAsset,
)
from swimplatform.security import token_hash

from pg_support import CONCURRENCY_POOL, run_concurrently

pytestmark = pytest.mark.postgresql

HEAD_REVISION = "20261114_0004"
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


def capture_pids(app, tables):
    """记录访问指定表的真实 backend PID 集合；用于并发证据而不只是响应码。"""
    seen = set()

    def before(connection, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if any(table in lowered for table in tables):
            seen.add(connection.connection.driver_connection.info.backend_pid)

    engine = app.state.engine
    event.listen(engine, "before_cursor_execute", before)
    return seen, lambda: event.remove(engine, "before_cursor_execute", before)


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
            assert db.execute(text(
                "SELECT count(*) FROM idempotency_records WHERE operation = 'upload_intent.create'"
            )).scalar_one() == 1
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

        pids, stop = capture_pids(application, ["training_sessions", "upload_sessions"])
        barrier = threading.Barrier(2)

        def cancel(client):
            barrier.wait(timeout=15)
            return client.patch(session_url, headers=headers, json={"status": "cancelled"})

        def abort(client):
            barrier.wait(timeout=15)
            return client.post(upload_url, headers=headers)

        try:
            cancel_result, abort_result = run_concurrently(application, [cancel, abort])
        finally:
            stop()
        assert cancel_result.status_code == 200
        assert abort_result.status_code == 204
        assert len(pids) >= 2, pids

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

        pids, stop = capture_pids(application, ["session_read_grants"])

        def job(client):
            return client.put(url, headers=headers, json={})

        try:
            results = run_concurrently(application, [job for _ in range(4)])
        finally:
            stop()
        assert all(response.status_code == 204 for response in results), [r.text for r in results]
        assert len(pids) >= 2, pids
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


# ---- 受控并发：行锁顺序与物理连接证据 ------------------------------------

SESSION_LOCK = lambda statement: "from training_sessions" in statement and "for update" in statement
UPLOAD_LOCK = lambda statement: "from upload_sessions" in statement and "for update" in statement


class ControlledRace:
    """由独立 PostgreSQL 监控连接确认行锁等待后，再放行受控请求。

    顺序按「第几次取得该行锁」判定，不依赖线程身份：TestClient 会把同步端点
    派发到 AnyIO worker 线程，threading.local 在调用线程设置后并不可见。
    监控连接会检查第二个 backend 的 wait_event_type 与 pg_blocking_pids，
    因而 SQLAlchemy 语句入口事件本身不被当作实际阻塞证据。
    """

    def __init__(self, app, predicate, pg_environment, database_name):
        self.app = app
        self.predicate = predicate
        self.pg_environment = pg_environment
        self.database_name = database_name
        self.first_locked = threading.Event()
        self.second_query_entered = threading.Event()
        self.release = threading.Event()
        self.pids = {}
        self.lock_wait = None
        self.monitor_pid = None
        self._locks = 0
        self.armed = False
        engine = app.state.engine
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)

    def close(self):
        engine = self.app.state.engine
        event.remove(engine, "before_cursor_execute", self._before)
        event.remove(engine, "after_cursor_execute", self._after)

    def _matches(self, statement):
        return self.predicate(statement.lower())

    def arm(self):
        self.first_locked.clear()
        self.second_query_entered.clear()
        self.release.clear()
        self.pids.clear()
        self.lock_wait = None
        self.monitor_pid = None
        self._locks = 0
        self.armed = True

    @staticmethod
    def _pid(connection):
        return connection.connection.driver_connection.info.backend_pid

    def _before(self, connection, cursor, statement, parameters, context, executemany):
        # 第一条请求已持锁暂停时，第二条请求到达同一锁 SQL 的执行入口。
        # 是否已进入 PostgreSQL 锁等待由独立监控连接另外确认。
        if self.armed and self._matches(statement) and self._locks == 1:
            self.pids["second"] = self._pid(connection)
            self.second_query_entered.set()

    def _after(self, connection, cursor, statement, parameters, context, executemany):
        if not self.armed or not self._matches(statement):
            return
        self._locks += 1
        if self._locks == 1:
            self.pids["first"] = self._pid(connection)
            self.first_locked.set()
            if not self.release.wait(45):
                raise AssertionError("持锁请求没有等到放行信号")

    def run(self, job):
        with TestClient(self.app) as client:
            return job(client)

    def observe_database_lock_wait(self, timeout_seconds=10):
        """用独立管理员连接观察 second backend 被 first backend 的行锁阻塞。"""
        deadline = time.monotonic() + timeout_seconds
        last_observation = None
        with self.pg_environment.admin(self.database_name) as monitor:
            monitor.execute("SET statement_timeout = 1000")
            self.monitor_pid = monitor.execute("SELECT pg_backend_pid()").fetchone()[0]
            while time.monotonic() < deadline:
                row = monitor.execute(
                    "SELECT activity.wait_event_type, activity.wait_event, "
                    "pg_blocking_pids(activity.pid), pg_backend_pid() "
                    "FROM pg_stat_activity AS activity "
                    "WHERE activity.pid = %s AND activity.datname = current_database()",
                    (self.pids["second"],),
                ).fetchone()
                if row:
                    wait_type, wait_event, blocking_pids, monitor_pid = row
                    self.monitor_pid = monitor_pid
                    last_observation = (wait_type, wait_event, blocking_pids)
                    if wait_type == "Lock" and self.pids["first"] in blocking_pids:
                        self.lock_wait = {
                            "wait_event_type": wait_type,
                            "wait_event": wait_event,
                            "blocking_pids": tuple(blocking_pids),
                        }
                        return
                time.sleep(0.05)
        raise AssertionError(
            "未在有界等待内观察到第二个 backend 被第一个 backend 持有的锁阻塞；"
            f"first={self.pids.get('first')}, second={self.pids.get('second')}, "
            f"monitor={self.monitor_pid}, last={last_observation}"
        )


def run_ordered(race, first_job, second_job, record_property):
    race.arm()
    results = {}

    def first():
        results["first"] = race.run(first_job)

    def second():
        results["second"] = race.run(second_job)

    holder = threading.Thread(target=first, daemon=True)
    holder.start()
    assert race.first_locked.wait(20), "第一条请求没有取得行锁"
    blocked = threading.Thread(target=second, daemon=True)
    blocked.start()
    try:
        assert race.second_query_entered.wait(20), "第二条请求没有到达同一锁 SQL 执行入口"
        race.observe_database_lock_wait(timeout_seconds=10)
    finally:
        race.release.set()
        holder.join(20)
        blocked.join(20)
    assert set(results) == {"first", "second"}
    assert race.pids["first"] != race.pids["second"]
    assert race.monitor_pid not in {race.pids["first"], race.pids["second"]}
    record_property("first_lock_holder_backend_pid", str(race.pids["first"]))
    record_property("second_waiting_backend_pid", str(race.pids["second"]))
    record_property("lock_monitor_backend_pid", str(race.monitor_pid))
    record_property("second_wait_event_type", race.lock_wait["wait_event_type"])
    record_property("second_wait_event", race.lock_wait["wait_event"] or "")
    record_property(
        "second_blocking_backend_pids",
        ",".join(str(pid) for pid in race.lock_wait["blocking_pids"]),
    )
    return results


def counts(app):
    with app.state.sessions() as db:
        return (
            db.execute(text("SELECT count(*) FROM video_assets")).scalar_one(),
            db.execute(text("SELECT count(*) FROM upload_sessions")).scalar_one(),
            db.execute(text("SELECT count(*) FROM idempotency_records WHERE operation = 'upload_intent.create'")).scalar_one(),
        )


def test_intent_first_then_cancel_terminates_upload(pg_databases, seeded_account, pg_environment, record_property):
    database = pg_databases()
    application, engine = _pooled_app(database)
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            base, headers, sid = org["base"], org["ch"], session["id"]

        def create(client):
            return client.post(
                base + f"/training-sessions/{sid}/upload-sessions",
                headers={**headers, "Idempotency-Key": "race-create-first"}, json=intent_payload(),
            )

        def cancel(client):
            return client.patch(
                base + f"/training-sessions/{sid}", headers=headers, json={"status": "cancelled"}
            )

        results = run_ordered(race, create, cancel, record_property)
        assert results["first"].status_code == 201, results["first"].text
        assert results["second"].status_code == 200, results["second"].text
        assert race.pids["first"] != race.pids["second"]

        with application.state.sessions() as db:
            uploads = db.execute(text("SELECT status, failure_reason FROM upload_sessions")).fetchall()
            assets = db.execute(text("SELECT status, failure_reason FROM video_assets")).fetchall()
            assert uploads == [("failed", "session_cancelled")]
            assert assets == [("failed", "session_cancelled")]
            assert db.execute(text(
                "SELECT count(*) FROM training_sessions WHERE status = 'cancelled'"
            )).scalar_one() == 1
            assert db.execute(text(
                "SELECT count(*) FROM video_assets WHERE status = 'pending_upload'"
            )).scalar_one() == 0
            assert db.execute(text(
                "SELECT count(*) FROM upload_sessions WHERE status = 'uploading'"
            )).scalar_one() == 0
    finally:
        race.close()
        engine.dispose()


def test_cancel_first_rejects_intent_without_side_effects(pg_databases, seeded_account, pg_environment, record_property):
    database = pg_databases()
    application, engine = _pooled_app(database)
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            base, headers, sid = org["base"], org["ch"], session["id"]

        def cancel(client):
            return client.patch(
                base + f"/training-sessions/{sid}", headers=headers, json={"status": "cancelled"}
            )

        def create(client):
            return client.post(
                base + f"/training-sessions/{sid}/upload-sessions",
                headers={**headers, "Idempotency-Key": "race-cancel-first"}, json=intent_payload(),
            )

        results = run_ordered(race, cancel, create, record_property)
        assert results["first"].status_code == 200, results["first"].text
        assert results["second"].status_code == 409, results["second"].text
        assert results["second"].json()["detail"]["code"] == "state_conflict"
        assert race.pids["first"] != race.pids["second"]
        assert counts(application) == (0, 0, 0)
    finally:
        race.close()
        engine.dispose()


def test_expiry_first_blocks_abort_from_rewriting_reason(
    pg_databases, seeded_account, pg_environment, record_property
):
    database = pg_databases()
    application, engine = _pooled_app(database)
    race = ControlledRace(application, UPLOAD_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            intent = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "expiry-race-1"}, json=intent_payload(),
            ).json()
            base, headers = org["base"], org["ch"]
            upload_id, asset_id = intent["upload_session"]["id"], intent["asset"]["id"]
            application.state.clock = lambda: datetime.now(UTC) + timedelta(hours=25)

        def read_expired(client):
            return client.get(base + f"/upload-sessions/{upload_id}", headers=headers)

        def abort(client):
            return client.post(base + f"/upload-sessions/{upload_id}/abort", headers=headers)

        results = run_ordered(race, read_expired, abort, record_property)
        assert results["first"].json()["status"] == "expired"
        assert results["second"].status_code == 204
        assert race.pids["first"] != race.pids["second"]

        with application.state.sessions() as db:
            assert db.execute(text(
                "SELECT status || ':' || failure_reason FROM upload_sessions"
            )).scalar_one() == "expired:upload_expired"
            assert db.execute(text(
                "SELECT status || ':' || failure_reason FROM video_assets"
            )).scalar_one() == "failed:upload_expired"
            assert db.execute(text(
                "SELECT count(*) FROM video_assets WHERE status = 'pending_upload'"
            )).scalar_one() == 0
    finally:
        race.close()
        engine.dispose()


def test_abort_before_expiry_remains_terminal_after_clock_advance(pg_databases, seeded_account):
    database = pg_databases()
    application, engine = _pooled_app(database)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            intent = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "expiry-race-2"}, json=intent_payload(),
            ).json()
            base, headers = org["base"], org["ch"]
            upload_id = intent["upload_session"]["id"]
            expires_at = datetime.fromisoformat(intent["upload_session"]["expires_at"].replace("Z", "+00:00"))
            application.state.clock = lambda: expires_at - timedelta(seconds=1)
            abort_response = client.post(base + f"/upload-sessions/{upload_id}/abort", headers=headers)

        assert abort_response.status_code == 204

        with application.state.sessions() as db:
            upload_terminal = db.execute(text(
                "SELECT status, failure_reason, updated_at FROM upload_sessions WHERE id = :id"
            ), {"id": upload_id}).one()
            asset_terminal = db.execute(text(
                "SELECT status, failure_reason, updated_at FROM video_assets WHERE id = :id"
            ), {"id": intent["asset"]["id"]}).one()
        assert upload_terminal.status == "aborted"
        assert upload_terminal.failure_reason == "upload_aborted"
        assert asset_terminal.status == "failed"
        assert asset_terminal.failure_reason == "upload_aborted"

        application.state.clock = lambda: expires_at + timedelta(seconds=1)
        with TestClient(application) as client:
            read_response = client.get(base + f"/upload-sessions/{upload_id}", headers=headers)
        assert read_response.status_code == 200, read_response.text
        assert read_response.json()["status"] == "aborted"
        assert read_response.json()["failure_reason"] == "upload_aborted"

        with application.state.sessions() as db:
            upload_after_read = db.execute(text(
                "SELECT status, failure_reason, updated_at FROM upload_sessions WHERE id = :id"
            ), {"id": upload_id}).one()
            asset_after_read = db.execute(text(
                "SELECT status, failure_reason, updated_at FROM video_assets WHERE id = :id"
            ), {"id": intent["asset"]["id"]}).one()
        assert tuple(upload_after_read) == tuple(upload_terminal)
        assert tuple(asset_after_read) == tuple(asset_terminal)
        assert upload_after_read.status != "expired"
        assert upload_after_read.failure_reason != "upload_expired"
        assert asset_after_read.failure_reason != "upload_expired"
    finally:
        engine.dispose()


@pytest.mark.parametrize("action", ["cancel", "abort", "expiry"])
@pytest.mark.parametrize("first", ["finalize", "action"])
def test_media_finalize_races_preserve_serial_terminal_state(
    pg_databases, seeded_account, pg_environment, record_property, action, first
):
    database = pg_databases()
    application, engine = _pooled_app(database)
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            intent_response = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": f"finalize-race-{action}-{first}"},
                json=intent_payload(),
            )
            assert intent_response.status_code == 201, intent_response.text
            upload_id = intent_response.json()["upload_session"]["id"]
            asset_id = intent_response.json()["asset"]["id"]
            now = datetime.now(UTC)
            deadline = now + timedelta(minutes=5)
            auth_hash = token_hash(org["ch"]["Authorization"].split(" ", 1)[1])
            with application.state.sessions() as db:
                upload = db.get(UploadSession, upload_id)
                upload.status = "completing"
                upload.complete_manifest_hash = "c" * 64
                upload.complete_requested_at = now
                upload.expires_at = deadline
                obj = MediaObject(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, upload_session_id=upload_id, provider_profile="s3",
                    bucket="test-bucket", object_key=f"private/test/{upload_id}/g1",
                    provider_upload_id="test-multipart", object_version="version-1",
                    phase="assembled", generation=1, assembled_at=now,
                    created_at=now, updated_at=now,
                )
                db.add(obj)
                db.flush()
                job = MediaJob(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, object_id=obj.id, kind="complete", state="running",
                    attempts=1, generation=1, lease_token="finalize-race-token",
                    lease_until=now + timedelta(minutes=5), next_attempt_at=now,
                    accepted_actor_kind="user", accepted_user_id=org["coach"]["id"],
                    accepted_auth_session_hash=auth_hash, created_at=now, updated_at=now,
                )
                db.add(job)
                db.commit()
                snapshot = {"id": job.id, "object_id": obj.id, "upload_id": upload_id,
                            "token": job.lease_token, "generation": job.generation,
                            "tenant_id": upload.tenant_id, "site_id": upload.site_id}
                object_snapshot = {"id": obj.id, "key": obj.object_key,
                                   "upload_id": obj.provider_upload_id, "version": obj.object_version,
                                   "generation": obj.generation}

        class HeadOnlyProvider:
            def head_object(self, key, version_id):
                assert key == object_snapshot["key"] and version_id == "version-1"
                return {"version_id": "version-1", "size": 4096}

        provider = HeadOnlyProvider()

        def finalize(_client):
            return _finalize_ready(
                application.state.sessions, provider, snapshot, object_snapshot, "version-1",
                size=4096, sha256=sha256(b"race-media").hexdigest(), media_type="video/mp4",
                now=datetime.now(UTC),
            )

        def run_action(client):
            if action == "cancel":
                return client.patch(
                    org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"],
                    json={"status": "cancelled"},
                )
            if action == "abort":
                return client.post(org["base"] + f"/upload-sessions/{upload_id}/abort", headers=org["ch"])
            return sweep_expired(application.state.sessions, now=deadline + timedelta(seconds=1))

        if first == "finalize":
            results = run_ordered(race, finalize, run_action, record_property)
        else:
            results = run_ordered(race, run_action, finalize, record_property)
        assert race.pids["first"] != race.pids["second"]
        assert race.lock_wait["wait_event_type"] == "Lock"

        with application.state.sessions() as db:
            stored_upload = db.get(UploadSession, upload_id)
            stored_asset = db.get(VideoAsset, asset_id)
            if first == "finalize":
                assert stored_upload.status == "completed"
                assert stored_asset.status == "ready"
                assert stored_asset.storage_object_ref is not None
                if action == "cancel":
                    assert results["second"].status_code == 200
                elif action == "abort":
                    assert results["second"].status_code == 204
                else:
                    assert results["second"] == 0
            else:
                if action == "cancel":
                    assert results["first"].status_code == 200
                    assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "session_cancelled")
                elif action == "abort":
                    assert results["first"].status_code == 204
                    assert (stored_upload.status, stored_upload.failure_reason) == ("aborted", "upload_aborted")
                else:
                    assert results["first"] == 1
                    assert stored_upload.status == "expired"
                    assert stored_upload.failure_reason == "upload_expired"
                assert stored_asset.status == "failed"
                assert stored_asset.storage_object_ref is None
    finally:
        race.close()
        engine.dispose()


def test_concurrent_same_key_complete_accepts_one_durable_job(
    pg_databases, seeded_account, pg_environment, record_property
):
    from dataclasses import replace

    database = pg_databases()
    application, engine = _pooled_app(database)
    application.state.settings = replace(application.state.settings, media_enabled=True)

    class NoIOProvider:
        profile = "s3"
        bucket = "pg-concurrency-test"

    application.state.storage_provider = NoIOProvider()
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            created = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "complete-race-intent"},
                json=intent_payload(),
            )
            assert created.status_code == 201, created.text
            upload_id = created.json()["upload_session"]["id"]
            asset_id = created.json()["asset"]["id"]
            now = datetime.now(UTC)
            with application.state.sessions() as db:
                upload = db.get(UploadSession, upload_id)
                upload.part_size_bytes, upload.part_count = 16 * 1024 * 1024, 1
                obj = MediaObject(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, upload_session_id=upload_id, provider_profile="s3",
                    bucket="pg-concurrency-test", object_key=f"private/test/{upload_id}/g1",
                    provider_upload_id="pg-multipart-1", phase="uploading", generation=1,
                    created_at=now, updated_at=now,
                )
                db.add(obj)
                db.flush()
                db.add(UploadPart(
                    tenant_id=upload.tenant_id, site_id=upload.site_id,
                    session_id=upload.session_id, asset_id=asset_id, upload_session_id=upload_id,
                    part_number=1, expected_size_bytes=4096, state="confirmed", etag='"pg-etag"',
                    actual_size_bytes=4096, confirmed_at=now, created_at=now, updated_at=now,
                ))
                db.commit()

        url = org["base"] + f"/upload-sessions/{upload_id}/complete"
        headers = {**org["ch"], "Idempotency-Key": "complete-race-same-key"}
        body = {"parts": [{"part_number": 1, "etag": '"pg-etag"'}]}
        results = run_ordered(
            race,
            lambda client: client.post(url, headers=headers, json=body),
            lambda client: client.post(url, headers=headers, json=body),
            record_property,
        )
        assert results["first"].status_code == results["second"].status_code == 202
        assert race.pids["first"] != race.pids["second"]
        assert race.lock_wait["wait_event_type"] == "Lock"
        with application.state.sessions() as db:
            upload = db.get(UploadSession, upload_id)
            obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload_id))
            jobs = db.scalars(select(MediaJob).where(
                MediaJob.object_id == obj.id, MediaJob.kind == "complete",
            )).all()
            records = db.scalars(select(IdempotencyRecord).where(
                IdempotencyRecord.operation == "upload.complete",
                IdempotencyRecord.target_id == upload_id,
            )).all()
            assert upload.status == "completing"
            assert len(jobs) == 1
            assert len(records) == 1
        with TestClient(application) as client:
            logged_out = client.post("/api/v1/auth/logout", headers=org["ch"])
        assert logged_out.status_code == 204, logged_out.text
    finally:
        race.close()
        engine.dispose()


def test_concurrent_same_part_confirmation_is_idempotent_on_independent_backends(
    pg_databases, seeded_account, pg_environment, record_property
):
    from dataclasses import replace

    database = pg_databases()
    application, engine = _pooled_app(database)
    application.state.settings = replace(application.state.settings, media_enabled=True)

    class PartProvider:
        profile = "s3"
        bucket = "pg-concurrency-test"

        def list_parts(self, key, upload_id, marker):
            assert key.endswith("/g1") and upload_id == "pg-multipart-2" and marker == 0
            return {"parts": [{"PartNumber": 1, "ETag": '"pg-etag-2"', "Size": 4096}],
                    "truncated": False, "next_marker": None}

    application.state.storage_provider = PartProvider()
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            created = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "confirm-race-intent"},
                json=intent_payload(),
            )
            assert created.status_code == 201, created.text
            upload_id = created.json()["upload_session"]["id"]
            asset_id = created.json()["asset"]["id"]
            now = datetime.now(UTC)
            with application.state.sessions() as db:
                upload = db.get(UploadSession, upload_id)
                upload.part_size_bytes, upload.part_count = 16 * 1024 * 1024, 1
                obj = MediaObject(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, upload_session_id=upload_id, provider_profile="s3",
                    bucket="pg-concurrency-test", object_key=f"private/test/{upload_id}/g1",
                    provider_upload_id="pg-multipart-2", phase="uploading", generation=1,
                    created_at=now, updated_at=now,
                )
                db.add(obj)
                db.add(UploadPart(
                    tenant_id=upload.tenant_id, site_id=upload.site_id,
                    session_id=upload.session_id, asset_id=asset_id, upload_session_id=upload_id,
                    part_number=1, expected_size_bytes=4096, state="registered", created_at=now,
                    updated_at=now,
                ))
                db.commit()

        url = org["base"] + f"/upload-sessions/{upload_id}/parts/1"
        headers = org["ch"]
        body = {"etag": '"pg-etag-2"', "size_bytes": 4096}
        results = run_ordered(
            race,
            lambda client: client.put(url, headers=headers, json=body),
            lambda client: client.put(url, headers=headers, json=body),
            record_property,
        )
        assert results["first"].status_code == results["second"].status_code == 200
        assert race.pids["first"] != race.pids["second"]
        assert race.lock_wait["wait_event_type"] == "Lock"
        assert results["first"].json() == results["second"].json()
        with application.state.sessions() as db:
            part = db.scalar(select(UploadPart).where(UploadPart.upload_session_id == upload_id))
            assert part.state == "confirmed"
            assert part.etag == '"pg-etag-2"' and part.actual_size_bytes == 4096
            assert part.confirmed_at is not None
    finally:
        race.close()
        engine.dispose()


def test_concurrent_part_prepare_reserves_one_media_object_and_job(
    pg_databases, seeded_account, pg_environment, record_property
):
    from dataclasses import replace

    database = pg_databases()
    application, engine = _pooled_app(database)
    application.state.settings = replace(application.state.settings, media_enabled=True)

    class NoIOProvider:
        profile = "s3"
        bucket = "pg-concurrency-test"

    application.state.storage_provider = NoIOProvider()
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            created = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "prepare-race-intent"},
                json=intent_payload(),
            )
            assert created.status_code == 201, created.text
            upload_id = created.json()["upload_session"]["id"]

        url = org["base"] + f"/upload-sessions/{upload_id}/part-urls"
        headers, body = org["ch"], {"part_numbers": [1]}
        results = run_ordered(
            race,
            lambda client: client.post(url, headers=headers, json=body),
            lambda client: client.post(url, headers=headers, json=body),
            record_property,
        )
        assert results["first"].status_code == results["second"].status_code == 202
        assert race.pids["first"] != race.pids["second"]
        assert race.lock_wait["wait_event_type"] == "Lock"
        with application.state.sessions() as db:
            obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload_id))
            jobs = db.scalars(select(MediaJob).where(
                MediaJob.object_id == obj.id, MediaJob.kind == "initialize",
            )).all()
            upload = db.get(UploadSession, upload_id)
            assert obj.phase == "preparing"
            assert len(jobs) == 1
            assert (upload.part_size_bytes, upload.part_count) == (16 * 1024 * 1024, 1)
    finally:
        race.close()
        engine.dispose()


def test_postgresql_expired_worker_lease_takeover_rejects_old_generation(
    pg_databases, seeded_account, record_property
):
    from sqlalchemy.orm import sessionmaker

    database = pg_databases()
    application, engine = _pooled_app(database)
    now = datetime.now(UTC)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            created = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "lease-takeover-intent"},
                json=intent_payload(),
            )
            assert created.status_code == 201, created.text
            upload_id = created.json()["upload_session"]["id"]
            asset_id = created.json()["asset"]["id"]
            with application.state.sessions() as db:
                upload = db.get(UploadSession, upload_id)
                obj = MediaObject(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, upload_session_id=upload_id, provider_profile="s3",
                    bucket="pg-concurrency-test", object_key=f"private/test/{upload_id}/g1",
                    phase="reserved", generation=1, created_at=now, updated_at=now,
                )
                db.add(obj)
                db.flush()
                db.add(MediaJob(
                    tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                    asset_id=asset_id, object_id=obj.id, kind="initialize", state="queued",
                    attempts=0, generation=1, next_attempt_at=now, created_at=now, updated_at=now,
                ))
                db.commit()

        with engine.connect() as first_connection, engine.connect() as second_connection:
            first_pid = first_connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            first_connection.commit()
            second_pid = second_connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            second_connection.commit()
            assert first_pid != second_pid
            first_factory = sessionmaker(first_connection, expire_on_commit=False)
            second_factory = sessionmaker(second_connection, expire_on_commit=False)
            first_snapshot = _claim_job(first_factory, now)
            assert first_snapshot and first_snapshot["generation"] == 2
            with second_factory() as db:
                job = db.get(MediaJob, first_snapshot["id"])
                job.lease_until = now - timedelta(seconds=1)
                db.commit()
            second_snapshot = _claim_job(second_factory, now + timedelta(seconds=1))
            assert second_snapshot and second_snapshot["generation"] == 3
            assert second_snapshot["token"] != first_snapshot["token"]
            with first_factory() as db:
                assert not _job_current(db, first_snapshot)
            with second_factory() as db:
                assert _job_current(db, second_snapshot)
            record_property("lease_takeover_first_backend_pid", str(first_pid))
            record_property("lease_takeover_second_backend_pid", str(second_pid))
            record_property("old_generation_rejected", "true")
    finally:
        engine.dispose()


@pytest.mark.parametrize("first", ["finalize", "cleanup"])
def test_postgresql_cleanup_candidate_cannot_race_ready_finalize(
    pg_databases, seeded_account, pg_environment, record_property, monkeypatch, first
):
    from dataclasses import replace

    database = pg_databases()
    application, engine = _pooled_app(database)
    run_id = pg_environment.run_id
    application.state.settings = replace(
        application.state.settings, media_enabled=True, media_environment="isolated-test",
        media_profile="rustfs-isolated", media_run_id=run_id,
        media_bucket="pg-concurrency-test", media_endpoint_url="http://127.0.0.1:9000",
        media_access_key="test-access", media_secret_key="test-secret",
    )
    monkeypatch.setenv("SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE", "true")

    class NoDeleteProvider:
        profile = "rustfs-isolated"
        bucket = "pg-concurrency-test"

        def list_object_versions(self, prefix, key_marker, version_marker, *, max_keys):
            assert prefix == f"private/test/{run_id}/"
            return {"versions": [], "truncated": False,
                    "key_marker": None, "version_marker": None}

        def head_object(self, key, version_id):
            assert key.endswith("/object") and version_id == "version-1"
            return {"version_id": version_id, "size": 4096}

        def delete_object(self, key, version_id):
            pytest.fail("a queued cleanup candidate must never delete an object that finalizes ready")

    provider = NoDeleteProvider()
    race = ControlledRace(application, SESSION_LOCK, pg_environment, database.name)
    try:
        with TestClient(application) as client:
            org = seed_scope(client, lambda name: seeded_account(name, application=application))
            session = make_session(client, org)
            created = client.post(
                org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
                headers={**org["ch"], "Idempotency-Key": "cleanup-finalize-race-intent"},
                json=intent_payload(),
            )
            assert created.status_code == 201, created.text
            upload_id, asset_id = created.json()["upload_session"]["id"], created.json()["asset"]["id"]

        now = datetime.now(UTC)
        observed_hash = sha256(b"race-media").hexdigest()
        with application.state.sessions() as db:
            upload = db.get(UploadSession, upload_id)
            upload.status = "completing"
            upload.complete_manifest_hash = "b" * 64
            upload.complete_requested_at = now
            upload.expected_sha256 = observed_hash
            obj = MediaObject(
                tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                asset_id=asset_id, upload_session_id=upload_id, provider_profile="rustfs-isolated",
                bucket="pg-concurrency-test", object_key=f"private/test/{run_id}/{upload_id}/object",
                provider_upload_id="pg-multipart-gc-race", object_version="version-1",
                phase="assembled", generation=1, assembled_at=now, created_at=now, updated_at=now,
            )
            db.add(obj)
            db.flush()
            db.add(MediaJob(
                tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
                asset_id=asset_id, object_id=obj.id, kind="complete", state="queued", attempts=0,
                generation=1, next_attempt_at=now, accepted_actor_kind="user",
                accepted_user_id=upload.initiator_user_id,
                accepted_auth_session_hash=token_hash(org["ch"]["Authorization"].removeprefix("Bearer ")),
                created_at=now, updated_at=now,
            ))
            db.add(MediaCleanupCandidate(
                tenant_id=upload.tenant_id, site_id=upload.site_id, object_id=obj.id,
                session_id=upload.session_id, asset_id=asset_id,
                provider_profile="rustfs-isolated", bucket="pg-concurrency-test",
                object_key=obj.object_key, object_version="version-1", kind="object",
                identity_hash=sha256(f"gc-race\0{upload_id}".encode()).hexdigest(),
                first_seen_at=now, last_seen_at=now, not_before=now,
                state="queued", attempts=0, next_attempt_at=now, generation=1,
                created_at=now, updated_at=now,
            ))
            db.commit()

        with application.state.sessions() as db:
            job = db.scalar(select(MediaJob).where(MediaJob.object_id == obj.id, MediaJob.kind == "complete"))
        snapshot = _claim_job(application.state.sessions, now)
        assert snapshot and snapshot["id"] == job.id
        object_snapshot = {
            "id": obj.id, "key": obj.object_key, "upload_id": "pg-multipart-gc-race",
            "version": "version-1", "generation": 1,
        }

        def finalize(_client):
            return _finalize_ready(
                application.state.sessions, provider, snapshot, object_snapshot, "version-1",
                size=4096, sha256=observed_hash, media_type="video/mp4", now=now,
            )

        def cleanup(_client):
            return cleanup_candidates(
                application.state.sessions, provider, application.state.settings,
                execute=True, limit=10, now=now,
            )

        results = (run_ordered(race, finalize, cleanup, record_property) if first == "finalize"
                   else run_ordered(race, cleanup, finalize, record_property))
        assert race.pids["first"] != race.pids["second"]
        assert race.lock_wait["wait_event_type"] == "Lock"
        with application.state.sessions() as db:
            stored_upload = db.get(UploadSession, upload_id)
            stored_asset = db.get(VideoAsset, asset_id)
            stored_object = db.get(MediaObject, obj.id)
            candidate = db.scalar(select(MediaCleanupCandidate).where(
                MediaCleanupCandidate.object_id == obj.id,
            ))
            assert (stored_upload.status, stored_asset.status) == ("completed", "ready")
            assert stored_asset.storage_object_ref == obj.id
            assert stored_object.phase == "verified"
            assert candidate.state == "manual"
            assert candidate.last_error_code in {"active_upload", "retained_asset_reference"}
        cleanup_result = results["first"] if first == "cleanup" else results["second"]
        assert cleanup_result["removed"] == 0
        assert cleanup_result["failed"] == 0
        record_property("gc_finalize_outcome", first)
        record_property("ready_preserved", "true")
    finally:
        race.close()
        engine.dispose()
