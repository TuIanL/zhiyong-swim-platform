"""S-read / S-manage / A-read 与资源授权生命周期（SQLite 与 PostgreSQL 共享）。"""
from datetime import UTC, datetime, timedelta

import pytest

SHA = "a" * 64
META = {"device_time_basis": "unknown", "video_timebase_kind": "relative", "device_clock_source": "unknown"}


def build(client, seeded_account):
    owner, oh = seeded_account("owner")
    coach, ch = seeded_account("coach")
    other, xh = seeded_account("other")
    athlete, ah = seeded_account("athlete")
    tenant = client.post("/api/v1/tenants", headers=oh, json={"name": "T", "slug": "team-a"}).json()
    site = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=oh, json={"name": "S1"}).json()
    site_b = client.post(f"/api/v1/tenants/{tenant['id']}/sites", headers=oh, json={"name": "S2"}).json()
    for user, role in ((coach, "coach"), (other, "coach"), (athlete, "athlete")):
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members", headers=oh,
            json={"user_id": user["id"], "role": role},
        )
        client.post(
            f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}/members", headers=oh,
            json={"user_id": user["id"]},
        )
    base = f"/api/v1/tenants/{tenant['id']}/sites/{site['id']}"
    return {
        "owner": owner, "oh": oh, "coach": coach, "ch": ch, "other": other, "xh": xh,
        "athlete": athlete, "ah": ah, "tenant": tenant, "site": site, "site_b": site_b, "base": base,
    }


def make_session(client, org, headers=None, key="auth-session-1"):
    response = client.post(
        org["base"] + "/training-sessions",
        headers={**(headers or org["ch"]), "Idempotency-Key": key},
        json={"title": "训练"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_asset(client, org, session_id, headers=None, key="auth-intent-1"):
    response = client.post(
        org["base"] + f"/training-sessions/{session_id}/upload-sessions",
        headers={**(headers or org["ch"]), "Idempotency-Key": key},
        json={
            "expected_size_bytes": 1024, "expected_sha256": SHA, "media_type": "video/mp4",
            "capture_metadata": dict(META),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]


def test_owner_reads_without_explicit_site_membership(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    asset = make_asset(client, org, session["id"])

    assert client.get(org["base"] + f"/training-sessions/{session['id']}", headers=org["oh"]).status_code == 200
    assert client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["oh"]).status_code == 200
    patched = client.patch(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["oh"], json={"title": "管理员改名"}
    )
    assert patched.status_code == 200


def test_site_access_alone_is_not_resource_access(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    asset = make_asset(client, org, session["id"])

    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404
    assert client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["xh"]).status_code == 404
    listed = client.get(org["base"] + "/training-sessions", headers=org["xh"]).json()["items"]
    assert listed == []


def test_session_grant_covers_existing_and_future_assets_but_not_manage(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    existing = make_asset(client, org, session["id"])

    granted = client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    )
    assert granted.status_code == 204

    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 200
    assert client.get(org["base"] + f"/video-assets/{existing['id']}", headers=org["xh"]).status_code == 200

    future = make_asset(client, org, session["id"], key="auth-intent-future")
    assert client.get(org["base"] + f"/video-assets/{future['id']}", headers=org["xh"]).status_code == 200

    patched = client.patch(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"], json={"title": "越权改名"}
    )
    assert patched.status_code == 403

    upload = client.post(
        org["base"] + f"/training-sessions/{session['id']}/upload-sessions",
        headers={**org["xh"], "Idempotency-Key": "readonly-upload-1"},
        json={
            "expected_size_bytes": 1, "expected_sha256": SHA, "capture_metadata": dict(META),
        },
    )
    assert upload.status_code == 403


def test_asset_grant_is_limited_to_that_asset(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    granted_asset = make_asset(client, org, session["id"])
    sibling = make_asset(client, org, session["id"], key="auth-intent-sibling")

    assert client.put(
        org["base"] + f"/video-assets/{granted_asset['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    ).status_code == 204

    assert client.get(
        org["base"] + f"/video-assets/{granted_asset['id']}", headers=org["xh"]
    ).status_code == 200
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}/video-assets", headers=org["xh"]
    ).status_code == 404
    assert client.get(org["base"] + f"/video-assets/{sibling['id']}", headers=org["xh"]).status_code == 404


def test_revoking_one_path_keeps_the_others(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    asset = make_asset(client, org, session["id"])
    client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    )
    client.put(
        org["base"] + f"/video-assets/{asset['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    )

    revoked = client.delete(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"],
    )
    assert revoked.status_code == 204
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404
    assert client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["xh"]).status_code == 200

    again = client.delete(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"],
    )
    assert again.status_code == 204

    client.delete(
        org["base"] + f"/video-assets/{asset['id']}/read-grants/{org['other']['id']}", headers=org["oh"]
    )
    assert client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["xh"]).status_code == 404


def test_creator_path_survives_grant_revocation(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['coach']['id']}",
        headers=org["oh"], json={},
    )
    client.delete(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['coach']['id']}",
        headers=org["oh"],
    )
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"]
    ).status_code == 200


