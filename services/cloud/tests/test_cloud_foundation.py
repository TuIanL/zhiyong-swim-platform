from datetime import UTC, datetime, timedelta
from uuid import uuid4
import subprocess
import sys

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from swimplatform.config import ROOT, Settings
from swimplatform.main import create_app
from swimplatform.models import AuthSession, Base, SiteMembership, User
from fastapi.testclient import TestClient
from conftest import PASSWORD


def test_registration_normalizes_email_and_does_not_leak_secrets(client):
    body = {"email": " Owner@Example.Test ", "password": PASSWORD, "display_name": " Owner "}
    r = client.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201
    assert r.json()["email"] == "owner@example.test"
    assert r.json()["display_name"] == "Owner"
    assert "password" not in r.text and "hash" not in r.text
    assert client.post("/api/v1/auth/register", json=body).status_code == 409


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"role": "owner"}, {"tenant_id": str(uuid4())}, {"is_active": True}])
def test_public_registration_rejects_privileged_fields(client, extra):
    r = client.post("/api/v1/auth/register", json={"email": "new@example.test", "display_name": "New", "password": PASSWORD, **extra})
    assert r.status_code == 422


def test_password_spaces_are_not_silently_removed(client):
    password = "  " + PASSWORD + "  "
    assert client.post("/api/v1/auth/register", json={"email": "space@example.test", "password": password, "display_name": "Space"}).status_code == 201
    assert client.post("/api/v1/auth/login", json={"email": "space@example.test", "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "space@example.test", "password": password}).status_code == 200


def test_login_uses_hashed_tokens_and_logout_revokes_immediately(client, app, account):
    user, headers = account("owner")
    raw = headers["Authorization"].split()[1]
    with app.state.sessions() as db:
        stored = db.scalar(select(AuthSession))
        assert stored.token_hash != raw and len(stored.token_hash) == 64
        assert db.get(User, user["id"]).password_hash.startswith("scrypt$")
    assert client.get("/api/v1/me", headers=headers).json() == user
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_expired_and_deactivated_sessions_are_rejected(client, app, account):
    user, headers = account("owner")
    with app.state.sessions() as db:
        db.scalar(select(AuthSession)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    _, second = account("second")
    with app.state.sessions() as db:
        db.scalar(select(User).where(User.email == "second@example.test")).is_active = False
        db.commit()
    assert client.get("/api/v1/me", headers=second).status_code == 401


def test_account_lockout(client, account):
    account("owner")
    body = {"email": "owner@example.test", "password": "Wrong-Password-2026"}
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
    assert client.post("/api/v1/auth/login", json={**body, "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={**body, "email": "missing@example.test"}).status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/me", "/api/v1/tenants"])
def test_authentication_required(client, path):
    assert client.get(path).status_code == 401


def test_tenant_creation_and_cross_tenant_isolation(client, account, tenant, site):
    _, a = account("alpha")
    _, b = account("bravo")
    ta, tb = tenant(a), tenant(b, "team-b")
    sa = site(a, ta["id"])
    assert ta["role"] == "owner"
    assert [t["id"] for t in client.get("/api/v1/tenants", headers=a).json()] == [ta["id"]]
    for method, path, body in [
        ("get", f"/tenants/{ta['id']}", None),
        ("get", f"/tenants/{ta['id']}/members", None),
        ("get", f"/tenants/{ta['id']}/sites", None),
        ("get", f"/tenants/{ta['id']}/sites/{sa['id']}", None),
        ("post", f"/tenants/{ta['id']}/sites", {"name": "侵入"}),
    ]:
        assert client.request(method, "/api/v1" + path, headers=b, **({"json": body} if body else {})).status_code == 404
    assert client.get(f"/api/v1/tenants/{tb['id']}", headers=a).status_code == 404


def test_member_roles_and_site_scopes(client, account, tenant, site):
    _, owner = account("owner")
    admin_user, admin = account("admin")
    coach_user, coach = account("coach")
    t = tenant(owner)
    path = f"/api/v1/tenants/{t['id']}"
    for u, role in [(admin_user, "admin"), (coach_user, "coach")]:
        assert client.post(path + "/members", headers=owner, json={"user_id": u["id"], "role": role}).status_code == 201
    s1, s2 = site(admin, t["id"]), site(owner, t["id"], "第二训练馆")
    assert client.get(path + "/sites", headers=coach).json() == []
    assert client.get(path + f"/sites/{s1['id']}", headers=coach).status_code == 404
    assert client.post(path + "/sites", headers=coach, json={"name": "无权创建"}).status_code == 403
    assert client.post(path + f"/sites/{s1['id']}/members", headers=admin, json={"user_id": coach_user["id"]}).status_code == 201
    assert [s["id"] for s in client.get(path + "/sites", headers=coach).json()] == [s1["id"]]
    assert client.get(path + f"/sites/{s2['id']}", headers=coach).status_code == 404
    assert client.get(path + "/members", headers=coach).status_code == 403
    assert client.patch(path + f"/members/{coach_user['id']}", headers=admin, json={"role": "admin"}).status_code == 403
    assert client.patch(path + f"/members/{coach_user['id']}", headers=owner, json={"role": "admin"}).status_code == 200
    assert len(client.get(path + "/sites", headers=coach).json()) == 2


def test_owner_cannot_be_demoted_or_removed(client, account, tenant):
    user, owner = account("owner")
    t = tenant(owner)
    path = f"/api/v1/tenants/{t['id']}/members/{user['id']}"
    assert client.patch(path, headers=owner, json={"role": "coach"}).status_code == 409
    assert client.delete(path, headers=owner).status_code == 409


def test_site_grant_revoke_and_member_removal(client, account, tenant, site, app):
    _, owner = account("owner")
    u, coach = account("coach")
    t = tenant(owner)
    path = f"/api/v1/tenants/{t['id']}"
    s = site(owner, t["id"])
    grant = path + f"/sites/{s['id']}/members"
    # 不能把非机构成员直接授予场馆。
    assert client.post(grant, headers=owner, json={"user_id": u["id"]}).status_code == 404
    assert client.post(path + "/members", headers=owner, json={"user_id": u["id"], "role": "coach"}).status_code == 201
    assert client.post(grant, headers=owner, json={"user_id": u["id"]}).status_code == 201
    assert client.get(path + f"/sites/{s['id']}", headers=coach).status_code == 200
    assert client.delete(grant + "/" + u["id"], headers=owner).status_code == 204
    assert client.get(path + f"/sites/{s['id']}", headers=coach).status_code == 404
    assert client.post(grant, headers=owner, json={"user_id": u["id"]}).status_code == 201
    assert client.delete(path + "/members/" + u["id"], headers=owner).status_code == 204
    assert client.get(path + "/sites", headers=coach).status_code == 404
    with app.state.sessions() as db:
        assert db.scalar(select(SiteMembership)) is None


def test_cross_tenant_site_id_and_foreign_keys(client, app, account, tenant, site):
    user, owner = account("owner")
    ta, tb = tenant(owner), tenant(owner, "team-b")
    sb = site(owner, tb["id"])
    assert client.get(f"/api/v1/tenants/{ta['id']}/sites/{sb['id']}", headers=owner).status_code == 404
    with app.state.sessions() as db:
        db.add(SiteMembership(tenant_id=ta["id"], site_id=sb["id"], user_id=user["id"]))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_duplicate_sites_and_invalid_timezone(client, account, tenant, site):
    _, owner = account("owner")
    ta, tb = tenant(owner), tenant(owner, "team-b")
    site(owner, ta["id"])
    assert client.post(f"/api/v1/tenants/{ta['id']}/sites", headers=owner, json={"name": "第一训练馆"}).status_code == 409
    site(owner, tb["id"])
    assert client.post(f"/api/v1/tenants/{ta['id']}/sites", headers=owner, json={"name": "馆", "timezone": "invalid/place"}).status_code == 422


def test_migration_matches_models_and_ready(client, app):
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    with app.state.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261110_0002"
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_startup_never_creates_schema(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'blank.sqlite3'}"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert inspect(app.state.engine).get_table_names() == []


@pytest.mark.parametrize("target", ["sqlite:////tmp/not-the-new-project.sqlite3", "postgresql+psycopg://unused@localhost:1/unused"])
def test_cli_refuses_external_or_legacy_database(target, monkeypatch):
    monkeypatch.setenv("SWIM_CLOUD_DATABASE_URL", target)
    from swimplatform.cli import main
    monkeypatch.setattr(sys, "argv", ["swimplatform.cli", "init-db"])
    with pytest.raises(SystemExit, match="拒绝"):
        main()
