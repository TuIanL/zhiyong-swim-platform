"""并发唯一写入、失败登录计数与行锁（design D5）。

全部用例使用 `pool_size=8` 的独立连接池（concurrency_app），不与顺序连接复用
的 `pool_size=1` 夹具混用；超时或池饥饿一律判失败。
"""
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from conftest import PASSWORD
from pg_support import run_concurrently

pytestmark = pytest.mark.postgresql

EMAIL = "concurrent@example.test"


def register(client, email=EMAIL):
    body = {"email": email, "password": PASSWORD, "display_name": "Concurrent"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    token = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return token["access_token"]


def record_backend_pids(engine) -> list[int]:
    pids: list[int] = []

    @event.listens_for(engine, "checkout")
    def _record(dbapi_connection, _record, _proxy):
        pids.append(dbapi_connection.info.backend_pid)

    return pids


def test_concurrent_tenant_slug_writes_leave_one_record(concurrency_app):
    with TestClient(concurrency_app) as client:
        token = register(client)
    headers = {"Authorization": f"Bearer {token}"}

    responses = run_concurrently(
        concurrency_app,
        [lambda client: client.post("/api/v1/tenants", headers=headers, json={"name": "team-a", "slug": "team-a"})] * 2,
    )
    codes = sorted(response.status_code for response in responses)
    assert codes == [201, 409], codes

    with TestClient(concurrency_app) as client:
        tenants = client.get("/api/v1/tenants", headers=headers).json()
    assert len(tenants) == 1
    assert tenants[0]["role"] == "owner"

    engine = concurrency_app.state.engine
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM tenants")).scalar() == 1
        assert connection.execute(text("SELECT count(*) FROM tenant_memberships")).scalar() == 1

    # 失败请求之后，合法写入仍然可以成功。
    with TestClient(concurrency_app) as client:
        assert client.post(
            "/api/v1/tenants", headers=headers, json={"name": "team-b", "slug": "team-b"}
        ).status_code == 201


def test_concurrent_registration_same_email(concurrency_app):
    body = {"email": "dup@example.test", "password": PASSWORD, "display_name": "Dup"}
    responses = run_concurrently(
        concurrency_app,
        [lambda client: client.post("/api/v1/auth/register", json=body)] * 2,
    )
    assert sorted(response.status_code for response in responses) == [201, 409]

    engine = concurrency_app.state.engine
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM users WHERE email = 'dup@example.test'")
        ).scalar() == 1


def test_concurrent_site_name_writes_leave_one_record(concurrency_app):
    with TestClient(concurrency_app) as client:
        token = register(client, "sites@example.test")
        headers = {"Authorization": f"Bearer {token}"}
        tenant = client.post(
            "/api/v1/tenants", headers=headers, json={"name": "team-a", "slug": "team-a"}
        ).json()

    path = f"/api/v1/tenants/{tenant['id']}/sites"
    responses = run_concurrently(
        concurrency_app,
        [lambda client: client.post(path, headers=headers, json={"name": "第一训练馆"})] * 2,
    )
    assert sorted(response.status_code for response in responses) == [201, 409]

    engine = concurrency_app.state.engine
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sites")).scalar() == 1


def test_five_concurrent_failed_logins_are_all_counted(concurrency_app):
    with TestClient(concurrency_app) as client:
        register(client)

    pids = record_backend_pids(concurrency_app.state.engine)
    wrong = lambda client: client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "Wrong-Password-2026"}
    )
    responses = run_concurrently(concurrency_app, [wrong] * 5)
    assert [response.status_code for response in responses] == [401] * 5
    # 反向证明这是真实并发：至少两个不同后端进程同时持有连接。
    assert len(set(pids)) >= 2, pids

    engine = concurrency_app.state.engine
    with engine.connect() as connection:
        failed, locked = connection.execute(
            text("SELECT failed_logins, locked_until FROM users WHERE email = :email"), {"email": EMAIL}
        ).fetchone()
    assert failed == 5
    assert locked is not None

    with TestClient(concurrency_app) as client:
        assert client.post(
            "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
        ).status_code == 401


def test_login_waits_for_row_lock_and_continues(concurrency_app, concurrency_database, pg_environment):
    with TestClient(concurrency_app) as client:
        register(client)

    holder_engine = create_engine(concurrency_database.admin_url)
    holder = holder_engine.connect()
    holder.execute(text("SELECT id FROM users WHERE email = :email FOR UPDATE"), {"email": EMAIL})

    result: dict = {}
    done = threading.Event()

    def attempt():
        client = TestClient(concurrency_app)
        try:
            result["response"] = client.post(
                "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
            )
        finally:
            client.close()
            done.set()

    thread = threading.Thread(target=attempt, daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 10
        waiting = 0
        while time.monotonic() < deadline and not done.is_set():
            with pg_environment.admin() as connection:
                waiting = connection.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = %s AND wait_event_type = 'Lock'",
                    (concurrency_database.name,),
                ).fetchone()[0]
            if waiting:
                break
            time.sleep(0.05)
        # 必须真的观察到后端在等锁，而不是“恰好没返回”。
        assert waiting >= 1, "未观察到等待行锁的后端"
        assert not done.is_set(), "请求在锁未释放前已返回"
    finally:
        holder.rollback()
        holder.close()
        holder_engine.dispose()

    assert done.wait(20), "释放锁后请求仍未返回"
    thread.join(timeout=5)
    assert result["response"].status_code == 200