def test_downgrade_to_athlete_revokes_creator_and_grant_access(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    asset = make_asset(client, org, session["id"])
    client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['coach']['id']}",
        headers=org["oh"], json={},
    )

    downgraded = client.patch(
        f"/api/v1/tenants/{org['tenant']['id']}/members/{org['coach']['id']}",
        headers=org["oh"], json={"role": "athlete"},
    )
    assert downgraded.status_code == 200
    # 刻意保留 SiteMembership：权限失效不能依赖场馆授权被一并删除。
    assert client.get(
        f"/api/v1/tenants/{org['tenant']['id']}/sites/{org['site']['id']}", headers=org["ch"]
    ).status_code == 200

    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"]
    ).status_code == 404
    assert client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["ch"]).status_code == 404
    assert client.patch(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"], json={"title": "x"}
    ).status_code == 404
    assert client.get(org["base"] + "/training-sessions", headers=org["ch"]).json()["items"] == []


def test_site_access_and_membership_loss_override_unexpired_grants(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    )
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 200

    client.delete(
        f"/api/v1/tenants/{org['tenant']['id']}/sites/{org['site']['id']}/members/{org['other']['id']}",
        headers=org["oh"],
    )
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404

    client.post(
        f"/api/v1/tenants/{org['tenant']['id']}/sites/{org['site']['id']}/members",
        headers=org["oh"], json={"user_id": org["other"]["id"]},
    )
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 200
    client.delete(
        f"/api/v1/tenants/{org['tenant']['id']}/members/{org['other']['id']}", headers=org["oh"]
    )
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404


def test_expired_grant_stops_applying(client, app, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{org['other']['id']}",
        headers=org["oh"], json={"expires_at": expires},
    ).status_code == 204
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 200

    app.state.clock = lambda: datetime.now(UTC) + timedelta(hours=2)
    assert client.get(
        org["base"] + f"/training-sessions/{session['id']}", headers=org["xh"]
    ).status_code == 404


def test_grant_eligibility_and_authority(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    url = org["base"] + f"/training-sessions/{session['id']}/read-grants"

    assert client.put(f"{url}/{org['other']['id']}", headers=org["ch"], json={}).status_code == 403
    assert client.put(f"{url}/{org['athlete']['id']}", headers=org["oh"], json={}).status_code == 422
    assert client.put(f"{url}/{org['owner']['id']}", headers=org["oh"], json={}).status_code == 422
    stranger, _ = seeded_account("stranger")
    assert client.put(f"{url}/{stranger['id']}", headers=org["oh"], json={}).status_code == 404

    other_site_only, osh = seeded_account("siteonly")
    client.post(
        f"/api/v1/tenants/{org['tenant']['id']}/members", headers=org["oh"],
        json={"user_id": other_site_only["id"], "role": "coach"},
    )
    assert client.put(f"{url}/{other_site_only['id']}", headers=org["oh"], json={}).status_code == 422


def test_cross_tenant_and_cross_site_are_not_found(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    asset = make_asset(client, org, session["id"])

    intruder, ih = seeded_account("intruder")
    other_tenant = client.post("/api/v1/tenants", headers=ih, json={"name": "X", "slug": "x-team"}).json()
    foreign_site = client.post(
        f"/api/v1/tenants/{other_tenant['id']}/sites", headers=ih, json={"name": "FS"}
    ).json()
    foreign_base = f"/api/v1/tenants/{other_tenant['id']}/sites/{foreign_site['id']}"
    assert client.get(
        foreign_base + f"/training-sessions/{session['id']}", headers=ih
    ).status_code == 404
    assert client.get(foreign_base + f"/video-assets/{asset['id']}", headers=ih).status_code == 404

    same_tenant_other_site = org["base"].replace(org["site"]["id"], org["site_b"]["id"])
    assert client.get(
        same_tenant_other_site + f"/training-sessions/{session['id']}", headers=org["ch"]
    ).status_code == 404
    assert client.get(
        same_tenant_other_site + f"/video-assets/{asset['id']}", headers=org["ch"]
    ).status_code == 404


def test_cursor_stays_filtered_after_revocation(client, seeded_account):
    org = build(client, seeded_account)
    for index in range(3):
        make_session(client, org, key=f"cursor-session-{index}")
    client.put(
        org["base"] + f"/training-sessions/{make_session(client, org, key='cursor-session-x')['id']}"
        f"/read-grants/{org['other']['id']}",
        headers=org["oh"], json={},
    )
    first = client.get(
        org["base"] + "/training-sessions", headers=org["oh"], params={"limit": 2}
    )
    cursor = first.json()["next_cursor"]
    assert cursor

    for item in client.get(
        org["base"] + "/training-sessions", headers=org["oh"], params={"limit": 100}
    ).json()["items"]:
        if item["created_by_user_id"] == org["coach"]["id"]:
            client.delete(
                org["base"] + f"/training-sessions/{item['id']}/read-grants/{org['other']['id']}",
                headers=org["oh"],
            )

    page_two = client.get(
        org["base"] + "/training-sessions", headers=org["xh"],
        params={"limit": 2, "cursor": cursor},
    )
    assert page_two.status_code == 200
    assert all(row["created_by_user_id"] != org["coach"]["id"] for row in page_two.json()["items"])

    mismatched = client.get(
        org["base"] + "/training-sessions", headers=org["oh"],
        params={"limit": 2, "cursor": cursor, "status": "planned"},
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["detail"]["code"] == "invalid_cursor"


def test_anonymous_requests_are_rejected(client, seeded_account):
    org = build(client, seeded_account)
    session = make_session(client, org)
    assert client.get(org["base"] + f"/training-sessions/{session['id']}").status_code == 401
    assert client.get(org["base"] + "/training-sessions").status_code == 401
