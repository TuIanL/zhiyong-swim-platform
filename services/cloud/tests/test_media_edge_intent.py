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


def edge_intent(
    client, token, session_id, device_id, *, key="edge-intent-1", expected_size_bytes=4096,
    capture_metadata=None,
):
    return client.post(
        f"/api/v1/edge/sessions/{session_id}/upload-sessions",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
        json={
            "device_id": device_id, "expected_size_bytes": expected_size_bytes, "expected_sha256": SHA,
            "media_type": "video/mp4", "capture_metadata": dict(capture_metadata or META),
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


def test_edge_cancelled_session_replays_original_intent_before_device_state(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    session = make_session(client, org)
    created = edge_intent(client, token, session["id"], device["id"], key="edge-cancel-replay-1")
    assert created.status_code == 201, created.text
    pair = created.json()
    client.patch(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["oh"],
        json={"status": "cancelled"},
    )
    client.patch(
        org["base"] + f"/devices/{device['id']}", headers=org["oh"], json={"status": "disabled"},
    )

    replay = edge_intent(
        client, token, session["id"], device["id"], key="edge-cancel-replay-1"
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["asset"]["id"] == pair["asset"]["id"]
    assert replay.json()["upload_session"]["id"] == pair["upload_session"]["id"]
    assert replay.json()["upload_session"]["status"] == "failed"
    assert replay.json()["upload_session"]["failure_reason"] == "session_cancelled"
    assert replay.json()["asset"]["failure_reason"] == "session_cancelled"
    conflict = edge_intent(
        client, token, session["id"], device["id"], key="edge-cancel-replay-1", expected_size_bytes=8192,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    fresh = edge_intent(client, token, session["id"], device["id"], key="edge-cancel-fresh-01")
    assert fresh.status_code == 409 and fresh.json()["detail"]["code"] == "state_conflict"


def test_edge_intent_replay_requires_current_credential(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    device = make_device(client, org["oh"], org["base"], node["id"])
    session = make_session(client, org)
    created = edge_intent(client, token, session["id"], device["id"], key="edge-auth-replay-01")
    assert created.status_code == 201, created.text

    credentials = client.get(
        org["base"] + f"/edge-nodes/{node['id']}/credentials", headers=org["oh"],
    )
    assert credentials.status_code == 200 and len(credentials.json()) == 1
    revoked = client.delete(
        org["base"] + f"/edge-nodes/{node['id']}/credentials/{credentials.json()[0]['id']}",
        headers=org["oh"],
    )
    assert revoked.status_code == 204

    replay = edge_intent(client, token, session["id"], device["id"], key="edge-auth-replay-01")
    assert replay.status_code == 401


def test_identical_bytes_from_two_devices_keep_distinct_capture_identity(client, seeded_account):
    org = build(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"])
    node_b, token_b = activate_node(client, org["oh"], org["base"], name="N2", key="node-capture-b")
    device_a = make_device(client, org["oh"], org["base"], node["id"], name="CAM-A", key="device-capture-a")
    device_b = make_device(client, org["oh"], org["base"], node_b["id"], name="CAM-B", key="device-capture-b")
    session = make_session(client, org)
    metadata_a = {
        "device_time_basis": "utc", "capture_started_at_utc": "2026-11-13T01:00:00Z",
        "device_capture_started_at_raw": "camera A local capture", "video_timebase_kind": "wall_clock",
        "device_clock_source": "ntp",
    }
    metadata_b = {
        "device_time_basis": "utc", "capture_started_at_utc": "2026-11-13T02:00:00Z",
        "device_capture_started_at_raw": "camera B local capture", "video_timebase_kind": "wall_clock",
        "device_clock_source": "gps",
    }
    first = edge_intent(
        client, token, session["id"], device_a["id"], key="same-content-capture-a",
        capture_metadata=metadata_a,
    )
    second = edge_intent(
        client, token_b, session["id"], device_b["id"], key="same-content-capture-b",
        capture_metadata=metadata_b,
    )
    assert first.status_code == second.status_code == 201
    a, b = first.json(), second.json()
    assert a["upload_session"]["expected_sha256"] == b["upload_session"]["expected_sha256"] == SHA
    assert a["upload_session"]["expected_size_bytes"] == b["upload_session"]["expected_size_bytes"] == 4096
    assert a["asset"]["id"] != b["asset"]["id"]
    assert a["upload_session"]["id"] != b["upload_session"]["id"]
    assert a["asset"]["source_device_id"] == device_a["id"]
    assert b["asset"]["source_device_id"] == device_b["id"]
    assert a["asset"]["device_capture_started_at_raw"] == metadata_a["device_capture_started_at_raw"]
    assert b["asset"]["device_capture_started_at_raw"] == metadata_b["device_capture_started_at_raw"]

    manual_a = client.post(
        org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
        headers={**org["ch"], "Idempotency-Key": "same-content-manual-a"},
        json={"expected_size_bytes": 4096, "expected_sha256": SHA, "media_type": "video/mp4", "capture_metadata": META},
    )
    manual_b = client.post(
        org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
        headers={**org["ch"], "Idempotency-Key": "same-content-manual-b"},
        json={"expected_size_bytes": 4096, "expected_sha256": SHA, "media_type": "video/mp4", "capture_metadata": META},
    )
    assert manual_a.status_code == manual_b.status_code == 201
    assert manual_a.json()["asset"]["id"] != manual_b.json()["asset"]["id"]
    assert manual_a.json()["upload_session"]["id"] != manual_b.json()["upload_session"]["id"]


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
