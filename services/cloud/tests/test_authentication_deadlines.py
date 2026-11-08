"""认证截止时间的时区独立性（design D5）。

- `sqlite` 标记：朴素 UTC 值的兼容回归，只在 SQLite 后端运行；
- `postgresql` 标记：UTC 与 Asia/Shanghai 两个独立库上的同一瞬间边界。
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from swimplatform.config import Settings
from swimplatform.main import create_app
from swimplatform.models import AuthSession, User

from conftest import PASSWORD
from pg_support import SCHEMA

EMAIL = "deadline@example.test"
UNSET = object()


@pytest.fixture
def frozen_clock(monkeypatch):
    """固定服务时钟，避免用 sleep 碰边界。"""
    fixed = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr("swimplatform.api.datetime", Frozen)
    return fixed


def login(client, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})


def set_deadlines(application, *, locked_until=UNSET, expires_at=UNSET):
    """直接改库里的截止值；只改截止时间，不动锁定次数策略。"""
    with application.state.sessions() as db:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if locked_until is not UNSET:
            user.locked_until = locked_until
            user.failed_logins = 0
        if expires_at is not UNSET:
            for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
                session.expires_at = expires_at
        db.commit()


def register(client):
    body = {"email": EMAIL, "password": PASSWORD, "display_name": "Deadline"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201


@pytest.mark.sqlite
def test_sqlite_naive_utc_deadlines_stay_compatible(client, app):
    """SQLite 存的是没有时区信息的 UTC 值，必须按既有约定解释。"""
    register(client)

    set_deadlines(app, locked_until=datetime.now(UTC) - timedelta(seconds=1))
    with app.state.sessions() as db:
        stored = db.scalar(select(User).where(User.email == EMAIL)).locked_until
    assert stored.tzinfo is None
    assert login(client).status_code == 200

    set_deadlines(app, locked_until=datetime.now(UTC) + timedelta(seconds=60))
    assert login(client).status_code == 401

    set_deadlines(app, locked_until=None)
    token = login(client)
    assert token.status_code == 200
    headers = {"Authorization": "Bearer " + token.json()["access_token"]}
    assert client.get("/api/v1/me", headers=headers).status_code == 200

    set_deadlines(app, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert client.get("/api/v1/me", headers=headers).status_code == 401


@pytest.mark.postgresql
@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai"])
def test_deadlines_are_absolute_instants_in_each_timezone(pg_databases, frozen_clock, zone):
    database = pg_databases(timezone=zone)
    application = create_app(Settings(database_url=database.app_url))
    try:
        with TestClient(application) as client:
            # 库级默认值让该库所有连接使用同一时区，未在任何连接上执行 SET。
            with application.state.engine.connect() as connection:
                assert connection.execute(text("SHOW TimeZone")).scalar() == zone
                assert connection.execute(text("SHOW search_path")).scalar() == SCHEMA

            register(client)

            # 锁定截止前 / 恰好截止 / 截止后。
            set_deadlines(application, locked_until=frozen_clock + timedelta(seconds=60))
            assert login(client).status_code == 401
            set_deadlines(application, locked_until=frozen_clock)
            assert login(client).status_code == 200
            set_deadlines(application, locked_until=frozen_clock - timedelta(seconds=1))
            assert login(client).status_code == 200

            # 会话截止前 / 恰好截止 / 截止后。
            token = login(client)
            assert token.status_code == 200
            headers = {"Authorization": "Bearer " + token.json()["access_token"]}

            set_deadlines(application, expires_at=frozen_clock + timedelta(seconds=60))
            assert client.get("/api/v1/me", headers=headers).status_code == 200
            set_deadlines(application, expires_at=frozen_clock)
            assert client.get("/api/v1/me", headers=headers).status_code == 401
            set_deadlines(application, expires_at=frozen_clock - timedelta(seconds=1))
            assert client.get("/api/v1/me", headers=headers).status_code == 401
    finally:
        application.state.engine.dispose()


@pytest.mark.postgresql
def test_reused_connection_keeps_database_timezone_and_search_path(pg_databases):
    """单连接池反复复用：时区与 schema 只来自库默认值和连接参数，没有会话残留。"""
    database = pg_databases(timezone="Asia/Shanghai")
    assert "options=" in database.app_url and "search_path" in database.app_url

    application = create_app(Settings(database_url=database.app_url))
    try:
        application.state.engine.dispose()
        engine = create_engine(database.app_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        application.state.engine = engine
        application.state.sessions = sessionmaker(engine, expire_on_commit=False)
        with TestClient(application) as client:
            for _ in range(4):
                assert client.get("/health").status_code == 200
                with engine.connect() as connection:
                    assert connection.execute(text("SHOW TimeZone")).scalar() == "Asia/Shanghai"
                    assert connection.execute(text("SHOW search_path")).scalar() == SCHEMA
                # pool_size=1：每次 checkout 都必然是同一物理连接。
                assert engine.pool.checkedin() == 1
    finally:
        application.state.engine.dispose()
