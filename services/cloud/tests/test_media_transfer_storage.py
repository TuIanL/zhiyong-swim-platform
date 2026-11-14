"""真实 S3-compatible transfer acceptance; only a disposable RustFS profile may run this file."""
from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from swimplatform.media_transfer import cleanup_candidates, discover_orphans, process_media_job
from swimplatform.models import (
    AuthSession, EdgeCredential, MediaCleanupCandidate, MediaJob, MediaObject, UploadPart,
    UploadSession, VideoAsset,
)
from swimplatform.security import token_hash
from swimplatform.storage import StorageError

from test_media_foundation import create_intent, new_session, setup_org
from test_media_edge_intent import (
    activate_node, build as build_edge_org, edge_intent, make_device,
    make_session as new_edge_session,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-swim.mp4"
PART_BYTES = 16 * 1024 * 1024


def assert_terminal_complete_contract(client, url, headers, body, *, status, reason):
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "upload_not_completable"
    assert f"{status}/{reason}" in replay.json()["detail"]["message"]
    different = {"parts": [{"part_number": 1, "etag": '"different-manifest"'}]}
    conflict = client.post(url, headers=headers, json=different)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


@pytest.fixture
def configured_media_app(app):
    if not app.state.settings.media_enabled or not app.state.storage_provider:
        pytest.fail("storage marker was collected without the verified RustFS test profile")
    capabilities = app.state.storage_provider.check_capabilities()
    assert capabilities == {
        "multipart": True, "multipart_pagination": True, "versioning": True,
        "private_bucket": True, "range_get": True, "server_side_signing": True,
    }
    return app


def drain_worker(app, *, maximum=10):
    processed = 0
    for _ in range(maximum):
        if not process_media_job(app.state.sessions, app.state.storage_provider,
                                 app.state.settings):
            break
        processed += 1
    assert processed < maximum, "worker did not quiesce within the bounded test loop"
    return processed


def start_transfer(client, app, org, session_id, *, content, expected_sha=None,
                   media_type="video/mp4", key):
    digest = expected_sha or hashlib.sha256(content).hexdigest()
    created = create_intent(
        client, org, session_id, key=key,
        expected_size_bytes=len(content), expected_sha256=digest, media_type=media_type,
    )
    assert created.status_code == 201, created.text
    upload = created.json()["upload_session"]
    part_url = org["base"] + f"/upload-sessions/{upload['id']}/part-urls"
    first = client.post(part_url, headers=org["ch"], json={"part_numbers": [1]})
    assert first.status_code == 202, first.text
    repeat = client.post(part_url, headers=org["ch"], json={"part_numbers": [1]})
    assert repeat.status_code == 202, repeat.text
    drain_worker(app)
    signed = client.post(part_url, headers=org["ch"], json={"part_numbers": [1]})
    assert signed.status_code == 200, signed.text
    item = signed.json()["items"][0]
    request = urllib.request.Request(item["url"], data=content, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        assert 200 <= response.status < 300
        etag = response.headers.get("ETag")
    assert etag
    confirm_url = org["base"] + f"/upload-sessions/{upload['id']}/parts/1"
    confirmed = client.put(confirm_url, headers=org["ch"],
                           json={"etag": etag, "size_bytes": len(content)})
    assert confirmed.status_code == 200, confirmed.text
    confirmed_again = client.put(confirm_url, headers=org["ch"],
                                 json={"etag": etag, "size_bytes": len(content)})
    assert confirmed_again.status_code == 200, confirmed_again.text
    assert confirmed_again.json() == confirmed.json()
    return upload, created.json()["asset"], etag


@pytest.mark.storage
def test_rustfs_full_upload_resume_complete_private_range_and_cleanup(client, seeded_account,
                                                                      configured_media_app,
                                                                      monkeypatch):
    app = configured_media_app
    provider = app.state.storage_provider
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)

    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="real-upload-key-01")
    parts_url = org["base"] + f"/upload-sessions/{upload['id']}/parts"
    listed = client.get(parts_url, headers=org["ch"])
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == [{
        "part_number": 1, "size_bytes": len(content), "etag": etag,
        "confirmed_at": listed.json()["items"][0]["confirmed_at"], "state": "confirmed",
    }]

    complete_url = org["base"] + f"/upload-sessions/{upload['id']}/complete"
    complete_body = {"parts": [{"part_number": 1, "etag": etag}]}
    complete_headers = {**org["ch"], "Idempotency-Key": "complete-key-001"}
    accepted = client.post(complete_url, headers=complete_headers, json=complete_body)
    assert accepted.status_code == 202, accepted.text
    repeated = client.post(complete_url, headers=complete_headers, json=complete_body)
    assert repeated.status_code == 202, repeated.text
    with app.state.sessions() as db:
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        jobs = db.scalars(select(MediaJob).where(MediaJob.object_id == obj.id,
                                                 MediaJob.kind == "complete")).all()
        assert len(jobs) == 1 and jobs[0].state in {"queued", "running", "retry_wait"}
    assert drain_worker(app) >= 1

    status_url = org["base"] + f"/upload-sessions/{upload['id']}"
    status = client.get(status_url, headers=org["ch"])
    assert status.status_code == 200 and status.json()["status"] == "completed"
    asset_url = org["base"] + f"/video-assets/{asset['id']}"
    asset_response = client.get(asset_url, headers=org["ch"])
    assert asset_response.status_code == 200
    ready = asset_response.json()
    assert ready["status"] == "ready"
    assert ready["size_bytes"] == len(content)
    assert ready["verified_size_bytes"] == len(content)
    assert ready["checksum_sha256"] == hashlib.sha256(content).hexdigest()
    assert ready["verified_media_type"] == "video/mp4"

    replay = client.post(complete_url, headers=complete_headers, json=complete_body)
    assert replay.status_code == 200, replay.text
    conflicting = client.post(
        complete_url, headers=complete_headers,
        json={"parts": [{"part_number": 1, "etag": '"different"'}]},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "idempotency_conflict"

    playback = client.post(asset_url + "/playback-url", headers=org["ch"])
    download = client.post(asset_url + "/download-url", headers=org["ch"])
    assert playback.status_code == download.status_code == 200
    assert playback.headers["cache-control"] == "private, no-store"
    assert playback.headers["referrer-policy"] == "no-referrer"
    assert playback.json()["expires_at"]
    assert "attachment" in download.json()["url"]
    range_request = urllib.request.Request(playback.json()["url"], headers={"Range": "bytes=0-63"})
    with urllib.request.urlopen(range_request, timeout=20) as response:
        assert response.status == 206
        assert len(response.read()) == 64

    # The actual bearer URL stops working after its configured one-second expiry.
    from dataclasses import replace
    original_settings = app.state.settings
    app.state.settings = replace(original_settings, media_read_url_seconds=1,
                                 media_read_url_max_seconds=1)
    try:
        expiring_read = client.post(asset_url + "/playback-url", headers=org["ch"])
        assert expiring_read.status_code == 200, expiring_read.text
        assert (datetime.fromisoformat(expiring_read.json()["expires_at"]) - datetime.now(UTC)).total_seconds() <= 1
        time.sleep(2)
        with pytest.raises(urllib.error.HTTPError) as expired_response:
            urllib.request.urlopen(expiring_read.json()["url"], timeout=5)
        assert expired_response.value.code in {401, 403}
    finally:
        app.state.settings = original_settings

    # A grantee's presigned URL cannot outlive the specific active grant used to read the asset.
    reader, reader_headers = seeded_account("media-reader")
    assert client.post(
        f"/api/v1/tenants/{org['tenant']['id']}/members", headers=org["oh"],
        json={"user_id": reader["id"], "role": "coach"},
    ).status_code == 201
    assert client.post(
        f"/api/v1/tenants/{org['tenant']['id']}/sites/{org['site']['id']}/members",
        headers=org["oh"], json={"user_id": reader["id"]},
    ).status_code == 201
    assert client.post(asset_url + "/playback-url", headers=reader_headers).status_code == 404
    grant_deadline = datetime.now(UTC) + timedelta(seconds=90)
    assert client.put(
        org["base"] + f"/training-sessions/{session['id']}/read-grants/{reader['id']}",
        headers=org["oh"], json={"expires_at": grant_deadline.isoformat()},
    ).status_code == 204
    reader_url = client.post(asset_url + "/playback-url", headers=reader_headers)
    assert reader_url.status_code == 200, reader_url.text
    assert datetime.fromisoformat(reader_url.json()["expires_at"]) <= grant_deadline

    # A second legal intent proves a lost client receipt can be reconstructed from ListParts.
    lost_upload, _lost_asset, lost_etag = start_transfer(
        client, app, org, session["id"], content=content, key="resume-upload-key-02"
    )
    with app.state.sessions() as db:
        stored = db.scalar(select(UploadSession).where(UploadSession.id == lost_upload["id"]))
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == stored.id))
        # The confirm call above stored the receipt; clear it to model a PUT whose response was lost
        # before the application could persist the client-provided confirmation.
        part = db.scalar(select(UploadPart).where(UploadPart.upload_session_id == stored.id))
        part.state, part.etag, part.actual_size_bytes, part.confirmed_at = "registered", None, None, None
        db.commit()
    recovered = client.get(org["base"] + f"/upload-sessions/{lost_upload['id']}/parts", headers=org["ch"])
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["items"][0]["etag"] == lost_etag

    # A complete retry remains 202 while one durable job is completing; Abort then wins the
    # terminal race, and same-key retries expose the original aborted reason without requeueing.
    aborting_url = org["base"] + f"/upload-sessions/{lost_upload['id']}/complete"
    aborting_headers = {**org["ch"], "Idempotency-Key": "abort-complete-key"}
    aborting_body = {"parts": [{"part_number": 1, "etag": lost_etag}]}
    assert client.post(aborting_url, headers=aborting_headers, json=aborting_body).status_code == 202
    assert client.post(aborting_url, headers=aborting_headers, json=aborting_body).status_code == 202
    with app.state.sessions() as db:
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == lost_upload["id"]))
        jobs = db.scalars(select(MediaJob).where(MediaJob.object_id == obj.id,
                                                 MediaJob.kind == "complete")).all()
        assert len(jobs) == 1
    assert client.post(org["base"] + f"/upload-sessions/{lost_upload['id']}/abort",
                       headers=org["ch"]).status_code == 204
    with app.state.sessions() as db:
        stored = db.get(UploadSession, lost_upload["id"])
        asset_row = db.get(VideoAsset, lost_upload["asset_id"])
        assert (stored.status, stored.failure_reason) == ("aborted", "upload_aborted")
        assert (asset_row.status, asset_row.failure_reason) == ("failed", "upload_aborted")
    assert_terminal_complete_contract(client, aborting_url, aborting_headers, aborting_body,
                                      status="aborted", reason="upload_aborted")

    # A missing layout must fail before any provider completion request is queued.
    oversized = create_intent(
        client, org, session["id"], key="missing-parts-key-03",
        expected_size_bytes=PART_BYTES + 1, expected_sha256="a" * 64, media_type="video/mp4",
    )
    missing_upload = oversized.json()["upload_session"]
    missing_url = org["base"] + f"/upload-sessions/{missing_upload['id']}/part-urls"
    assert client.post(missing_url, headers=org["ch"], json={"part_numbers": [1, 2]}).status_code == 202
    drain_worker(app)
    missing_complete = client.post(
        org["base"] + f"/upload-sessions/{missing_upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "missing-complete-key"},
        json={"parts": [{"part_number": 1, "etag": '"one"'},
                         {"part_number": 2, "etag": '"two"'}]},
    )
    assert missing_complete.status_code == 409
    assert missing_complete.json()["detail"]["code"] == "part_not_confirmed"


    # Wrong end-to-end SHA still transfers and confirms, then terminates failed/validation_failed.
    wrong_sha_upload, wrong_sha_asset, wrong_sha_etag = start_transfer(
        client, app, org, session["id"], content=content, expected_sha="0" * 64,
        key="wrong-sha-upload-04",
    )
    wrong_sha_complete = client.post(
        org["base"] + f"/upload-sessions/{wrong_sha_upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "wrong-sha-complete"},
        json={"parts": [{"part_number": 1, "etag": wrong_sha_etag}]},
    )
    assert wrong_sha_complete.status_code == 202
    drain_worker(app)
    final_upload = client.get(org["base"] + f"/upload-sessions/{wrong_sha_upload['id']}", headers=org["ch"]).json()
    final_asset = client.get(org["base"] + f"/video-assets/{wrong_sha_asset['id']}", headers=org["ch"]).json()
    assert (final_upload["status"], final_upload["failure_reason"]) == ("failed", "validation_failed")
    assert (final_asset["status"], final_asset["failure_reason"]) == ("failed", "validation_failed")
    failed_url = org["base"] + f"/upload-sessions/{wrong_sha_upload['id']}/complete"
    failed_headers = {**org["ch"], "Idempotency-Key": "wrong-sha-complete"}
    failed_body = {"parts": [{"part_number": 1, "etag": wrong_sha_etag}]}
    assert_terminal_complete_contract(client, failed_url, failed_headers, failed_body,
                                      status="failed", reason="validation_failed")

    # Abort wins after complete acceptance; retries return the durable original terminal state.
    # Expiry materializes even when the same accepted completion key is retried.
    expiring_upload, _expiring_asset, expiring_etag = start_transfer(
        client, app, org, session["id"], content=content, key="expire-completing-upload-06"
    )
    expiring_url = org["base"] + f"/upload-sessions/{expiring_upload['id']}/complete"
    expiring_key = {**org["ch"], "Idempotency-Key": "expire-complete-key"}
    expiring_body = {"parts": [{"part_number": 1, "etag": expiring_etag}]}
    assert client.post(expiring_url, headers=expiring_key, json=expiring_body).status_code == 202
    with app.state.sessions() as db:
        stored = db.get(UploadSession, expiring_upload["id"])
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = client.post(expiring_url, headers=expiring_key, json=expiring_body)
    assert expired.status_code == 409
    with app.state.sessions() as db:
        stored = db.get(UploadSession, expiring_upload["id"])
        assert (stored.status, stored.failure_reason) == ("expired", "upload_expired")
    assert_terminal_complete_contract(client, expiring_url, expiring_key, expiring_body,
                                      status="expired", reason="upload_expired")

    # Only this run's namespaced failed object is eligible for destructive cleanup.
    with app.state.sessions() as db:
        candidates = db.scalars(select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.asset_id == wrong_sha_asset["id"]
        )).all()
        assert candidates and all(c.object_key.startswith(
            f"private/test/{app.state.settings.media_run_id}/") for c in candidates)
    monkeypatch.setenv("SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE", "true")
    cleanup_time = datetime.now(UTC) + timedelta(minutes=10)
    cleanup = cleanup_candidates(app.state.sessions, provider, app.state.settings,
                                 execute=True, now=cleanup_time)
    assert cleanup["failed"] == 0, cleanup
    assert cleanup["removed"] >= 1


