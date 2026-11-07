"""顺序连接复用（design D4）。

`pool_size=1`、`max_overflow=0`：只可能有一个物理连接，因此这里是“同一连接按顺序
处理不同身份”的证据，不是并发证据。并发场景使用 `concurrency_app`。
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from conftest import PASSWORD

pytestmark = pytest.mark.postgresql


def register(client, email):
    body = {"email": email, "password": PASSWORD, "display_name": email.split("@")[0]}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"Authorization": "Bearer " + token["access_token"]}


def test_single_pool_connection_serves_alternating_identities(reuse_pool_app):
    engine = reuse_pool_app.state.engine
    assert engine.pool.size() == 1
    assert "options=" in str(engine.url) and "search_path" in str(engine.url)

    pids: list[int] = []

    @event.listens_for(engine, "checkout")
    def _record(dbapi_connection, _record, _proxy):
        pids.append(dbapi_connection.info.backend_pid)

    with TestClient(reuse_pool_app) as client:
        alpha = register(client, "reuse-alpha@example.test")
        bravo = register(client, "reuse-bravo@example.test")
        for headers, slug in ((alpha, "team-a"), (bravo, "team-b")):
            assert client.post(
                "/api/v1/tenants", headers=headers, json={"name": slug, "slug": slug}
            ).status_code == 201

        tenant_a = client.get("/api/v1/tenants", headers=alpha).json()[0]
        tenant_b = client.get("/api/v1/tenants", headers=bravo).json()[0]
        site_a = client.post(
            f"/api/v1/tenants/{tenant_a['id']}/sites", headers=alpha, json={"name": "A馆"}
        ).json()

        # 交替 A / B / 匿名，结果必须各自只反映当前身份。
        for _ in range(2):
            assert [t["id"] for t in client.get("/api/v1/tenants", headers=alpha).json()] == [tenant_a["id"]]
            assert [t["id"] for t in client.get("/api/v1/tenants", headers=bravo).json()] == [tenant_b["id"]]
            assert client.get("/api/v1/me", headers=alpha).json()["email"] == "reuse-alpha@example.test"
            assert client.get("/api/v1/me", headers=bravo).json()["email"] == "reuse-bravo@example.test"
            assert client.get("/api/v1/tenants", headers=alpha).status_code == 200
            assert client.get("/api/v1/me").status_code == 401

            # 交叉使用机构与场馆 ID 必须被拒绝，而不是沿用上一个身份的权限。
            assert client.get(
                f"/api/v1/tenants/{tenant_a['id']}/sites/{site_a['id']}", headers=bravo
            ).status_code == 404
            assert client.get(f"/api/v1/tenants/{tenant_a['id']}", headers=bravo).status_code == 404

            # 写入失败（重复 slug）后，正常请求仍可成功。
            assert client.post(
                "/api/v1/tenants", headers=alpha, json={"name": "team-a", "slug": "team-a"}
            ).status_code == 409
            assert client.get("/api/v1/me", headers=alpha).status_code == 200

    # 整个过程只允许出现一个物理连接。
    assert len(set(pids)) == 1, pids
    assert engine.pool.checkedin() == 1
    assert engine.pool.checkedout() == 0


def test_single_pool_connection_does_not_leak_previous_tenant_rows(reuse_database, reuse_pool_app):
    """同一连接交替读取两个机构的场馆列表，不应残留上一个身份的过滤结果。"""
    with TestClient(reuse_pool_app) as client:
        alpha = register(client, "rows-alpha@example.test")
        bravo = register(client, "rows-bravo@example.test")
        heads = {}
        for headers, slug, site_name in ((alpha, "team-a", "A馆"), (bravo, "team-b", "B馆")):
            tenant = client.post(
                "/api/v1/tenants", headers=headers, json={"name": slug, "slug": slug}
            ).json()
            created = client.post(
                f"/api/v1/tenants/{tenant['id']}/sites", headers=headers, json={"name": site_name}
            ).json()
            heads[slug] = (tenant["id"], created["id"])

        for _ in range(3):
            tenant_a, site_a = heads["team-a"]
            tenant_b, site_b = heads["team-b"]
            assert [s["id"] for s in client.get(f"/api/v1/tenants/{tenant_a}/sites", headers=alpha).json()] == [site_a]
            assert [s["id"] for s in client.get(f"/api/v1/tenants/{tenant_b}/sites", headers=bravo).json()] == [site_b]

    admin_engine = create_engine(reuse_database.admin_url)
    try:
        with admin_engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM sites")).scalar() == 2
    finally:
        admin_engine.dispose()
