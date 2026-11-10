"""Cloud Edge Registry HTTP contract, authorization and lifecycle tests."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swimplatform.config import Settings
from swimplatform.main import create_app
from swimplatform.models import Device, EdgeCredential, EdgeNode, IdempotencyRecord


@pytest.fixture
def registry_world(client, seeded_account):
    accounts = {name: seeded_account(name) for name in ("owner", "admin", "coach", "athlete", "outsider")}
    owner, owner_headers = accounts["owner"]
    tenant = client.post("/api/v1/tenants", headers=owner_headers, json={"name": "Registry", "slug": "registry"}).json()
    for name, role in (("admin", "admin"), ("coach", "coach"), ("athlete", "athlete")):
        response = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=owner_headers,
            json={"user_id": accounts[name][0]["id"], "role": role},
        )
        assert response.status_code == 201, response.text
    site = client.post(
        f"/api/v1/tenants/{tenant['id']}/sites", headers=owner_headers, json={"name": "Registry Site"}
    ).json()
    prefix = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
    return {
        "accounts": accounts,
        "tenant": tenant,
        "site": site,
        "prefix": prefix,
        "nodes": prefix + "/edge-nodes",
        "devices": prefix + "/devices",
    }


def create_node(client, world, headers=None, *, key="node-key-0001", name="edge-one"):
    return client.post(
        world["nodes"], headers={**(headers or world["accounts"]["owner"][1]), "Idempotency-Key": key},
        json={"name": name},
    )


def issue_credential(client, world, node_id, headers=None, *, key="credential-key-01", body=None):
    return client.post(
        f"{world['nodes']}/{node_id}/credentials",
        headers={**(headers or world["accounts"]["owner"][1]), "Idempotency-Key": key},
        json=body or {},
    )


def test_registry_operations_camera_first_and_manager_boundary(client, registry_world):
    world = registry_world
    owner = world["accounts"]["owner"][1]
    node_response = create_node(client, world)
    assert node_response.status_code == 201, node_response.text
    node = node_response.json()
    assert node["status"] == "pending" and node["online"] is False

    node_path = f"{world['nodes']}/{node['id']}"
    for name, expected in (("owner", 200), ("admin", 200), ("coach", 403), ("athlete", 403),
                           ("outsider", 404)):
        headers = world["accounts"][name][1]
        assert client.get(world["nodes"], headers=headers).status_code == expected
        assert client.get(node_path, headers=headers).status_code == expected
    assert client.get(world["nodes"]).status_code == 401
    assert client.post(world["nodes"], headers={"Idempotency-Key": "node-key-0002"},
                       json={"name": "anonymous"}).status_code == 401

    assert client.patch(node_path, headers=owner, json={}).status_code == 422
    assert client.patch(node_path, headers=owner, json={"tenant_id": world["tenant"]["id"]}).status_code == 422
    assert client.patch(node_path, headers=owner, json={"name": "   "}).status_code == 422
    assert client.patch(node_path, headers=owner, json={"status": "unknown"}).status_code == 422
    assert client.patch(node_path, headers=owner, json={"status": "active"}).status_code == 200
    active_timestamp = client.get(node_path, headers=owner).json()["updated_at"]
    assert client.patch(node_path, headers=owner, json={"status": "active"}).status_code == 200
    assert client.get(node_path, headers=owner).json()["updated_at"] == active_timestamp
    assert client.patch(node_path, headers=owner, json={"status": "pending"}).status_code == 409

    create_device_url = world["devices"]
    for kind in ("cart", "microphone", "CAMERA"):
        response = client.post(create_device_url, headers={**owner, "Idempotency-Key": f"device-key-{kind}"},
                               json={"name": "unsupported", "kind": kind, "edge_node_id": node["id"]})
        assert response.status_code == 422, response.text
    cameras = []
    for _ in range(2):
        response = client.post(
            create_device_url,
            headers={**owner, "Idempotency-Key": f"device-key-{len(cameras)}-01"},
            json={"name": "随车摄像头", "kind": "camera", "edge_node_id": node["id"], "hardware_serial": "same-serial"},
        )
        assert response.status_code == 201, response.text
        cameras.append(response.json())
    assert cameras[0]["id"] != cameras[1]["id"]
    assert cameras[0]["kind"] == "camera"
    assert client.get(world["devices"], headers=owner, params={"edge_node_id": node["id"]}).json() == cameras
    assert client.get(world["devices"], headers=owner, params={"status": "disabled"}).json() == []

    device_path = f"{world['devices']}/{cameras[0]['id']}"
    assert client.patch(device_path, headers=owner, json={}).status_code == 422
    assert client.patch(device_path, headers=owner, json={"edge_node_id": node["id"]}).status_code == 422
    assert client.patch(device_path, headers=owner, json={"status": "disabled"}).status_code == 200
    assert client.patch(device_path, headers=owner, json={"status": "active"}).status_code == 200
    active_device_timestamp = client.get(device_path, headers=owner).json()["updated_at"]
    assert client.patch(device_path, headers=owner, json={"status": "active"}).status_code == 200
    assert client.get(device_path, headers=owner).json()["updated_at"] == active_device_timestamp
    assert client.get(f"{world['devices']}/{world['site']['id']}", headers=owner).status_code == 404
    assert client.delete(node_path, headers=owner).status_code == 405


def test_idempotency_replays_after_restart_and_rechecks_authorization(client, registry_world, app):
    world = registry_world
    owner = world["accounts"]["owner"][1]
    first = create_node(client, world, key="node-retry-0001", name="retry")
    replay = create_node(client, world, key="node-retry-0001", name="retry")
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    changed = create_node(client, world, key="node-retry-0001", name="different")
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "idempotency_conflict"
    assert client.post(world["nodes"], headers={**owner, "Idempotency-Key": "short"}, json={"name": "x"}).status_code == 422

    node_id = first.json()["id"]
    assert client.patch(f"{world['nodes']}/{node_id}", headers=owner, json={"status": "active"}).status_code == 200
    device_body = {"name": "camera", "edge_node_id": node_id, "kind": "camera"}
    device_first = client.post(world["devices"], headers={**owner, "Idempotency-Key": "device-retry-0001"}, json=device_body)
    device_again = client.post(world["devices"], headers={**owner, "Idempotency-Key": "device-retry-0001"}, json=device_body)
    assert device_first.status_code == device_again.status_code == 201
    assert device_first.json()["id"] == device_again.json()["id"]

    url = str(app.state.engine.url)
    app.state.engine.dispose()
    restarted = create_app(Settings(database_url=url))
    try:
        from fastapi.testclient import TestClient
        with TestClient(restarted) as restarted_client:
            again = create_node(restarted_client, world, key="node-retry-0001", name="retry")
            assert again.status_code == 201
            assert again.json()["id"] == first.json()["id"]
            # Current role is checked before a persisted replay is returned.
            assert restarted_client.patch(
                f"/api/v1/tenants/{world['tenant']['id']}/members/{world['accounts']['admin'][0]['id']}",
                headers=owner, json={"role": "coach"},
            ).status_code == 200
            admin_replay = create_node(
                restarted_client, world, world["accounts"]["admin"][1],
                key="node-admin-0001", name="admin",
            )
            assert admin_replay.status_code == 403
    finally:
        restarted.state.engine.dispose()


def test_credential_once_header_identity_and_lifecycle_audit(client, registry_world, app, caplog):
    world = registry_world
    owner = world["accounts"]["owner"][1]
    node = create_node(client, world).json()
    issued_response = issue_credential(client, world, node["id"])
    assert issued_response.status_code == 201, issued_response.text
    issued = issued_response.json()
    assert issued["token"].startswith("swim_edge_")
    assert datetime.fromisoformat(issued["expires_at"]) - datetime.fromisoformat(issued["issued_at"]) == timedelta(days=7)
    assert issued["issued_by_user_id"] == world["accounts"]["owner"][0]["id"]
    assert "token_hash" not in issued and "secret" not in issued

    replay = issue_credential(client, world, node["id"])
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "credential_secret_not_replayable"
    assert replay.json()["detail"]["credential_id"] == issued["id"]

    rows = client.get(f"{world['nodes']}/{node['id']}/credentials", headers=owner)
    assert rows.status_code == 200 and len(rows.json()) == 1
    assert "token" not in rows.text and "token_hash" not in rows.text
    with app.state.sessions() as db:
        credential = db.get(EdgeCredential, issued["id"])
        record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.resource_id == issued["id"]))
        assert credential.token_hash != issued["token"]
        assert record.key_hash != "credential-key-01"
        assert record.request_hash and issued["token"] not in record.request_hash
    assert issued["token"] not in caplog.text

    heartbeat_path = "/api/v1/edge/heartbeat"
    assert client.post(heartbeat_path, headers=owner, json={}).status_code == 401
    assert client.get(world["nodes"], headers={"Authorization": f"Bearer {issued['token']}"}).status_code == 401
    assert client.post(heartbeat_path, headers={"Authorization": f"Bearer {issued['token']}"}, json={}).status_code == 401

    app.state.clock = lambda: datetime.fromisoformat(issued["issued_at"]).replace(tzinfo=UTC) + timedelta(seconds=10)
    assert client.patch(f"{world['nodes']}/{node['id']}", headers=owner, json={"status": "active"}).status_code == 200
    beat = client.post(heartbeat_path, headers={"Authorization": f"Bearer {issued['token']}"}, json={
        "reported_config_revision": 999,
        "observed_at_raw": "local-clock-not-authoritative",
        "health": {"software_version": "0.2.0", "status": "degraded"},
    })
    assert beat.status_code == 200, beat.text
    assert beat.json()["heartbeat_interval_seconds"] == 30
    assert beat.json()["online_window_seconds"] == 90
    assert beat.json()["online"] is True
    node_read = client.get(f"{world['nodes']}/{node['id']}", headers=owner).json()
    assert node_read["applied_config_revision"] == 999
    assert node_read["config_revision"] == 1
    assert node_read["software_version"] == "0.2.0" and node_read["health_status"] == "degraded"
    assert client.post(heartbeat_path, headers={"Authorization": f"Bearer {issued['token']}"},
                       json={"last_seen_at": "2030-01-01T00:00:00Z"}).status_code == 422
    assert client.post(heartbeat_path, headers={"Authorization": f"Bearer {issued['token']}"},
                       json={"health": {"status": "ok", "extra": "no"}}).status_code == 422

    credential_path = f"{world['nodes']}/{node['id']}/credentials/{issued['id']}"
    admin_headers = world["accounts"]["admin"][1]
    assert client.delete(credential_path, headers=admin_headers).status_code == 204
    assert client.delete(credential_path, headers=owner).status_code == 204
    with app.state.sessions() as db:
        revoked = db.get(EdgeCredential, issued["id"])
        assert revoked.revoked_by_user_id == world["accounts"]["admin"][0]["id"]
        assert revoked.revoked_at is not None
    assert client.post(heartbeat_path, headers={"Authorization": f"Bearer {issued['token']}"},
                       json={}).status_code == 401


def test_deadlines_online_boundary_and_atomic_disable_restore(client, registry_world, app):
    world = registry_world
    owner = world["accounts"]["owner"][1]
    now = datetime(2030, 1, 1, tzinfo=UTC)
    app.state.clock = lambda: now
    node = create_node(client, world).json()
    thirty_day = issue_credential(
        client, world, node["id"], key="credential-30days", body={"expires_at": (now + timedelta(days=30)).isoformat()}
    )
    assert thirty_day.status_code == 201, thirty_day.text
    over_limit = issue_credential(
        client, world, node["id"], key="credential-over-limit",
        body={"expires_at": (now + timedelta(days=30, seconds=1)).isoformat()},
    )
    assert over_limit.status_code == 422
    naive = issue_credential(
        client, world, node["id"], key="credential-naive", body={"expires_at": "2030-01-02T00:00:00"},
    )
    assert naive.status_code == 422

    token = thirty_day.json()["token"]
    node_path = f"{world['nodes']}/{node['id']}"
    assert client.patch(node_path, headers=owner, json={"status": "active"}).status_code == 200
    response = client.post("/api/v1/edge/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})
    assert response.status_code == 200
    assert client.get(node_path, headers=owner).json()["online"] is True

    app.state.clock = lambda: now + timedelta(seconds=89, milliseconds=999)
    assert client.get(node_path, headers=owner).json()["online"] is True
    app.state.clock = lambda: now + timedelta(seconds=90)
    assert client.get(node_path, headers=owner).json()["online"] is False

    app.state.clock = lambda: now + timedelta(days=35)
    expired = client.post("/api/v1/edge/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={})
    assert expired.status_code == 401
    assert client.get(node_path, headers=owner).json()["status"] == "active"
    # A disabled node remains disabled until a new generation is issued and explicitly activated.
    assert client.patch(node_path, headers=owner, json={"status": "disabled"}).status_code == 200
    with app.state.sessions() as db:
        old = db.scalar(select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"]))
        assert old.revoked_at is not None and old.revoked_by_user_id == world["accounts"]["owner"][0]["id"]
        old_generation = db.get(EdgeNode, node["id"]).credential_generation
        old_revoked_at = old.revoked_at
    assert client.patch(node_path, headers=owner, json={"status": "disabled"}).status_code == 200
    with app.state.sessions() as db:
        still_disabled = db.get(EdgeNode, node["id"])
        still_revoked = db.scalar(select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"]))
        assert still_disabled.credential_generation == old_generation
        assert still_revoked.revoked_at == old_revoked_at
    assert client.post("/api/v1/edge/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={}).status_code == 401
    assert client.patch(node_path, headers=owner, json={"status": "active"}).status_code == 409
    new_key = "credential-new-generation"
    new = issue_credential(client, world, node["id"], key=new_key)
    assert new.status_code == 201, new.text
    assert client.patch(node_path, headers=owner, json={"status": "active"}).status_code == 200
    assert client.post("/api/v1/edge/heartbeat", headers={"Authorization": f"Bearer {new.json()['token']}"}, json={}).status_code == 200


def test_heartbeat_retries_health_bounds_and_failures_do_not_change_admin_status(client, registry_world, app):
    world = registry_world
    owner = world["accounts"]["owner"][1]
    now = datetime(2030, 3, 1, tzinfo=UTC)
    app.state.clock = lambda: now
    node = create_node(client, world).json()
    issued = issue_credential(client, world, node["id"])
    token = issued.json()["token"]
    assert client.patch(f"{world['nodes']}/{node['id']}", headers=owner, json={"status": "active"}).status_code == 200
    headers = {"Authorization": f"Bearer {token}"}
    body = {"health": {"software_version": "1.0", "status": "ok"}}
    for tick in (0, 31, 62):
        app.state.clock = lambda tick=tick: now + timedelta(seconds=tick)
        response = client.post("/api/v1/edge/heartbeat", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["online"] is True
    with app.state.sessions() as db:
        before = db.get(EdgeNode, node["id"]).last_seen_at
    app.state.clock = lambda: now + timedelta(seconds=63)
    invalid = client.post("/api/v1/edge/heartbeat", headers=headers, json={"health": {"status": "ok", "unexpected": True}})
    assert invalid.status_code == 422
    with app.state.sessions() as db:
        after = db.get(EdgeNode, node["id"]).last_seen_at
        status = db.get(EdgeNode, node["id"]).status
    assert before == after and status == "active"
    oversized = client.post("/api/v1/edge/heartbeat", headers=headers, json={"observed_at_raw": "x" * 129})
    assert oversized.status_code == 422
    app.state.clock = lambda: now + timedelta(seconds=152)
    assert client.get(f"{world['nodes']}/{node['id']}", headers=owner).json()["online"] is False
    assert client.get(f"{world['nodes']}/{node['id']}", headers=owner).json()["status"] == "active"
