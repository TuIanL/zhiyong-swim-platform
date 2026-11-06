import pytest
from fastapi.testclient import TestClient
from swimplatform.config import Settings
from swimplatform.main import create_app
from swimplatform.migrate import migrate_database

PASSWORD = "Swimming-Platform-2026!"


@pytest.fixture
def app(tmp_path):
    # 无任何外部连接回退；每项测试使用 pytest 独立临时库并真实执行迁移。
    url = f"sqlite:///{tmp_path / 'isolated.sqlite3'}"
    migrate_database(url)
    app = create_app(Settings(database_url=url))
    yield app
    app.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def account(client):
    def create(name):
        email = f"{name}@example.test"
        r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "display_name": name})
        assert r.status_code == 201, r.text
        user = r.json()
        r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return user, {"Authorization": "Bearer " + r.json()["access_token"]}
    return create


@pytest.fixture
def tenant(client):
    def create(headers, slug="team-a"):
        r = client.post("/api/v1/tenants", headers=headers, json={"name": slug, "slug": slug})
        assert r.status_code == 201, r.text
        return r.json()
    return create


@pytest.fixture
def site(client):
    def create(headers, tenant_id, name="第一训练馆"):
        r = client.post(f"/api/v1/tenants/{tenant_id}/sites", headers=headers, json={"name": name})
        assert r.status_code == 201, r.text
        return r.json()
    return create
