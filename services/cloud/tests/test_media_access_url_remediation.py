"""C1/W1 media access URL deadline and exact-version checks."""
from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest
from sqlalchemy import select

from swimplatform.models import (
    AssetReadGrant, AuthSession, MediaObject, SessionReadGrant, TrainingSession,
    UploadSession, VideoAsset,
)
from swimplatform.security import token_hash
from swimplatform.storage import StorageError

from test_media_authorization import build, make_asset, make_session

SIZE = 1024
SHA = "a" * 64


class HeadAndSigner:
    profile = "fake-test"
    bucket = "fake-private"

    def __init__(self):
        self.expected = None
        self.head_error = None
        self.sign_calls = []
        self.head_calls = []

    def head_object(self, key, version_id=None):
        self.head_calls.append((key, version_id))
        if self.head_error:
            raise self.head_error
        assert self.expected is not None
        return dict(self.expected)

    def sign_read(self, key, version_id, expires, *, disposition=None):
        self.sign_calls.append((key, version_id, expires, disposition))
        return f"https://storage.invalid/object?expires={expires}"


@pytest.fixture
def ready_access_asset(client, app, seeded_account):
    org = build(client, seeded_account)
    training = make_session(client, org)
    asset_read = make_asset(client, org, training["id"])
    provider = HeadAndSigner()
    now = datetime.now(UTC)
    with app.state.sessions() as db:
        asset = db.get(VideoAsset, asset_read["id"])
        upload = db.scalar(select(UploadSession).where(UploadSession.asset_id == asset.id))
        upload.status = "completed"
        upload.completed_at = now
        upload.complete_manifest_hash = "b" * 64
        upload.complete_requested_at = now
        obj = MediaObject(
            tenant_id=asset.tenant_id, site_id=asset.site_id, session_id=asset.session_id,
            asset_id=asset.id, upload_session_id=upload.id,
            provider_profile=provider.profile, bucket=provider.bucket,
            object_key=f"private/test/{asset.id}", object_version="version-1", phase="verified",
            generation=1, observed_size_bytes=SIZE, observed_sha256=SHA,
            observed_media_type="video/mp4", verified_at=now,
        )
        db.add(obj)
        db.flush()
        asset.status = "ready"
        asset.received_at = now
        asset.size_bytes = SIZE
        asset.media_type = "video/mp4"
        asset.checksum_sha256 = SHA
        asset.storage_object_ref = obj.id
        asset.verified_size_bytes = SIZE
        asset.verified_media_type = "video/mp4"
        asset.verified_at = now
        db.commit()
        provider.expected = {
            "size": SIZE, "version_id": "version-1",
            "metadata": {
                "owner": "swim-platform", "purpose": "isolated-media-transfer",
                "tenant-id": asset.tenant_id, "site-id": asset.site_id,
                "session-id": asset.session_id, "asset-id": asset.id,
                "upload-session-id": upload.id,
            },
        }
        identifiers = {
            "asset_id": asset.id, "session_id": training["id"],
            "tenant_id": asset.tenant_id, "site_id": asset.site_id,
            "object_id": obj.id, "upload_id": upload.id,
        }
    app.state.storage_provider = provider
    app.state.settings = replace(app.state.settings, media_enabled=True,
                                 media_read_url_seconds=60, media_read_url_max_seconds=300)
    return org, identifiers, provider


def set_auth_expiry(app, headers, expiry):
    token = headers["Authorization"].split(" ", 1)[1]
    with app.state.sessions() as db:
        auth = db.get(AuthSession, token_hash(token))
        auth.expires_at = expiry
        db.commit()


def add_grant(app, org, identifiers, user_id, *, expires_at=None, revoked_at=None, asset=False):
    now = datetime.now(UTC)
    with app.state.sessions() as db:
        if asset:
            grant = AssetReadGrant(
                tenant_id=identifiers["tenant_id"], site_id=identifiers["site_id"],
                session_id=identifiers["session_id"], asset_id=identifiers["asset_id"],
                grantee_user_id=user_id, granted_by_user_id=org["owner"]["id"],
                granted_at=now, expires_at=expires_at, revoked_at=revoked_at,
                revoked_by_user_id=org["owner"]["id"] if revoked_at else None,
            )
        else:
            grant = SessionReadGrant(
                tenant_id=identifiers["tenant_id"], site_id=identifiers["site_id"],
                session_id=identifiers["session_id"], grantee_user_id=user_id,
                granted_by_user_id=org["owner"]["id"], granted_at=now,
                expires_at=expires_at, revoked_at=revoked_at,
                revoked_by_user_id=org["owner"]["id"] if revoked_at else None,
            )
        db.add(grant)
        db.commit()


@pytest.mark.parametrize("operation", ["playback-url", "download-url"])
def test_permanent_grant_never_outlives_short_auth_session(
    client, app, ready_access_asset, operation
):
    org, ids, provider = ready_access_asset
    reader, headers = org["other"], org["xh"]
    fixed_now = datetime.now(UTC)
    app.state.clock = lambda: fixed_now
    add_grant(app, org, ids, reader["id"], expires_at=None)
    add_grant(app, org, ids, reader["id"], expires_at=fixed_now + timedelta(hours=1),
              revoked_at=fixed_now + timedelta(seconds=1), asset=True)
    set_auth_expiry(app, headers, fixed_now + timedelta(seconds=10))
    response = client.post(
        f"{org['base']}/video-assets/{ids['asset_id']}/{operation}", headers=headers,
    )
    assert response.status_code == 200, response.text
    assert provider.sign_calls[-1][2] == 10
    assert datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00")) == fixed_now + timedelta(seconds=10)
    assert int(response.json()["url"].split("expires=")[-1]) == provider.sign_calls[-1][2]