@pytest.mark.storage
def test_identical_bytes_from_two_devices_verify_as_distinct_assets(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    org = build_edge_org(client, seeded_account)
    node_a, token_a = activate_node(client, org["oh"], org["base"], name="Camera cart A", key="same-byte-node-a")
    node_b, token_b = activate_node(client, org["oh"], org["base"], name="Camera cart B", key="same-byte-node-b")
    device_a = make_device(client, org["oh"], org["base"], node_a["id"], name="CAM-A", key="same-byte-device-a")
    device_b = make_device(client, org["oh"], org["base"], node_b["id"], name="CAM-B", key="same-byte-device-b")
    session = new_edge_session(client, org, key="same-byte-session")

    def upload_from(token, device, key, raw_capture_time):
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
        metadata = {
            "device_time_basis": "unknown", "video_timebase_kind": "relative",
            "device_clock_source": "unknown", "device_capture_started_at_raw": raw_capture_time,
        }
        created = client.post(
            f"/api/v1/edge/sessions/{session['id']}/upload-sessions", headers=headers,
            json={"device_id": device["id"], "expected_size_bytes": len(content),
                  "expected_sha256": digest, "media_type": "video/mp4",
                  "capture_metadata": metadata},
        )
        assert created.status_code == 201, created.text
        upload, asset = created.json()["upload_session"], created.json()["asset"]
        base = f"/api/v1/edge/upload-sessions/{upload['id']}"
        assert client.post(base + "/part-urls", headers=headers,
                           json={"part_numbers": [1]}).status_code == 202
        drain_worker(app)
        signed = client.post(base + "/part-urls", headers=headers, json={"part_numbers": [1]})
        assert signed.status_code == 200, signed.text
        request = urllib.request.Request(signed.json()["items"][0]["url"], data=content, method="PUT")
        with urllib.request.urlopen(request, timeout=20) as response:
            etag = response.headers.get("ETag")
        assert etag
        confirmed = client.put(base + "/parts/1", headers=headers,
                               json={"etag": etag, "size_bytes": len(content)})
        assert confirmed.status_code == 200, confirmed.text
        completed = client.post(
            base + "/complete", headers={**headers, "Idempotency-Key": key + "-complete"},
            json={"parts": [{"part_number": 1, "etag": etag}]},
        )
        assert completed.status_code == 202, completed.text
        drain_worker(app)
        read = client.get(org["base"] + f"/video-assets/{asset['id']}", headers=org["oh"])
        assert read.status_code == 200, read.text
        assert read.json()["status"] == "ready"
        assert read.json()["checksum_sha256"] == digest
        return upload, read.json()

    upload_a, asset_a = upload_from(token_a, device_a, "same-bytes-a", "camera A capture")
    upload_b, asset_b = upload_from(token_b, device_b, "same-bytes-b", "camera B capture")
    assert asset_a["id"] != asset_b["id"]
    assert upload_a["id"] != upload_b["id"]
    assert asset_a["source_device_id"] == device_a["id"]
    assert asset_b["source_device_id"] == device_b["id"]
    assert asset_a["device_capture_started_at_raw"] != asset_b["device_capture_started_at_raw"]
    assert asset_a["checksum_sha256"] == asset_b["checksum_sha256"] == digest
    with app.state.sessions() as db:
        object_a = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload_a["id"]))
        object_b = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload_b["id"]))
        assert object_a.object_key != object_b.object_key
        assert object_a.object_version and object_b.object_version


