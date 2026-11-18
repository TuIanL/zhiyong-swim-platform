"""W2: existing multipart layouts remain immutable across configuration reloads."""
from dataclasses import replace

import pytest
from sqlalchemy import select

from swimplatform.media_transfer import process_media_job
from swimplatform.models import MediaObject, UploadSession

from test_media_edge_intent import (
    activate_node, build as build_edge_org, edge_intent, make_device,
    make_session as make_edge_session,
)
from test_media_foundation import create_intent, new_session, setup_org

MIB = 1024 * 1024
SIZE = 40 * MIB


class LayoutProvider:
    profile = "layout-test"
    bucket = "layout-private"

    def __init__(self):
        self.signed = []

    def check_capabilities(self):
        return {}

    def list_multipart_uploads(self, prefix, key_marker=None, upload_marker=None):
        return {"uploads": [], "truncated": False, "key_marker": None, "upload_marker": None}

    def create_multipart(self, key, metadata):
        return "durable-multipart-upload"

    def sign_part(self, key, upload_id, part_number, expires):
        self.signed.append((key, upload_id, part_number, expires))
        return f"https://storage.invalid/{part_number}"


def initialize(app, provider):
    assert process_media_job(app.state.sessions, provider, app.state.settings)
    with app.state.sessions() as db:
        objects = db.scalars(select(MediaObject)).all()
        assert len(objects) == 1
        assert objects[0].phase == "uploading"
        assert objects[0].provider_upload_id == "durable-multipart-upload"


@pytest.mark.parametrize("backend", ["user", "edge"])
def test_frozen_layout_survives_reconfiguration_for_user_and_edge(
    client, app, seeded_account, backend
):
    provider = LayoutProvider()
    app.state.storage_provider = provider
    app.state.settings = replace(app.state.settings, media_enabled=True,
                                 media_part_size_bytes=16 * MIB)
    if backend == "user":
        org = setup_org(client, seeded_account)
        session = new_session(client, org)
        created = create_intent(
            client, org, session["id"], key="layout-user-40m",
            expected_size_bytes=SIZE, expected_sha256="a" * 64,
        )
        assert created.status_code == 201, created.text
        upload = created.json()["upload_session"]
        url = org["base"] + f"/upload-sessions/{upload['id']}/part-urls"
        first = client.post(url, headers=org["ch"], json={"part_numbers": [1]})
        assert first.status_code == 202, first.text
        headers = org["ch"]
    else:
        org = build_edge_org(client, seeded_account)
        node, token = activate_node(client, org["oh"], org["base"], key="layout-edge-node")
        device = make_device(client, org["oh"], org["base"], node["id"], key="layout-edge-device")
        session = make_edge_session(client, org)
        created = edge_intent(
            client, token, session["id"], device["id"], key="layout-edge-40m",
            expected_size_bytes=SIZE, expected_sha256="a" * 64,
        )
        assert created.status_code == 201, created.text
        upload = created.json()["upload_session"]
        url = f"/api/v1/edge/upload-sessions/{upload['id']}/part-urls"
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(url, headers=headers, json={"part_numbers": [1]})
        assert first.status_code == 202, first.text

    with app.state.sessions() as db:
        saved = db.get(UploadSession, upload["id"])
        assert (saved.part_size_bytes, saved.part_count) == (16 * MIB, 3)
    initialize(app, provider)

    # Simulate a process restart/config reload after the multipart layout is durable.
    app.state.settings = replace(app.state.settings, media_part_size_bytes=32 * MIB)
    third = client.post(url, headers=headers, json={"part_numbers": [3]})
    assert third.status_code == 200, third.text
    assert third.json()["items"][0]["part_number"] == 3
    assert third.json()["items"][0]["expected_size_bytes"] == 8 * MIB
    assert provider.signed[-1][2] == 3
    with app.state.sessions() as db:
        saved = db.get(UploadSession, upload["id"])
        assert (saved.part_size_bytes, saved.part_count) == (16 * MIB, 3)


def test_existing_physical_upload_without_layout_is_rejected(client, app, seeded_account):
    provider = LayoutProvider()
    app.state.storage_provider = provider
    app.state.settings = replace(app.state.settings, media_enabled=True,
                                 media_part_size_bytes=16 * MIB)
    org = setup_org(client, seeded_account)
    session = new_session(client, org)
    created = create_intent(
        client, org, session["id"], key="layout-missing-frozen",
        expected_size_bytes=SIZE, expected_sha256="a" * 64,
    ).json()
    upload = created["upload_session"]
    url = org["base"] + f"/upload-sessions/{upload['id']}/part-urls"
    assert client.post(url, headers=org["ch"], json={"part_numbers": [1]}).status_code == 202
    initialize(app, provider)
    with app.state.sessions() as db:
        saved = db.get(UploadSession, upload["id"])
        saved.part_size_bytes = saved.part_count = None
        db.commit()
    response = client.post(url, headers=org["ch"], json={"part_numbers": [1]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "state_conflict"
    assert not provider.signed
