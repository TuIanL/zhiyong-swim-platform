"""训练会话、上传意图与资产的核心行为（SQLite 与 PostgreSQL 共享）。"""
from datetime import UTC, datetime, timedelta

import pytest

SHA = "a" * 64
META = {"device_time_basis": "unknown", "video_timebase_kind": "relative", "device_clock_source": "unknown"}


def setup_org(client, seeded_account, *, role="coach"):
    owner, owner_headers = seeded_account("owner")
    coach, coach_headers = seeded_account("coach")
    tenant = client.post(
        "/api/v1/tenants", headers=owner_headers, json={"name": "T", "slug": "team-a"}
    ).json()
    site = client.post(
        f"/api/v1/tenants/{tenant['id']}/sites", headers=owner_headers, json={"name": "S1"}
    ).json()
    client.post(
        f"/api/v1/tenants/{tenant['id']}/members", headers=owner_headers,
        json={"user_id": coach["id"], "role": role},
    )
    client.post(
        f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/members", headers=owner_headers,
        json={"user_id": coach["id"]},
    )
    base = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
    return {
        "owner": owner, "oh": owner_headers, "coach": coach, "ch": coach_headers,
        "tenant": tenant, "site": site, "base": base,
    }


def new_session(client, org, *, key="session-key-1", headers=None) -> dict:
    response = client.post(
        org["base"] + "/training-sessions",
        headers={**(headers or org["ch"]), "Idempotency-Key": key},
        json={"title": "第一次训练"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def intent_body(**overrides):
    body = {
        "expected_size_bytes": 2048, "expected_sha256": SHA, "media_type": "video/mp4",
        "capture_metadata": dict(META),
    }
    body.update(overrides)
    return body


def create_intent(client, org, session_id, *, key="intent-key-1", headers=None, **overrides):
    return client.post(
        org["base"] + f"/training-sessions/{session_id}/upload-sessions",
        headers={**(headers or org["ch"]), "Idempotency-Key": key},
        json=intent_body(**overrides),
    )


def test_session_create_uses_cloud_identity_and_replays_idempotently(client, seeded_account):
    org = setup_org(client, seeded_account)
    created = new_session(client, org)
    assert created["status"] == "planned"
    assert created["created_by_user_id"] == org["coach"]["id"]
    assert created["started_at"] is None and created["completed_at"] is None

    replay = client.post(
        org["base"] + "/training-sessions",
        headers={**org["ch"], "Idempotency-Key": "session-key-1"},
        json={"title": "第一次训练"},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == created["id"]

    conflict = client.post(
        org["base"] + "/training-sessions",
        headers={**org["ch"], "Idempotency-Key": "session-key-1"},
        json={"title": "改过的标题"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "00000000-0000-0000-0000-000000000000"),
        ("site_id", "00000000-0000-0000-0000-000000000000"),
        ("created_by_user_id", "00000000-0000-0000-0000-000000000000"),
        ("status", "completed"),
        ("started_at", "2026-01-01T00:00:00Z"),
    ],
)
def test_session_create_rejects_client_owned_fields(client, seeded_account, field, value):
    org = setup_org(client, seeded_account)
    response = client.post(
        org["base"] + "/training-sessions",
        headers={**org["ch"], "Idempotency-Key": f"reject-{field}-1"},
        json={"title": "x", field: value},
    )
    assert response.status_code == 422


def test_session_state_machine_and_terminal_states(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    url = org["base"] + f"/training-sessions/{session['id']}"

    skipped = client.patch(url, headers=org["ch"], json={"status": "completed"})
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == "state_conflict"

    recording = client.patch(url, headers=org["ch"], json={"status": "recording"})
    assert recording.status_code == 200 and recording.json()["started_at"] is not None

    repeated = client.patch(url, headers=org["ch"], json={"status": "recording"})
    assert repeated.status_code == 200
    assert repeated.json()["started_at"] == recording.json()["started_at"]

    completed = client.patch(url, headers=org["ch"], json={"status": "completed"})
    assert completed.status_code == 200 and completed.json()["completed_at"] is not None

    reopened = client.patch(url, headers=org["ch"], json={"status": "cancelled"})
    assert reopened.status_code == 409


def test_session_patch_surface_is_closed(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    url = org["base"] + f"/training-sessions/{session['id']}"

    assert client.patch(url, headers=org["ch"], json={}).status_code == 422
    assert client.patch(url, headers=org["ch"], json={"title": None}).status_code == 422
    assert client.patch(url, headers=org["ch"], json={"tenant_id": "x"}).status_code == 422

    renamed = client.patch(url, headers=org["ch"], json={"title": "改名"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "改名"
    assert renamed.json()["status"] == "planned"


def test_intent_creates_asset_and_upload_session_together(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    response = create_intent(client, org, session["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    upload, asset = body["upload_session"], body["asset"]
    assert upload["asset_id"] == asset["id"]
    assert asset["session_id"] == session["id"]
    assert asset["origin"] == "manual"
    assert asset["created_by_user_id"] == org["coach"]["id"]
    assert asset["status"] == "pending_upload"
    assert asset["checksum_sha256"] is None
    assert asset["source_edge_node_id"] is None and asset["source_device_id"] is None
    assert upload["status"] == "uploading"
    assert upload["confirmed_parts"] == []

    replay = create_intent(client, org, session["id"])
    assert replay.status_code == 201
    assert replay.json()["upload_session"]["id"] == upload["id"]
    assert replay.json()["asset"]["id"] == asset["id"]

    conflict = create_intent(client, org, session["id"], expected_size_bytes=4096)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_upload_session_read_and_abort_pair_asset_failure(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(client, org, session["id"]).json()

    read = client.get(org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"])
    assert read.status_code == 200 and read.json()["status"] == "uploading"

    assert client.post(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}/abort", headers=org["ch"]
    ).status_code == 204
    terminal = client.get(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"]
    ).json()
    assert terminal["status"] == "aborted" and terminal["failure_reason"] == "upload_aborted"

    asset = client.get(org["base"] + f"/video-assets/{created['asset']['id']}", headers=org["ch"]).json()
    assert asset["status"] == "failed" and asset["failure_reason"] == "upload_aborted"

    repeated = client.post(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}/abort", headers=org["ch"]
    )
    assert repeated.status_code == 204
    still = client.get(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"]
    ).json()
    assert still["updated_at"] == terminal["updated_at"]


def test_expiry_is_materialized_by_server_clock(client, app, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(client, org, session["id"]).json()

    app.state.clock = lambda: datetime.now(UTC) + timedelta(hours=25)
    expired = client.get(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"]
    )
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"
    asset = client.get(org["base"] + f"/video-assets/{created['asset']['id']}", headers=org["ch"]).json()
    assert asset["status"] == "failed" and asset["failure_reason"] == "upload_expired"

    abort_after = client.post(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}/abort", headers=org["ch"]
    )
    assert abort_after.status_code == 204
    assert client.get(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"]
    ).json()["failure_reason"] == "upload_expired"


def test_cancelled_session_rejects_intent_and_closes_unfinished_uploads(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(client, org, session["id"]).json()

    cancelled = client.patch(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"], json={"status": "cancelled"}
    )
    assert cancelled.status_code == 200 and cancelled.json()["cancelled_at"] is not None

    upload = client.get(
        org["base"] + f"/upload-sessions/{created['upload_session']['id']}", headers=org["ch"]
    ).json()
    assert upload["status"] == "failed" and upload["failure_reason"] == "session_cancelled"
    asset = client.get(org["base"] + f"/video-assets/{created['asset']['id']}", headers=org["ch"]).json()
    assert asset["status"] == "failed" and asset["failure_reason"] == "session_cancelled"

    rejected = create_intent(client, org, session["id"], key="after-cancel-1")
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "state_conflict"


def test_completed_session_accepts_make_up_upload_without_rollback(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    url = org["base"] + f"/training-sessions/{session['id']}"
    client.patch(url, headers=org["ch"], json={"status": "recording"})
    completed = client.patch(url, headers=org["ch"], json={"status": "completed"}).json()
    assert completed["completed_at"] is not None

    make_up = create_intent(client, org, session["id"], key="make-up-1")
    assert make_up.status_code == 201, make_up.text
    assert make_up.json()["asset"]["status"] == "pending_upload"

    after = client.get(url, headers=org["ch"]).json()
    assert after["status"] == "completed"
    assert after["completed_at"] == completed["completed_at"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"device_time_basis": "unknown", "device_timezone": "Asia/Shanghai", "video_timebase_kind": "unknown"},
        {"device_time_basis": "unknown", "capture_started_at_utc": "2026-01-01T00:00:00Z", "video_timebase_kind": "unknown"},
        {"device_time_basis": "offset", "video_timebase_kind": "unknown"},
        {"device_time_basis": "offset", "device_utc_offset_minutes": 60, "device_timezone": "Asia/Shanghai", "video_timebase_kind": "unknown"},
        {"device_time_basis": "iana_timezone", "video_timebase_kind": "unknown"},
        {"device_time_basis": "utc", "device_utc_offset_minutes": 480, "video_timebase_kind": "unknown"},
        {"device_time_basis": "utc", "device_utc_offset_minutes": 900, "video_timebase_kind": "unknown"},
        {"device_time_basis": "utc", "capture_started_at_utc": "2026-01-02T00:00:00Z",
         "capture_ended_at_utc": "2026-01-01T00:00:00Z", "video_timebase_kind": "unknown"},
    ],
)
def test_capture_metadata_rejects_inconsistent_basis(client, seeded_account, metadata):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    body = {
        "expected_size_bytes": 1024, "expected_sha256": SHA,
        "capture_metadata": {**metadata, "device_clock_source": "unknown"},
    }
    response = client.post(
        org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
        headers={**org["ch"], "Idempotency-Key": "meta-bad-1"}, json=body,
    )
    assert response.status_code == 422, response.text


def test_raw_device_time_is_preserved_verbatim(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    raw_start = "  2026-11-12 09:00:00  "
    raw_end = " 2026-11-12 09:45:00 "
    created = create_intent(
        client, org, session["id"],
        capture_metadata={
            "device_time_basis": "offset", "device_utc_offset_minutes": -300,
            "device_capture_started_at_raw": raw_start, "device_capture_ended_at_raw": raw_end,
            "video_timebase_kind": "relative", "device_clock_source": "ntp",
        },
    )
    assert created.status_code == 201, created.text
    asset = created.json()["asset"]
    assert asset["device_capture_started_at_raw"] == raw_start
    assert asset["device_capture_ended_at_raw"] == raw_end
    assert asset["device_time_basis"] == "offset"
    assert asset["checksum_sha256"] is None


def test_no_completion_or_playback_operation_is_exposed(client, seeded_account):
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(client, org, session["id"]).json()
    upload_id = created["upload_session"]["id"]
    asset_id = created["asset"]["id"]

    assert client.post(
        org["base"] + f"/upload-sessions/{upload_id}/complete", headers=org["ch"]
    ).status_code == 404
    assert client.post(
        org["base"] + f"/video-assets/{asset_id}/playback-url", headers=org["ch"]
    ).status_code == 404

    asset = client.get(org["base"] + f"/video-assets/{asset_id}", headers=org["ch"]).json()
    assert asset["status"] in {"pending_upload", "failed"}
    assert asset["checksum_sha256"] is None


def test_session_list_is_cursor_paginated_without_totals(client, seeded_account):
    org = setup_org(client, seeded_account)
    for index in range(3):
        new_session(client, org, key=f"page-key-{index}")

    first = client.get(org["base"] + "/training-sessions", headers=org["ch"], params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert "total_count" not in body
    assert body["next_cursor"]

    second = client.get(
        org["base"] + "/training-sessions", headers=org["ch"],
        params={"limit": 2, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert {row["id"] for row in first.json()["items"]}.isdisjoint(
        {row["id"] for row in second.json()["items"]}
    )

    assert client.get(
        org["base"] + "/training-sessions", headers=org["ch"], params={"limit": 101}
    ).status_code == 422


@pytest.mark.parametrize("table", ["video_assets", "upload_sessions", "idempotency_records"])
def test_intent_atomicity_rolls_back_all_three(client, app, seeded_account, table):
    """任一步写入失败，Asset、UploadSession 与幂等记录都必须一起回滚。"""
    from sqlalchemy import event as sa_event, text

    org = setup_org(client, seeded_account)
    session = new_session(client, org)

    def snapshot():
        with app.state.engine.connect() as connection:
            return (
                connection.execute(text("SELECT count(*) FROM video_assets")).scalar_one(),
                connection.execute(text("SELECT count(*) FROM upload_sessions")).scalar_one(),
                connection.execute(text("SELECT count(*) FROM idempotency_records")).scalar_one(),
            )

    before = snapshot()

    def boom(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith(f"insert into {table}"):
            raise RuntimeError(f"injected failure on {table}")

    engine = app.state.engine
    sa_event.listen(engine, "before_cursor_execute", boom)
    try:
        with pytest.raises(RuntimeError):
            create_intent(client, org, session["id"], key=f"atomic-{table}")
    finally:
        sa_event.remove(engine, "before_cursor_execute", boom)

    assert snapshot() == before