def test_finite_grant_caps_long_auth_deadline(client, app, ready_access_asset):
    org, ids, provider = ready_access_asset
    fixed_now = datetime.now(UTC)
    app.state.clock = lambda: fixed_now
    add_grant(app, org, ids, org["other"]["id"], expires_at=fixed_now + timedelta(seconds=30))
    set_auth_expiry(app, org["xh"], fixed_now + timedelta(seconds=120))
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/playback-url",
                           headers=org["xh"])
    assert response.status_code == 200, response.text
    assert provider.sign_calls[-1][2] == 30
    assert datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00")) == fixed_now + timedelta(seconds=30)


def test_or_grants_choose_longest_active_path_and_ignore_revoked_path(
    client, app, ready_access_asset
):
    org, ids, provider = ready_access_asset
    fixed_now = datetime.now(UTC)
    app.state.clock = lambda: fixed_now
    add_grant(app, org, ids, org["other"]["id"], expires_at=fixed_now + timedelta(seconds=30))
    add_grant(app, org, ids, org["other"]["id"], expires_at=fixed_now + timedelta(seconds=45), asset=True)
    # A revoked long-lived path must not participate in the OR deadline.
    add_grant(app, org, ids, org["other"]["id"], expires_at=fixed_now + timedelta(hours=1),
              revoked_at=fixed_now + timedelta(seconds=1), asset=True)
    set_auth_expiry(app, org["xh"], fixed_now + timedelta(seconds=120))
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/download-url",
                           headers=org["xh"])
    assert response.status_code == 200, response.text
    assert provider.sign_calls[-1][2] == 45
    assert "attachment" in provider.sign_calls[-1][3]


@pytest.mark.parametrize("identity_kind", ["creator", "manager"])
def test_creator_and_manager_paths_remain_capped_by_identity(
    client, app, ready_access_asset, identity_kind
):
    org, ids, provider = ready_access_asset
    fixed_now = datetime.now(UTC)
    app.state.clock = lambda: fixed_now
    if identity_kind == "creator":
        headers, user, ttl = org["ch"], org["coach"], 40
    else:
        headers, user, ttl = org["oh"], org["owner"], 55
    set_auth_expiry(app, headers, fixed_now + timedelta(seconds=ttl))
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/playback-url",
                           headers=headers)
    assert response.status_code == 200, response.text
    assert provider.sign_calls[-1][2] == ttl
    assert user["id"]


def test_expired_auth_is_rejected_before_head_or_sign(client, app, ready_access_asset):
    org, ids, provider = ready_access_asset
    fixed_now = datetime.now(UTC)
    app.state.clock = lambda: fixed_now
    set_auth_expiry(app, org["ch"], fixed_now - timedelta(seconds=1))
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/download-url",
                           headers=org["ch"])
    assert response.status_code == 401
    assert provider.head_calls == []
    assert provider.sign_calls == []


@pytest.mark.parametrize("error", [StorageError("permission_denied"), StorageError("provider_unavailable")])
def test_head_permission_and_network_failures_are_diagnostic_server_errors(
    client, ready_access_asset, error
):
    org, ids, provider = ready_access_asset
    provider.head_error = error
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/playback-url",
                           headers=org["ch"])
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storage_unavailable"
    assert error.code in response.json()["detail"]["message"]
    assert provider.sign_calls == []


def test_missing_exact_object_version_returns_unavailable_without_mutating_ready_history(
    client, app, ready_access_asset
):
    org, ids, provider = ready_access_asset
    provider.head_error = StorageError("not_found")
    before = None
    with app.state.sessions() as db:
        asset = db.get(VideoAsset, ids["asset_id"])
        obj = db.get(MediaObject, ids["object_id"])
        before = (asset.status, asset.storage_object_ref, obj.object_key, obj.object_version,
                  obj.phase, obj.observed_size_bytes)
    for operation in ("playback-url", "download-url"):
        response = client.post(
            f"{org['base']}/video-assets/{ids['asset_id']}/{operation}", headers=org["ch"]
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "media_unavailable"
        assert "url" not in response.json()
    with app.state.sessions() as db:
        asset = db.get(VideoAsset, ids["asset_id"])
        obj = db.get(MediaObject, ids["object_id"])
        after = (asset.status, asset.storage_object_ref, obj.object_key, obj.object_version,
                 obj.phase, obj.observed_size_bytes)
    assert after == before
    assert provider.sign_calls == []


@pytest.mark.parametrize("mutation", ["version", "size", "metadata"])
def test_head_must_match_exact_version_size_and_identity(client, ready_access_asset, mutation):
    org, ids, provider = ready_access_asset
    if mutation == "version":
        provider.expected["version_id"] = "other-version"
    elif mutation == "size":
        provider.expected["size"] = SIZE + 1
    else:
        provider.expected["metadata"]["asset-id"] = "other-asset"
    response = client.post(f"{org['base']}/video-assets/{ids['asset_id']}/download-url",
                           headers=org["ch"])
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "media_unavailable"
    assert provider.sign_calls == []
