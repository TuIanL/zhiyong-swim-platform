"""PostgreSQL physical-connection and lifecycle transaction evidence."""
from contextlib import contextmanager
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from pg_support import run_concurrently
from swimplatform.models import Device, EdgeCredential, EdgeNode, IdempotencyRecord

pytestmark = pytest.mark.postgresql


@pytest.fixture
def registry_context(concurrency_app, seeded_account):
    owner, owner_headers = seeded_account("edge-pg-owner")
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
        assert len(backend_pids) == 2 and len(set(backend_pids)) == 2, backend_pids
    finally:
        event.remove(engine, "before_cursor_execute", gate)


def create_node(context, client, key="node-create-pg-01"):
    return client.post(context["nodes"], headers={**context["headers"], "Idempotency-Key": key},
                       json={"name": "Edge PG"})


def issue(context, client, node_id, key="credential-pg-01"):
    return client.post(f"{context['nodes']}/{node_id}/credentials",
                       headers={**context["headers"], "Idempotency-Key": key}, json={})


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
