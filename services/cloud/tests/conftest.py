"""测试夹具与后端选择。

三层标记（见 design D1）：
- 无标记：共享 API 用例，SQLite 与 PostgreSQL 都运行；
- `sqlite`：只在 SQLite 有意义（朴素时间兼容、仅 SQLite 的初始化路径）；
- `postgresql`：需要专用可销毁实例（schema、权限探测、并发、连接复用）。

默认集合只跑 SQLite，不改变日常 `python -m pytest` 语义。
"""
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from swimplatform.config import Settings
from swimplatform.main import create_app
from swimplatform.migrate import migrate_database
from swimplatform.models import AuthSession, User
from swimplatform.security import password_hash, token_hash

PASSWORD = "Swimming-Platform-2026!"
BACKENDS = ("sqlite", "postgresql")
PG_ENVIRONMENT = pytest.StashKey[object]()

# 供矩阵用例直接写入账号的密码摘要：只在导入时计算一次，避免每例重复 scrypt。
SEEDED_PASSWORD_HASH = password_hash(PASSWORD)


def pytest_addoption(parser):
    parser.addoption(
        "--cloud-backend",
        action="store",
        default="sqlite",
        choices=BACKENDS,
        help="测试后端；默认只跑 SQLite，postgresql 需配合 scripts/test-postgresql.py",
    )
    parser.addoption(
        "--cloud-pg-minimum-scenarios",
        action="store",
        type=int,
        default=0,
        help="PostgreSQL 后端要求的最少必需场景数；低于此值视为收集异常",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "sqlite: 只在 SQLite 后端运行的用例"
    )
    config.addinivalue_line(
        "markers", "postgresql: 只在专用可销毁 PostgreSQL 实例上运行的用例"
    )
    if config.getoption("--cloud-backend") == "postgresql":
        # 环境不完整时必须整体失败，不能静默跳过或回退 SQLite。
        from pg_support import PgEnvironment

        # 在收集用例、创建数据库或连接 psycopg 之前验证真实 Docker 归属。
        config.stash[PG_ENVIRONMENT] = PgEnvironment.from_environment()


# PostgreSQL 后端下记录“必需场景”（全部非 sqlite 用例）及其最终结果。
PG_LEDGER = pytest.StashKey[dict]()