@pytest.mark.storage
def test_real_provider_private_bucket_and_browser_cors(configured_media_app):
    provider = configured_media_app.state.storage_provider
    capabilities = provider.check_capabilities()
    assert capabilities["private_bucket"] is True
    # RustFS returns CORS headers only for the configured test origin and methods.
    probe_url = f"{provider.endpoint_url}/{provider.bucket}/cors-probe"
    request = urllib.request.Request(
        probe_url, method="OPTIONS",
        headers={"Origin": "http://localhost:3000",
                 "Access-Control-Request-Method": "PUT",
                 "Access-Control-Request-Headers": "content-type,range"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
            assert "PUT" in response.headers.get("Access-Control-Allow-Methods", "")
    except urllib.error.HTTPError as exc:
        pytest.fail(f"RustFS CORS preflight failed: HTTP {exc.code}")


@pytest.mark.storage
def test_worker_recovers_when_complete_commits_before_database_version_record(
    client, app, seeded_account, configured_media_app, monkeypatch
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="worker-crash-transfer-01")
    complete_url = org["base"] + f"/upload-sessions/{upload['id']}/complete"
    headers = {**org["ch"], "Idempotency-Key": "worker-crash-complete-01"}
    body = {"parts": [{"part_number": 1, "etag": etag}]}
    assert client.post(complete_url, headers=headers, json=body).status_code == 202
    provider = app.state.storage_provider
    actual_complete = provider.complete_multipart

    class SimulatedWorkerCrash(BaseException):
        pass

    def commit_then_crash(key, provider_upload_id, parts):
        actual_complete(key, provider_upload_id, parts)
        raise SimulatedWorkerCrash()

    monkeypatch.setattr(provider, "complete_multipart", commit_then_crash)
    with pytest.raises(SimulatedWorkerCrash):
        process_media_job(app.state.sessions, provider, app.state.settings)
    with app.state.sessions() as db:
        stored = db.get(UploadSession, upload["id"])
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        job = db.scalar(select(MediaJob).where(MediaJob.object_id == obj.id, MediaJob.kind == "complete"))
        assert stored.status == "completing"
        assert obj.object_version is None
        assert job.state == "running"
        job.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    def must_resume_from_completed_object(*_args, **_kwargs):
        pytest.fail("recovered worker attempted CompleteMultipartUpload a second time")

    monkeypatch.setattr(provider, "complete_multipart", must_resume_from_completed_object)
    assert process_media_job(app.state.sessions, provider, app.state.settings)
    final_upload = client.get(org["base"] + f"/upload-sessions/{upload['id']}",
                              headers=org["ch"]).json()
    final_asset = client.get(org["base"] + f"/video-assets/{asset['id']}",
                             headers=org["ch"]).json()
    assert final_upload["status"] == "completed"
    assert final_asset["status"] == "ready"
    assert final_asset["verified_size_bytes"] == len(content)
    assert final_asset["checksum_sha256"] == hashlib.sha256(content).hexdigest()


@pytest.mark.storage
def test_provider_rejects_actual_part_size_mismatch_before_complete(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(
        client, org, session["id"], key="wrong-part-size-01",
        expected_size_bytes=len(content) + 1,
    )
    assert created.status_code == 201, created.text
    upload = created.json()["upload_session"]
    part_urls = org["base"] + f"/upload-sessions/{upload['id']}/part-urls"
    assert client.post(part_urls, headers=org["ch"], json={"part_numbers": [1]}).status_code == 202
    drain_worker(app)
    signed = client.post(part_urls, headers=org["ch"], json={"part_numbers": [1]})
    assert signed.status_code == 200, signed.text
    request = urllib.request.Request(signed.json()["items"][0]["url"], data=content, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        etag = response.headers.get("ETag")
    assert etag
    confirm = client.put(
        org["base"] + f"/upload-sessions/{upload['id']}/parts/1", headers=org["ch"],
        json={"etag": etag, "size_bytes": len(content) + 1},
    )
    assert confirm.status_code == 409
    assert confirm.json()["detail"]["code"] == "part_conflict"
    assert client.post(org["base"] + f"/upload-sessions/{upload['id']}/abort",
                       headers=org["ch"]).status_code == 204


@pytest.mark.storage
def test_completed_object_size_mismatch_binds_and_removes_exact_version(
    client, app, seeded_account, configured_media_app, monkeypatch
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="object-size-mismatch-01")
    # Model a stale/corrupt declaration after part acceptance to exercise the worker's
    # whole-object check after provider CompleteMultipartUpload has created a real version.
    with app.state.sessions() as db:
        stored = db.get(UploadSession, upload["id"])
        stored.expected_size_bytes += 1
        db.commit()
    complete_url = org["base"] + f"/upload-sessions/{upload['id']}/complete"
    accepted = client.post(
        complete_url, headers={**org["ch"], "Idempotency-Key": "object-size-mismatch-complete"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert accepted.status_code == 202, accepted.text
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        candidate = db.scalar(select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.object_id == obj.id, MediaCleanupCandidate.kind == "object",
        ))
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "validation_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "validation_failed")
        assert obj.object_version and candidate and candidate.object_version == obj.object_version

    monkeypatch.setenv("SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE", "true")
    result = cleanup_candidates(
        app.state.sessions, app.state.storage_provider, app.state.settings, execute=True,
        now=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert result["failed"] == 0, result
    assert result["removed"] >= 1
    with pytest.raises(StorageError) as gone:
        app.state.storage_provider.head_object(obj.object_key, obj.object_version)
    assert gone.value.code == "not_found"


@pytest.mark.storage
def test_non_mp4_bytes_cannot_become_ready_even_when_declared_video_mp4(
    client, app, seeded_account, configured_media_app
):
    content = b"not an MP4 container\n" * 128
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"], content=content,
                                         media_type="video/mp4", key="fake-mp4-01")
    complete = client.post(
        org["base"] + f"/upload-sessions/{upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "fake-mp4-complete-01"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    drain_worker(app)
    failed_upload = client.get(org["base"] + f"/upload-sessions/{upload['id']}",
                               headers=org["ch"]).json()
    failed_asset = client.get(org["base"] + f"/video-assets/{asset['id']}",
                              headers=org["ch"]).json()
    assert (failed_upload["status"], failed_upload["failure_reason"]) == ("failed", "validation_failed")
    assert (failed_asset["status"], failed_asset["failure_reason"]) == ("failed", "validation_failed")
    assert failed_asset["verified_at"] is None
    with app.state.sessions() as db:
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        candidate = db.scalar(select(MediaCleanupCandidate).where(MediaCleanupCandidate.object_id == obj.id))
        assert obj.object_version and candidate and candidate.kind == "object"


@pytest.mark.storage
def test_expired_upload_is_swept_and_exact_multipart_cleanup_is_confirmed(
    client, app, seeded_account, configured_media_app, monkeypatch
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, _etag = start_transfer(client, app, org, session["id"],
                                           content=content, key="sweep-expired-upload-01")
    with app.state.sessions() as db:
        stored = db.get(UploadSession, upload["id"])
        # Age both timestamps together to preserve the database invariant while
        # modeling an intent whose original expiry has already passed.
        stored.created_at = datetime.now(UTC) - timedelta(minutes=30)
        stored.expires_at = stored.created_at + timedelta(minutes=1)
        db.commit()

    from swimplatform.media_transfer import sweep_expired
    assert sweep_expired(app.state.sessions, now=datetime.now(UTC)) == 1
    with app.state.sessions() as db:
        stored = db.get(UploadSession, upload["id"])
        asset_row = db.get(VideoAsset, asset["id"])
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        assert (stored.status, stored.failure_reason) == ("expired", "upload_expired")
        assert (asset_row.status, asset_row.failure_reason) == ("failed", "upload_expired")
        candidate = db.scalar(select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.object_id == obj.id, MediaCleanupCandidate.kind == "multipart",
        ))
        assert candidate and candidate.upload_id == obj.provider_upload_id

    monkeypatch.setenv("SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE", "true")
    result = cleanup_candidates(
        app.state.sessions, app.state.storage_provider, app.state.settings, execute=True,
        now=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert result["failed"] == 0, result
    assert result["removed"] >= 1


@pytest.mark.storage
def test_valid_user_upload_fails_if_original_login_expires_before_ready(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="user-expiry-transfer-01")
    response = client.post(
        org["base"] + f"/upload-sessions/{upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "user-expiry-complete-01"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert response.status_code == 202, response.text
    with app.state.sessions() as db:
        auth = db.scalar(select(AuthSession).where(
            AuthSession.token_hash == token_hash(org["ch"]["Authorization"].split(" ", 1)[1])
        ))
        assert auth is not None
        auth.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "upload_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "upload_failed")
        assert stored_asset.storage_object_ref is None


@pytest.mark.storage
def test_user_logout_during_complete_invalidates_original_identity_without_blocking_logout(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="user-logout-transfer-01")
    complete = client.post(
        org["base"] + f"/upload-sessions/{upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "user-logout-complete-01"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    logged_out = client.post("/api/v1/auth/logout", headers=org["ch"])
    assert logged_out.status_code == 204, logged_out.text
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "upload_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "upload_failed")
        assert stored_asset.storage_object_ref is None


@pytest.mark.storage
def test_valid_edge_upload_fails_if_original_credential_expires_before_ready(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = build_edge_org(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"], key="edge-expiry-node")
    device = make_device(client, org["oh"], org["base"], node["id"], key="edge-expiry-device")
    session = new_edge_session(client, org, key="edge-expiry-session")
    created = edge_intent(
        client, token, session["id"], device["id"], key="edge-expiry-intent",
        expected_size_bytes=len(content), expected_sha256=hashlib.sha256(content).hexdigest(),
        capture_metadata={"device_time_basis": "unknown", "video_timebase_kind": "relative",
                          "device_clock_source": "unknown"},
    )
    assert created.status_code == 201, created.text
    upload = created.json()["upload_session"]
    asset = created.json()["asset"]
    headers = {"Authorization": f"Bearer {token}"}
    parts_url = f"/api/v1/edge/upload-sessions/{upload['id']}/part-urls"
    assert client.post(parts_url, headers=headers, json={"part_numbers": [1]}).status_code == 202
    assert process_media_job(app.state.sessions, app.state.storage_provider, app.state.settings)
    signed = client.post(parts_url, headers=headers, json={"part_numbers": [1]})
    assert signed.status_code == 200, signed.text
    part_url = signed.json()["items"][0]["url"]
    request = urllib.request.Request(part_url, data=content, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as put_response:
        etag = put_response.headers.get("ETag")
    assert etag
    confirm = client.put(
        f"/api/v1/edge/upload-sessions/{upload['id']}/parts/1", headers=headers,
        json={"etag": etag, "size_bytes": len(content)},
    )
    assert confirm.status_code == 200, confirm.text
    complete = client.post(
        f"/api/v1/edge/upload-sessions/{upload['id']}/complete",
        headers={**headers, "Idempotency-Key": "edge-expiry-complete"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    with app.state.sessions() as db:
        credential = db.scalar(select(EdgeCredential).where(EdgeCredential.edge_node_id == node["id"]))
        assert credential is not None
        credential.issued_at = datetime.now(UTC) - timedelta(minutes=1)
        credential.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "upload_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "upload_failed")
        assert stored_asset.storage_object_ref is None


@pytest.mark.storage
def test_user_role_revocation_during_complete_prevents_ready(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="user-role-change-01")
    complete = client.post(
        org["base"] + f"/upload-sessions/{upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "user-role-change-complete"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    changed = client.patch(
        f"/api/v1/tenants/{org['tenant']['id']}/members/{org['coach']['id']}",
        headers=org["oh"], json={"role": "athlete"},
    )
    assert changed.status_code == 200, changed.text
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        obj = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        candidate = db.scalar(select(MediaCleanupCandidate).where(MediaCleanupCandidate.object_id == obj.id))
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "upload_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "upload_failed")
        assert stored_asset.storage_object_ref is None
        assert obj.object_version and candidate and candidate.kind == "object"


@pytest.mark.storage
def test_disabled_edge_device_during_complete_prevents_ready(
    client, app, seeded_account, configured_media_app
):
    content = FIXTURE.read_bytes()
    org = build_edge_org(client, seeded_account)
    node, token = activate_node(client, org["oh"], org["base"], key="edge-device-change-node")
    device = make_device(client, org["oh"], org["base"], node["id"], key="edge-device-change-device")
    session = new_edge_session(client, org, key="edge-device-change-session")
    created = edge_intent(
        client, token, session["id"], device["id"], key="edge-device-change-intent",
        expected_size_bytes=len(content), expected_sha256=hashlib.sha256(content).hexdigest(),
    )
    assert created.status_code == 201, created.text
    upload, asset = created.json()["upload_session"], created.json()["asset"]
    headers = {"Authorization": f"Bearer {token}"}
    part_urls = f"/api/v1/edge/upload-sessions/{upload['id']}/part-urls"
    assert client.post(part_urls, headers=headers, json={"part_numbers": [1]}).status_code == 202
    assert process_media_job(app.state.sessions, app.state.storage_provider, app.state.settings)
    signed = client.post(part_urls, headers=headers, json={"part_numbers": [1]})
    assert signed.status_code == 200, signed.text
    request = urllib.request.Request(signed.json()["items"][0]["url"], data=content, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        etag = response.headers.get("ETag")
    assert etag
    assert client.put(
        f"/api/v1/edge/upload-sessions/{upload['id']}/parts/1", headers=headers,
        json={"etag": etag, "size_bytes": len(content)},
    ).status_code == 200
    complete = client.post(
        f"/api/v1/edge/upload-sessions/{upload['id']}/complete",
        headers={**headers, "Idempotency-Key": "edge-device-change-complete"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    assert client.patch(
        org["base"] + f"/devices/{device['id']}", headers=org["oh"], json={"status": "disabled"}
    ).status_code == 200
    drain_worker(app)
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "upload_failed")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "upload_failed")
        assert stored_asset.storage_object_ref is None


@pytest.mark.storage
def test_cancel_after_provider_complete_records_exact_object_cleanup(
    client, app, seeded_account, configured_media_app, monkeypatch
):
    content = FIXTURE.read_bytes()
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    upload, asset, etag = start_transfer(client, app, org, session["id"],
                                         content=content, key="cancel-after-provider-01")
    complete = client.post(
        org["base"] + f"/upload-sessions/{upload['id']}/complete",
        headers={**org["ch"], "Idempotency-Key": "cancel-after-provider-complete"},
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.text
    provider = app.state.storage_provider
    actual_complete = provider.complete_multipart
    canceled = []

    def complete_then_cancel(key, provider_upload_id, parts):
        result = actual_complete(key, provider_upload_id, parts)
        response = client.patch(
            org["base"] + f"/training-sessions/{session['id']}", headers=org["ch"],
            json={"status": "cancelled"},
        )
        assert response.status_code == 200, response.text
        canceled.append(True)
        return result

    monkeypatch.setattr(provider, "complete_multipart", complete_then_cancel)
    assert process_media_job(app.state.sessions, provider, app.state.settings)
    assert canceled == [True]
    with app.state.sessions() as db:
        stored_upload = db.get(UploadSession, upload["id"])
        stored_asset = db.get(VideoAsset, asset["id"])
        stored_object = db.scalar(select(MediaObject).where(MediaObject.upload_session_id == upload["id"]))
        object_candidate = db.scalar(select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.object_id == stored_object.id,
            MediaCleanupCandidate.kind == "object",
        ))
        assert (stored_upload.status, stored_upload.failure_reason) == ("failed", "session_cancelled")
        assert (stored_asset.status, stored_asset.failure_reason) == ("failed", "session_cancelled")
        assert stored_asset.storage_object_ref is None
        assert stored_object.phase == "delete_pending" and stored_object.object_version
        assert object_candidate and object_candidate.object_version == stored_object.object_version
    cleanup = cleanup_candidates(
        app.state.sessions, provider, app.state.settings, execute=True,
        now=datetime.now(UTC) + timedelta(minutes=10),
    )
    assert cleanup["failed"] == 0, cleanup
    assert cleanup["removed"] >= 1


@pytest.mark.storage
def test_orphan_discovery_paginates_observes_twice_and_deletes_only_verified_failed_objects(
    client, app, seeded_account, configured_media_app
):
    from swimplatform.media_transfer import _object_key

    org = setup_org(client, seeded_account)
    provider = app.state.storage_provider
    now = datetime.now(UTC)
    expected_objects = []
    for index in range(2):
        session = new_session(client, org, key=f"orphan-session-{index}")
        created = create_intent(client, org, session["id"], key=f"orphan-intent-{index}").json()
        upload, asset = created["upload_session"], created["asset"]
        aborted = client.post(
            org["base"] + f"/upload-sessions/{upload['id']}/abort", headers=org["ch"]
        )
        assert aborted.status_code == 204
        with app.state.sessions() as db:
            persisted_upload = db.get(UploadSession, upload["id"])
            assert persisted_upload is not None
            tenant_id, site_id, session_id = (
                persisted_upload.tenant_id, persisted_upload.site_id, persisted_upload.session_id
            )
        key = _object_key(tenant_id, site_id, session_id, asset["id"], upload["id"],
                          1, app.state.settings.media_run_id)
        put = provider.client.put_object(
            Bucket=provider.bucket, Key=key, Body=b"orphan-version",
            Metadata={"owner": "swim-platform", "purpose": "isolated-media-transfer",
                      "run-id": app.state.settings.media_run_id, "tenant-id": tenant_id,
                      "site-id": site_id, "session-id": session_id,
                      "asset-id": asset["id"], "upload-session-id": upload["id"]},
        )
        assert put.get("VersionId")
        expected_objects.append((key, put["VersionId"]))

    first = discover_orphans(app.state.sessions, provider, app.state.settings, now=now, limit=1)
    assert first["scanned_versions"] >= 2
    assert first["observed"] == 2 and first["queued"] == 0
    second = discover_orphans(
        app.state.sessions, provider, app.state.settings,
        now=now + timedelta(minutes=16), limit=1,
    )
    assert second["queued"] == 2
    dry_run = cleanup_candidates(
        app.state.sessions, provider, app.state.settings, execute=False,
        now=now + timedelta(minutes=16), limit=10,
    )
    assert dry_run["dry_run"] is True
    queued = {(item["key"], item["version_id"]) for item in dry_run["candidates"]}
    assert set(expected_objects) <= queued
    executed = cleanup_candidates(
        app.state.sessions, provider, app.state.settings, execute=True,
        now=now + timedelta(minutes=17), limit=10,
    )
    assert executed["failed"] == 0, executed
    assert executed["removed"] >= 2
    for key, version_id in expected_objects:
        with pytest.raises(StorageError):
            provider.head_object(key, version_id)
