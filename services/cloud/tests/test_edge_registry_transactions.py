"""PostgreSQL physical-connection and lifecycle transaction evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import threading
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from pg_support import run_concurrently
from swimplatform.config import Settings
from swimplatform.main import create_app
from swimplatform.models import Device, EdgeCredential, EdgeNode, IdempotencyRecord

pytestmark = pytest.mark.postgresql
_request_operation = ContextVar("edge_registry_request_operation", default=None)


@pytest.fixture
def registry_context(concurrency_app, seeded_account):
    owner, owner_headers = seeded_account("edge-pg-owner", application=concurrency_app)
    with TestClient(concurrency_app) as client:
        tenant_response = client.post("/api/v1/tenants", headers=owner_headers,
                                      json={"name": "Registry", "slug": "edge-pg"})
        assert tenant_response.status_code == 201, tenant_response.text
        tenant = tenant_response.json()
        site_response = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=owner_headers,
                                    json={"name": "Edge Site"})
        assert site_response.status_code == 201, site_response.text
        site = site_response.json()
    return {
        "app": concurrency_app,
        "owner": owner,
        "headers": owner_headers,
        "nodes": f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/edge-nodes",
        "devices": f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/devices",
        "tenant_id": tenant["id"],
        "site_id": site["id"],
    }


@contextmanager
def simultaneous_sql(engine, predicate):
    barrier = threading.Barrier(2)
    backend_pids = []

    def gate(connection, cursor, statement, parameters, context, executemany):
        if predicate(statement.lower()):
            backend_pids.append(connection.connection.driver_connection.info.backend_pid)
            if len(backend_pids) <= 2:
                barrier.wait(timeout=15)

    event.listen(engine, "before_cursor_execute", gate)
    try:
        yield backend_pids
        # Two participants synchronize at the barrier; a third concurrent
        # request may execute the same observed statement without waiting.
        assert len(backend_pids) >= 2 and len(set(backend_pids)) >= 2, backend_pids
    finally:
        event.remove(engine, "before_cursor_execute", gate)


def create_node(context, client, key="node-create-pg-01"):
    return client.post(context["nodes"], headers={**context["headers"], "Idempotency-Key": key},
                       json={"name": "Edge PG"})


def issue(context, client, node_id, key="credential-pg-01"):
    return client.post(f"{context['nodes']}/{node_id}/credentials",
                       headers={**context["headers"], "Idempotency-Key": key}, json={})


def create_scope(app, seeded_account, account_name, slug):
    owner, headers = seeded_account(account_name, application=app)
    with TestClient(app) as client:
        tenant_response = client.post(
            "/api/v1/tenants", headers=headers, json={"name": slug, "slug": slug}
        )
        assert tenant_response.status_code == 201, tenant_response.text
        tenant = tenant_response.json()
        site_response = client.post(
            f"/api/v1/tenants/{tenant['id']}/sites", headers=headers, json={"name": f"{slug} site"}
        )
        assert site_response.status_code == 201, site_response.text
        site = site_response.json()
    prefix = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
    return {
        "app": app,
        "owner": owner,
        "headers": headers,
        "tenant_id": tenant["id"],
        "site_id": site["id"],
        "nodes": prefix + "/edge-nodes",
        "devices": prefix + "/devices",
    }


def ordered_registry_race(app, first_name, first_job, second_name, second_job):
    """Pause after the first Node FOR UPDATE and release only after the second tries it."""
    first_locked = threading.Event()
    second_attempting = threading.Event()
    release_first = threading.Event()
    backend_pids = {}
    engine = app.state.engine

    def node_lock(statement):
        normalized = statement.lower()
        return "from edge_nodes" in normalized and "for update" in normalized

    def record_pid(connection, operation):
        backend_pids[operation] = connection.connection.driver_connection.info.backend_pid

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        operation = _request_operation.get()
        if operation == second_name and node_lock(statement):
            record_pid(connection, operation)
            second_attempting.set()

    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        operation = _request_operation.get()
        if operation == first_name and node_lock(statement):
            record_pid(connection, operation)
            first_locked.set()
            if not release_first.wait(timeout=15):
                raise AssertionError("controlled transaction did not receive release signal")

    def request(operation, job):
        token = _request_operation.set(operation)
        try:
            with TestClient(app) as client:
                return job(client)
        finally:
            _request_operation.reset(token)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    started = monotonic()
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        first = executor.submit(request, first_name, first_job)
        assert first_locked.wait(timeout=15), "first request did not acquire the Node row lock"
        second = executor.submit(request, second_name, second_job)
        assert second_attempting.wait(timeout=15), "second request did not reach the Node row-lock query"
        assert backend_pids[first_name] != backend_pids[second_name], backend_pids
        release_first.set()
        responses = {
            first_name: first.result(timeout=30),
            second_name: second.result(timeout=30),
        }
    finally:
        release_first.set()
        executor.shutdown(wait=True, cancel_futures=True)
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine, "after_cursor_execute", after_cursor_execute)
    return responses, backend_pids, monotonic() - started


def test_concurrent_node_create_same_key_commits_one_resource(registry_context):
    context = registry_context
    with simultaneous_sql(context["app"].state.engine,
                          lambda statement: statement.lstrip().startswith("insert into edge_nodes")) as pids:
        responses = run_concurrently(
            context["app"],
            [lambda client: create_node(context, client, "node-concurrent-01")] * 2,
        )
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with context["app"].state.sessions() as db:
        assert len(db.scalars(select(EdgeNode)).all()) == 1
        assert len(db.scalars(select(IdempotencyRecord)).all()) == 1
    assert len(set(pids)) == 2


def test_concurrent_device_create_same_key_serializes_on_node_and_replays(registry_context):
    context = registry_context
    with TestClient(context["app"]) as client:
        node = create_node(context, client).json()
        assert client.patch(f"{context['nodes']}/{node['id']}", headers=context["headers"],
                            json={"status": "active"}).status_code == 200
    with simultaneous_sql(context["app"].state.engine,
                          lambda statement: "from edge_nodes" in statement and "for update" in statement) as pids:
        responses = run_concurrently(context["app"], [
            lambda client: client.post(
                context["devices"], headers={**context["headers"], "Idempotency-Key": "device-concurrent-01"},
                json={"name": "Mobile camera", "kind": "camera", "edge_node_id": node["id"]},
            )
        ] * 2)
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with context["app"].state.sessions() as db:
        assert len(db.scalars(select(Device)).all()) == 1
        assert len(db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.operation == "device.create")).all()) == 1
    assert len(set(pids)) == 2


def test_concurrent_credential_issue_returns_secret_once(registry_context):
    context = registry_context
    with TestClient(context["app"]) as client:
        node = create_node(context, client).json()
    with simultaneous_sql(context["app"].state.engine,
                          lambda statement: "from edge_nodes" in statement and "for update" in statement) as pids:
        responses = run_concurrently(context["app"], [
            lambda client: issue(context, client, node["id"], "credential-concurrent-01")
        ] * 2)
    assert sorted(response.status_code for response in responses) == [201, 409]
    successful = next(response for response in responses if response.status_code == 201)
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["detail"]["code"] == "credential_secret_not_replayable"
    assert rejected.json()["detail"]["credential_id"] == successful.json()["id"]
    with context["app"].state.sessions() as db:
        credentials = db.scalars(select(EdgeCredential)).all()
        records = db.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.operation == "edge_credential.issue"
        )).all()
        assert len(credentials) == len(records) == 1
        assert successful.json()["token"] not in credentials[0].token_hash
        assert successful.json()["token"] not in records[0].request_hash
    assert len(set(pids)) == 2


def test_foreign_manager_node_requests_do_not_wait_on_or_mutate_foreign_scope(
    registry_context, seeded_account, pg_environment, concurrency_database, record_property
):
    """A locked foreign Node must be invisible to scoped manager lock queries."""
    context = registry_context
    app = context["app"]
    pool_size = app.state.engine.pool.size()
    assert pool_size >= 8
    record_property("application_pool_size", str(pool_size))
    foreign = create_scope(app, seeded_account, "edge-pg-foreign-owner", "edge-pg-foreign")
    with TestClient(app) as client:
        node_response = create_node(foreign, client, key="foreign-node-create-01")
        assert node_response.status_code == 201, node_response.text
        node = node_response.json()
        credential_response = issue(
            foreign, client, node["id"], key="foreign-credential-create-01"
        )
        assert credential_response.status_code == 201, credential_response.text
        credential = credential_response.json()
        assert client.patch(
            f"{foreign['nodes']}/{node['id']}", headers=foreign["headers"], json={"status": "active"}
        ).status_code == 200

    foreign_node_path = f"{context['nodes']}/{node['id']}"
    foreign_credential_path = f"{foreign_node_path}/credentials/{credential['id']}"
    with app.state.sessions() as db:
        before_node = db.get(EdgeNode, node["id"])
        before_node = tuple(getattr(before_node, column.key) for column in EdgeNode.__table__.columns)
        before_credentials = [
            tuple(getattr(row, column.key) for column in EdgeCredential.__table__.columns)
            for row in db.scalars(
                select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"])
                .order_by(EdgeCredential.id)
            ).all()
        ]
        before_records = [
            tuple(getattr(row, column.key) for column in IdempotencyRecord.__table__.columns)
            for row in db.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.site_id == foreign["site_id"])
                .order_by(IdempotencyRecord.id)
            ).all()
        ]
    requests = {
        "node_patch": lambda client: client.patch(
            foreign_node_path, headers=context["headers"], json={"name": "cross-tenant-write"}
        ),
        "credential_issue": lambda client: client.post(
            f"{foreign_node_path}/credentials",
            headers={**context["headers"], "Idempotency-Key": "cross-issue-key-01"},
            json={},
        ),
        "credential_revoke": lambda client: client.delete(
            foreign_credential_path, headers=context["headers"]
        ),
    }
    request_pids = {}

    def remember_manager_lock(connection, cursor, statement, parameters, execution_context, executemany):
        label = _request_operation.get()
        normalized = statement.lower()
        if label in requests and "from edge_nodes" in normalized and "for update" in normalized:
            request_pids[label] = connection.connection.driver_connection.info.backend_pid

    for label, job in requests.items():
        requests[label] = (
            lambda client, label=label, job=job: _run_marked_request(label, job, client)
        )

    engine = app.state.engine
    event.listen(engine, "before_cursor_execute", remember_manager_lock)
    try:
        with pg_environment.admin(concurrency_database.name, search_path="swim_cloud") as locker:
            with locker.transaction():
                locker_pid = locker.execute("SELECT pg_backend_pid()").fetchone()[0]
                locked = locker.execute(
                    "SELECT id FROM edge_nodes WHERE id = %s FOR UPDATE", (node["id"],)
                ).fetchone()
                assert locked == (node["id"],)

                # All three responses must complete while this independent transaction still
                # owns the foreign row lock. A global-id FOR UPDATE would block here.
                responses = run_concurrently(
                    app, list(requests.values()), timeout=8.0
                )
                assert [response.status_code for response in responses] == [404, 404, 404]
                assert set(request_pids) == set(requests), request_pids
                assert all(pid != locker_pid for pid in request_pids.values())
                record_property("foreign_row_lock_backend_pid", str(locker_pid))
                for operation, backend_pid in sorted(request_pids.items()):
                    record_property(f"{operation}_backend_pid", str(backend_pid))
                assert all(
                    response.json()["detail"]["code"] == "edge_node_not_found"
                    for response in responses
                )
    finally:
        event.remove(engine, "before_cursor_execute", remember_manager_lock)

    with app.state.sessions() as db:
        saved_node = db.get(EdgeNode, node["id"])
        after_node = tuple(getattr(saved_node, column.key) for column in EdgeNode.__table__.columns)
        after_credentials = [
            tuple(getattr(row, column.key) for column in EdgeCredential.__table__.columns)
            for row in db.scalars(
                select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"])
                .order_by(EdgeCredential.id)
            ).all()
        ]
        after_records = [
            tuple(getattr(row, column.key) for column in IdempotencyRecord.__table__.columns)
            for row in db.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.site_id == foreign["site_id"])
                .order_by(IdempotencyRecord.id)
            ).all()
        ]
        assert after_node == before_node
        assert after_credentials == before_credentials
        assert after_records == before_records


def _run_marked_request(operation, job, client):
    token = _request_operation.set(operation)
    try:
        return job(client)
    finally:
        _request_operation.reset(token)


def test_manual_credential_revoke_and_heartbeat_have_both_serial_orders(
    registry_context, seeded_account, record_property
):
    context = create_scope(
        registry_context["app"], seeded_account, "edge-pg-revoke-owner", "edge-pg-revoke"
    )
    app = context["app"]
    pool_size = app.state.engine.pool.size()
    assert pool_size >= 8
    record_property("application_pool_size", str(pool_size))
    manager_admin, manager_admin_headers = seeded_account(
        "edge-pg-revoke-admin", application=app
    )
    with TestClient(app) as client:
        assert client.post(
            f"/api/v1/tenants/{context['tenant_id']}/members",
            headers=context["headers"],
            json={"user_id": manager_admin["id"], "role": "admin"},
        ).status_code == 201
        node_response = create_node(context, client, key="revoke-race-node-001")
        assert node_response.status_code == 201, node_response.text
        node = node_response.json()
        first_credential_response = issue(
            context, client, node["id"], key="revoke-race-credential-01"
        )
        assert first_credential_response.status_code == 201, first_credential_response.text
        first_credential = first_credential_response.json()
        assert client.patch(
            f"{context['nodes']}/{node['id']}", headers=context["headers"], json={"status": "active"}
        ).status_code == 200

    heartbeat_time = datetime.now(UTC) + timedelta(seconds=30)
    app.state.clock = lambda: heartbeat_time
    first_path = (
        f"{context['nodes']}/{node['id']}/credentials/{first_credential['id']}"
    )
    first_heartbeat = lambda client: client.post(
        "/api/v1/edge/heartbeat",
        headers={"Authorization": f"Bearer {first_credential['token']}"},
        json={},
    )
    first_revoke = lambda client: client.delete(first_path, headers=manager_admin_headers)
    first_results, first_pids, _ = ordered_registry_race(
        app, "heartbeat", first_heartbeat, "revoke", first_revoke
    )
    assert first_results["heartbeat"].status_code == 200, first_results["heartbeat"].text
    assert first_results["revoke"].status_code == 204, first_results["revoke"].text
    assert first_pids["heartbeat"] != first_pids["revoke"]
    record_property("heartbeat_first_backend_pid", str(first_pids["heartbeat"]))
    record_property("revoke_after_heartbeat_backend_pid", str(first_pids["revoke"]))
    assert datetime.fromisoformat(
        first_results["heartbeat"].json()["last_seen_at"].replace("Z", "+00:00")
    ).astimezone(UTC) == heartbeat_time
    with app.state.sessions() as db:
        saved_node = db.get(EdgeNode, node["id"])
        saved_credential = db.get(EdgeCredential, first_credential["id"])
        assert saved_node.last_seen_at.astimezone(UTC) == heartbeat_time
        assert saved_credential.revoked_at.astimezone(UTC) == heartbeat_time
        assert saved_credential.revoked_by_user_id == manager_admin["id"]

    # A second credential exercises revoke-first: heartbeat reaches the same Node lock
    # while revoke owns it, then must observe the committed revocation after acquiring it.
    with TestClient(app) as client:
        second_credential_response = issue(
            context, client, node["id"], key="revoke-race-credential-02"
        )
        assert second_credential_response.status_code == 201, second_credential_response.text
        second_credential = second_credential_response.json()
    baseline_last_seen = heartbeat_time
    revoke_time = heartbeat_time + timedelta(seconds=10)
    app.state.clock = lambda: revoke_time
    second_path = (
        f"{context['nodes']}/{node['id']}/credentials/{second_credential['id']}"
    )
    second_revoke = lambda client: client.delete(second_path, headers=manager_admin_headers)
    second_heartbeat = lambda client: client.post(
        "/api/v1/edge/heartbeat",
        headers={"Authorization": f"Bearer {second_credential['token']}"},
        json={},
    )
    second_results, second_pids, _ = ordered_registry_race(
        app, "revoke", second_revoke, "heartbeat", second_heartbeat
    )
    assert second_results["revoke"].status_code == 204, second_results["revoke"].text
    assert second_results["heartbeat"].status_code == 401, second_results["heartbeat"].text
    assert second_pids["revoke"] != second_pids["heartbeat"]
    record_property("revoke_first_backend_pid", str(second_pids["revoke"]))
    record_property("heartbeat_after_revoke_backend_pid", str(second_pids["heartbeat"]))
    with app.state.sessions() as db:
        saved_node = db.get(EdgeNode, node["id"])
        saved_credential = db.get(EdgeCredential, second_credential["id"])
        assert saved_node.last_seen_at.astimezone(UTC) == baseline_last_seen
        assert saved_credential.revoked_at.astimezone(UTC) == revoke_time
        assert saved_credential.revoked_by_user_id == manager_admin["id"]

    # A repeated delete from a different valid manager is idempotent and keeps first audit data.
    app.state.clock = lambda: revoke_time + timedelta(seconds=10)
    with TestClient(app) as client:
        repeated = client.delete(second_path, headers=context["headers"])
    assert repeated.status_code == 204, repeated.text
    with app.state.sessions() as db:
        saved_credential = db.get(EdgeCredential, second_credential["id"])
        assert saved_credential.revoked_at.astimezone(UTC) == revoke_time
        assert saved_credential.revoked_by_user_id == manager_admin["id"]


def test_disable_issue_and_heartbeat_race_has_serializable_lifecycle(registry_context):
    context = registry_context
    with TestClient(context["app"]) as client:
        node = create_node(context, client).json()
        first = issue(context, client, node["id"], "credential-before-01").json()
        assert client.patch(f"{context['nodes']}/{node['id']}", headers=context["headers"],
                            json={"status": "active"}).status_code == 200

    def disable(client):
        return client.patch(f"{context['nodes']}/{node['id']}", headers=context["headers"],
                            json={"status": "disabled"})

    def issue_after_lock(client):
        return issue(context, client, node["id"], "credential-race-0001")

    def heartbeat(client):
        return client.post("/api/v1/edge/heartbeat", headers={"Authorization": f"Bearer {first['token']}"}, json={})

    with simultaneous_sql(context["app"].state.engine,
                          lambda statement: "from edge_nodes" in statement and "for update" in statement) as pids:
        responses = run_concurrently(context["app"], [disable, issue_after_lock, heartbeat])
    # The disable always commits; issue is allowed on a disabled node for controlled recovery,
    # while heartbeat may linearize before the disable and then gets invalidated by it.
    assert any(response.status_code == 200 and response.json()["status"] == "disabled" for response in responses)
    assert any(response.status_code == 201 for response in responses)
    assert all(response.status_code in (200, 201, 401) for response in responses)
    with context["app"].state.sessions() as db:
        current = db.get(EdgeNode, node["id"])
        credentials = db.scalars(select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"])).all()
        assert current.status == "disabled"
        assert current.credential_generation == 1
        assert all(c.revoked_at is not None or c.generation == current.credential_generation for c in credentials)
    # Any credential issued before or during disable is unusable while the node is disabled.
    for credential in credentials:
        token = first["token"] if credential.id == first["id"] else None
        if token:
            with TestClient(context["app"]) as client:
                assert client.post("/api/v1/edge/heartbeat",
                                   headers={"Authorization": f"Bearer {token}"}, json={}).status_code == 401
    assert len(set(pids)) >= 2


def test_disable_transaction_rolls_back_node_and_credential_when_revoke_fails(registry_context, pg_environment,
                                                                                concurrency_database):
    context = registry_context
    with TestClient(context["app"]) as client:
        node = create_node(context, client).json()
        credential = issue(context, client, node["id"], "credential-rollback-01").json()
        assert client.patch(f"{context['nodes']}/{node['id']}", headers=context["headers"],
                            json={"status": "active"}).status_code == 200

    with pg_environment.admin(concurrency_database.name) as admin:
        admin.execute("""
            CREATE FUNCTION swim_cloud.reject_credential_revoke() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'controlled revoke failure';
              END IF;
              RETURN NEW;
            END;
            $$
        """)
        admin.execute("""
            CREATE TRIGGER reject_credential_revoke BEFORE UPDATE ON swim_cloud.edge_credentials
            FOR EACH ROW EXECUTE FUNCTION swim_cloud.reject_credential_revoke()
        """)

    with TestClient(context["app"], raise_server_exceptions=False) as client:
        response = client.patch(f"{context['nodes']}/{node['id']}", headers=context["headers"],
                                json={"status": "disabled"})
        assert response.status_code == 500

    with context["app"].state.sessions() as db:
        current = db.get(EdgeNode, node["id"])
        saved = db.get(EdgeCredential, credential["id"])
        assert current.status == "active" and current.credential_generation == 0
        assert saved.revoked_at is None and saved.revoked_by_user_id is None
    with pg_environment.admin(concurrency_database.name) as admin:
        admin.execute("DROP TRIGGER reject_credential_revoke ON swim_cloud.edge_credentials")
        admin.execute("DROP FUNCTION swim_cloud.reject_credential_revoke()")


@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai"])
def test_edge_credential_expiry_is_absolute_utc_in_each_database_timezone(zone, pg_databases, seeded_account):
    """PostgreSQL session timezone must not shift the credential's expiry instant."""
    from datetime import UTC, datetime, timedelta

    database = pg_databases(timezone=zone)
    application = create_app(Settings(database_url=database.app_url))
    zone_key = zone.lower().replace("/", "-")
    try:
        _owner, headers = seeded_account(f"edge-zone-{zone}", application=application)
        deadline = datetime(2030, 6, 1, tzinfo=UTC)
        application.state.clock = lambda: deadline - timedelta(days=7)
        with TestClient(application) as client:
            tenant_response = client.post("/api/v1/tenants", headers=headers,
                                          json={"name": "Timezone", "slug": f"edge-zone-{zone_key}"})
            assert tenant_response.status_code == 201, tenant_response.text
            tenant = tenant_response.json()
            site_response = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=headers,
                                        json={"name": "Timezone Site"})
            assert site_response.status_code == 201, site_response.text
            site = site_response.json()
            prefix = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
            node_response = client.post(f"{prefix}/edge-nodes", headers={**headers, "Idempotency-Key": f"node-zone-{zone_key}"},
                                        json={"name": "Timezone Node"})
            assert node_response.status_code == 201, node_response.text
            node = node_response.json()
            credential_response = client.post(
                f"{prefix}/edge-nodes/{node['id']}/credentials",
                headers={**headers, "Idempotency-Key": f"credential-zone-{zone_key}"},
                json={"expires_at": deadline.isoformat()},
            )
            assert credential_response.status_code == 201, credential_response.text
            credential = credential_response.json()
            assert datetime.fromisoformat(credential["expires_at"]).astimezone(UTC) == deadline
            assert client.patch(f"{prefix}/edge-nodes/{node['id']}", headers=headers,
                                json={"status": "active"}).status_code == 200
            heartbeat_headers = {"Authorization": f"Bearer {credential['token']}"}
            application.state.clock = lambda: deadline - timedelta(microseconds=1)
            before = client.post("/api/v1/edge/heartbeat", headers=heartbeat_headers, json={})
            assert before.status_code == 200, before.text
            application.state.clock = lambda: deadline
            exact = client.post("/api/v1/edge/heartbeat", headers=heartbeat_headers, json={})
            assert exact.status_code == 401, exact.text
            application.state.clock = lambda: deadline + timedelta(microseconds=1)
            after = client.post("/api/v1/edge/heartbeat", headers=heartbeat_headers, json={})
            assert after.status_code == 401, after.text
    finally:
        application.state.engine.dispose()