def pytest_collection_modifyitems(config, items):
    if config.getoption("--cloud-backend") == "postgresql":
        ledger = config.stash.setdefault(PG_LEDGER, {})
        skip = pytest.mark.skip(reason="SQLite 专属用例不在 PostgreSQL 后端运行")
        for item in items:
            if item.get_closest_marker("sqlite"):
                item.add_marker(skip)
            else:
                ledger[item.nodeid] = "collected"
        return
    skip = pytest.mark.skip(reason="需要 --cloud-backend=postgresql 与专用可销毁实例")
    for item in items:
        if item.get_closest_marker("postgresql"):
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    ledger = item.config.stash.get(PG_LEDGER, None)
    if not ledger or item.nodeid not in ledger:
        return
    if report.skipped:
        ledger[item.nodeid] = "skipped"
    elif report.failed:
        ledger[item.nodeid] = "error" if report.when == "setup" else "failed"
    elif report.when == "call" and report.passed:
        ledger[item.nodeid] = "passed"


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--cloud-backend") != "postgresql":
        return
    ledger = session.config.stash.get(PG_LEDGER, {}) or {}
    minimum = session.config.getoption("--cloud-pg-minimum-scenarios")
    problems = []
    if not ledger:
        problems.append("未收集到任何 PostgreSQL 必需场景")
    elif minimum and len(ledger) < minimum:
        problems.append(f"PostgreSQL 必需场景只收集到 {len(ledger)} 项，低于下限 {minimum}")
    for nodeid, state in sorted(ledger.items()):
        if state != "passed":
            problems.append(f"{nodeid} → {state}")
    if problems:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line("")
            reporter.write_line("PostgreSQL 必需场景未全部通过：", red=True)
            for problem in problems:
                reporter.write_line(f"  - {problem}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope="session")
def cloud_backend(request):
    return request.config.getoption("--cloud-backend")


@pytest.fixture(scope="session")
def pg_environment(cloud_backend, pytestconfig):
    if cloud_backend != "postgresql":
        pytest.skip("需要 --cloud-backend=postgresql")
    return pytestconfig.stash[PG_ENVIRONMENT]


@pytest.fixture
def pg_databases(pg_environment):
    """本次用例的 PG 临时库工厂；用例结束按创建顺序倒序精确销毁。"""
    created = []

    def make(**kwargs):
        database = pg_environment.create_database(**kwargs)
        created.append(database)
        return database

    yield make
    for database in reversed(created):
        pg_environment.drop_database(database.name)


@pytest.fixture
def app(request, cloud_backend):
    if cloud_backend == "sqlite":
        # 无任何外部连接回退；每项测试使用 pytest 独立临时库并真实执行迁移。
        url = f"sqlite:///{request.getfixturevalue('tmp_path') / 'isolated.sqlite3'}"
        migrate_database(url)
        application = create_app(Settings(database_url=url))
    else:
        database = request.getfixturevalue("pg_databases")()
        application = create_app(Settings(database_url=database.app_url))
    yield application
    application.state.engine.dispose()


def _app_with_pool(database, pool: dict):
    """用指定连接池重建应用引擎；用于区分顺序复用与真实并发场景。"""
    from sqlalchemy import create_engine

    application = create_app(Settings(database_url=database.app_url))
    application.state.engine.dispose()
    engine = create_engine(database.app_url, pool_pre_ping=True, **pool)
    application.state.engine = engine
    application.state.sessions = sessionmaker(engine, expire_on_commit=False)
    return application, engine


@pytest.fixture
def reuse_database(request, cloud_backend):
    if cloud_backend != "postgresql":
        pytest.skip("需要 --cloud-backend=postgresql")
    return request.getfixturevalue("pg_databases")()


@pytest.fixture
def reuse_pool_app(reuse_database):
    """顺序连接复用专用：pool_size=1、max_overflow=0，任何并发都会池饥饿。"""
    from pg_support import REUSE_POOL

    application, engine = _app_with_pool(reuse_database, REUSE_POOL)
    yield application
    engine.dispose()


@pytest.fixture
def concurrency_database(request, cloud_backend):
    if cloud_backend != "postgresql":
        pytest.skip("需要 --cloud-backend=postgresql")
    return request.getfixturevalue("pg_databases")()


@pytest.fixture
def concurrency_app(concurrency_database):
    """真实并发专用：pool_size=8、max_overflow=0；不复用 pool_size=1 的夹具。"""
    from pg_support import CONCURRENCY_POOL

    application, engine = _app_with_pool(concurrency_database, CONCURRENCY_POOL)
    yield application
    engine.dispose()


@pytest.fixture
def empty_database_url(request, cloud_backend):
    """未执行迁移的空库：用于验证启动不建表与 ready=503。"""
    if cloud_backend == "sqlite":
        return f"sqlite:///{request.getfixturevalue('tmp_path') / 'blank.sqlite3'}"
    return request.getfixturevalue("pg_databases")(migrate=False, grant=False).app_url


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
def seeded_account(app):
    """直接写入账号与会话；供角色矩阵使用，避免每格重复 scrypt 成本。

    注册与登录作为独立 operation 在矩阵中单独验证，这里只构造合法身份。
    """

    def create(name):
        token = secrets.token_urlsafe(32)
        with app.state.sessions() as db:
            user = User(
                email=f"{name}@example.test",
                display_name=name,
                password_hash=SEEDED_PASSWORD_HASH,
            )
            db.add(user)
            db.flush()
            db.add(
                AuthSession(
                    token_hash=token_hash(token),
                    user_id=user.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            db.commit()
            payload = {"id": user.id, "email": user.email, "display_name": user.display_name}
        return payload, {"Authorization": f"Bearer {token}"}

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
