"""Edge 上传意图：节点身份、设备来源与场馆一致性（SQLite 与 PostgreSQL 共享）。"""
SHA = "a" * 64
META = {"device_time_basis": "unknown", "video_timebase_kind": "relative", "device_clock_source": "unknown"}


def build(client, seeded_account, *, extra_site=False):
    owner, oh = seeded_account("owner")
    coach, ch = seeded_account("coach")
    tenant = client.post("/api/v1/tenants", headers=oh, json={"name": "T", "slug": "team-a"}).json()
    site = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=oh, json={"name": "S1"}).json()
    client.post(
        f"/api/v1/tenants/{tenant['id']}/members", headers=oh,
        json={"user_id": coach["id"], "role": "coach"},
    )
    client.post(
        f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/members", headers=oh,
        json={"user_id": coach["id"]},
    )
    base = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
    result = {"owner": owner, "oh": oh, "coach": coach, "ch": ch, "tenant": tenant, "site": site, "base": base}
    if extra_site:
        result["site_b"] = client.post(
            f"/api/v1/tenants/{tenant['id']}/sites", headers=oh, json={"name": "S2"}
        ).json()
        result["base_b"] = f"/api/v1/tenants/{tenant['id']}/sites/{result['site_b']['id']}"
    return result


def activate_node(client, owner_headers, base, *, name="N1", key="node-key-1"):
    node = client.post(
        base + "/edge-nodes", headers={**owner_headers, "Idempotency-Key": key}, json={"name": name}
    ).json()
    client.patch(base + f"/edge-nodes/{node['id']}", headers=owner_headers, json={"status": "active"})
    credential = client.post(
        base + f"/edge-nodes/{node['id']}/credentials",
        headers={**owner_headers, "Idempotency-Key": f"{key}-cred"}, json={},
    ).json()
    return node, credential["token"]


def make_device(client, owner_headers, base, node_id, *, name="CAM1", key="device-key-1"):
    return client.post(
        base + "/devices", headers={**owner_headers, "Idempotency-Key": key},
        json={"edge_node_id": node_id, "name": name},
    ).json()


def make_session(client, org, key="edge-session-1"):
    response = client.post(
        org["base"] + "/training-sessions",
        headers={**org["ch"], "Idempotency-Key": key}, json={"title": "训练"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def edge_intent(client, token, session_id, device_id, *, key="edge-intent-1"):
    return client.post(
        f"/api/v1/edge/sessions/{session_id}/upload-sessions",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={
            "device_id": device_id, "expected_size_bytes": 4096, "expected_sha256": SHA,
            "media_type": "video/mp4", "capture_metadata": dict(META),
        },
    )


def test_edge_intent_records_source_and_replays(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    session = make_session(client, org)

    created = edge_intent(client, token, session["id"], device["id"])
    assert created.status_code == 201, created.text
    asset = created.json()["asset"]
    assert asset["origin"] == "edge"
    assert asset["source_edge_node_id"] == node["id"]
    assert asset["source_device_id"] == device["id"]
    assert asset["created_by_user_id"] is None
    assert created.json()["upload_session"]["initiator_edge_node_id"] == node["id"]
    assert created.json()["upload_session"]["initiator_user_id"] is None

    replay = edge_intent(client, token, session["id"], device["id"])
    assert replay.status_code == 201
    assert replay.json()["upload_session"]["id"] == created.json()["upload_session"]["id"]


def test_edge_intent_rejects_foreign_or_disabled_device(client, seeded_account):
    org = build(client, seeded_account, extra_site=True)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    session = make_session(client, org)

    other_node, _ = activate_node(client, org["oh"], org["base"], name="N2", key="node-key-2")
    foreign = make_device(client, org["oh"], org["base"], other_node["id"], name="CAM2", key="device-key-2")
    assert edge_intent(client, token, session["id"], foreign["id"], key="edge-intent-2").status_code == 404

    client.patch(org["base"] + f"/devices/{device['id']}", headers=org["oh"], json={"status": "disabled"})
    assert edge_intent(client, token, session["id"], device["id"], key="edge-intent-3").status_code == 409


def test_edge_intent_requires_session_in_node_scope(client, seeded_account):
    org = build(client, seeded_account, extra_site=True)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    other_site_session = client.post(
        org["base_b"] + "/training-sessions",
        headers={**org["oh"], "Idempotency-Key": "edge-session-2"}, json={"title": "另一场馆"},
    ).json()

    cross_site = edge_intent(client, token, other_site_session["id"], device["id"], key="edge-cross-1")
    assert cross_site.status_code == 404


def test_edge_upload_session_is_bound_to_its_node(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    session = make_session(client, org)
    created = edge_intent(client, token, session["id"], device["id"]).json()

    path = f"/api/v1/edge/upload-sessions/{created['upload_session']['id']}"
    assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200

    _, other_token = activate_node(client, org["oh"], org["base"], name="N3", key="node-key-3")
    assert client.get(path, headers={"Authorization": f"Bearer {other_token}"}).status_code == 404
    assert client.post(
        path + "/abort", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 404
    assert client.get(path).status_code == 401

    assert client.post(path + "/abort", headers={"Authorization": f"Bearer {token}"}).status_code == 204
    terminal = client.get(path, headers={"Authorization": f"Bearer {token}"}).json()
    assert terminal["status"] == "aborted" and terminal["failure_reason"] == "upload_aborted"


def test_edge_identity_cannot_read_user_resources(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    session = make_session(client, org)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(org["base"] + f"/training-sessions/{session['id']}", headers=headers).status_code == 401
    assert client.get(org["base"] + "/training-sessions", headers=headers).status_code == 401
    assert client.post(
        org["base"] + "/training-sessions", headers={**headers, "Idempotency-Key": "edge-user-1"},
        json={"title": "x"},
    ).status_code == 401
