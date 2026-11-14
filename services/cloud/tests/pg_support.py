"""PostgreSQL 测试支撑：实例环境、每例独立库、专用 schema 与最小授权。

本模块只在 `--cloud-backend=postgresql` 时使用。连接信息全部来自
`scripts/test-postgresql.py` 传入的进程环境；这里不读取任何业务连接变量。

两条硬约定：
1. 表与 `alembic_version` 都落在专用 schema `swim_cloud` 内，两个身份都用
   连接级 libpq `options=-c search_path=…` 定位，绝不在池化连接上执行 `SET`。
2. `CREATE DATABASE` / `DROP DATABASE` 不能进入事务块，统一使用独立的管理员
   autocommit 连接，用完即关，不与业务引擎的连接池共用。
"""
from __future__ import annotations

import os
import importlib.util
import sys
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from swimplatform.migrate import migrate_database

SCHEMA = "swim_cloud"
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}\Z")
TEST_DATABASE_PREFIX = "swim_test_"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# 与 scripts/test-postgresql.py 约定的固定角色名。
ADMIN_USER = "swim_admin"
MIGRATION_USER = "swim_migrator"
APP_USER = "swim_app"
APPROVED_APP_TABLES = (
    "users", "auth_sessions", "tenants", "tenant_memberships", "sites", "site_memberships",
    "edge_nodes", "devices", "edge_credentials", "idempotency_records",
    "training_sessions", "video_assets", "upload_sessions", "session_read_grants", "asset_read_grants",
)

# 连接池配置按用途分开：顺序复用与真实并发不能共用同一组参数。
REUSE_POOL = {"pool_size": 1, "max_overflow": 0, "pool_timeout": 5}
CONCURRENCY_POOL = {"pool_size": 8, "max_overflow": 0, "pool_timeout": 15}

ENV_KEYS = {
    "run": "SWIM_CLOUD_PG_HARNESS_RUN",
    "host": "SWIM_CLOUD_PG_HOST",
    "port": "SWIM_CLOUD_PG_PORT",
    "container_id": "SWIM_CLOUD_PG_CONTAINER_ID",
    "container_name": "SWIM_CLOUD_PG_CONTAINER_NAME",
    "owner": "SWIM_CLOUD_PG_OWNER",
    "admin_user": "SWIM_CLOUD_PG_ADMIN_USER",
    "admin_password": "SWIM_CLOUD_PG_ADMIN_PASSWORD",
    "migration_user": "SWIM_CLOUD_PG_MIGRATION_USER",
    "migration_password": "SWIM_CLOUD_PG_MIGRATION_PASSWORD",
    "app_user": "SWIM_CLOUD_PG_APP_USER",
    "app_password": "SWIM_CLOUD_PG_APP_PASSWORD",
}


class PostgresEnvironmentError(RuntimeError):
    """显式请求 PostgreSQL 但环境不完整；必须失败，不能回退 SQLite。"""


def harness_module():
    """测试初始化复用编排入口的真实 Docker 身份校验，避免两份规则漂移。"""
    name = "_swim_pg_harness"
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[3] / "scripts/test-postgresql.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _required(environment: dict[str, str], key: str) -> str:
    value = environment.get(key, "")
    if not value:
        raise PostgresEnvironmentError(f"缺少 {key}；PostgreSQL 测试不会回退到 SQLite")
    return value


@dataclass(frozen=True)
class PgDatabase:
    """本次用例专属的临时数据库及其三种身份的连接串。"""

    name: str
    app_url: str
    migration_url: str
    admin_url: str
    timezone: str | None
    migrated: bool

    def engine(self, **pool):
        return create_engine(self.app_url, pool_pre_ping=True, **pool)

    def sessions(self, **pool):
        engine = self.engine(**pool)
        return engine, sessionmaker(engine, expire_on_commit=False)


@dataclass(frozen=True)
class PgEnvironment:
    host: str
    port: int
    run_id: str
    admin_user: str
    admin_password: str
    migration_user: str
    migration_password: str
    app_user: str
    app_password: str
    container_id: str
    container_name: str
    owner: str

    @classmethod
    def from_environment(cls, environment: dict[str, str] | None = None) -> "PgEnvironment":
        source = dict(os.environ if environment is None else environment)
        run_id = _required(source, ENV_KEYS["run"])
        if not RUN_ID_PATTERN.match(run_id):
            raise PostgresEnvironmentError(
                "SWIM_CLOUD_PG_HARNESS_RUN 不是本次编排生成的 run id；拒绝连接"
            )
        host = _required(source, ENV_KEYS["host"])
        if host not in LOOPBACK_HOSTS:
            raise PostgresEnvironmentError(f"只允许回环地址的专用实例，收到 {host!r}")
        raw_port = _required(source, ENV_KEYS["port"])
        try:
            port = int(raw_port)
        except ValueError as error:
            raise PostgresEnvironmentError(f"端口不是整数：{raw_port!r}") from error
        if not 1024 <= port <= 65535:
            raise PostgresEnvironmentError(f"端口超出预期范围：{port}")
        admin_user = _required(source, ENV_KEYS["admin_user"])
        migration_user = _required(source, ENV_KEYS["migration_user"])
        app_user = _required(source, ENV_KEYS["app_user"])
        if len({admin_user, migration_user, app_user}) != 3:
            raise PostgresEnvironmentError("管理员、迁移与应用身份必须互不相同")
        result = cls(
            host=host,
            port=port,
            run_id=run_id,
            admin_user=admin_user,
            admin_password=_required(source, ENV_KEYS["admin_password"]),
            migration_user=migration_user,
            migration_password=_required(source, ENV_KEYS["migration_password"]),
            app_user=app_user,
            app_password=_required(source, ENV_KEYS["app_password"]),
            container_id=_required(source, ENV_KEYS["container_id"]),
            container_name=_required(source, ENV_KEYS["container_name"]),
            owner=_required(source, ENV_KEYS["owner"]),
        )
        result.verify_container()
        return result

    def verify_container(self) -> None:
        harness = harness_module()
        try:
            if self.owner != harness.OWNER_VALUE or self.host != "127.0.0.1":
                raise harness.HarnessError("环境中的 owner 或 host 与专用容器不一致")
            resources = harness.RunResources(self.run_id, self.container_name, self.container_id)
            harness.resolve_host_port(harness.resolve_docker(), resources)
            if resources.host_port != self.port:
                raise harness.HarnessError("环境端口与容器 5432/tcp 实际映射不一致")
        except (harness.HarnessError, LookupError) as error:
            raise PostgresEnvironmentError(f"专用容器归属核验失败，拒绝数据库连接：{error}") from error

    # ---- 连接 ----------------------------------------------------------

    def url(self, *, user: str, password: str, database: str, schema: str | None = SCHEMA) -> str:
        """构造连接串；schema 通过 libpq `options` 在建立连接时生效。"""
        query = {"options": f"-c search_path={schema}"} if schema else {}
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password,
            host=self.host,
            port=self.port,
            database=database,
            query=query,
        ).render_as_string(hide_password=False)

    @contextmanager
    def connect(
        self,
        *,
        user: str,
        password: str,
        database: str,
        search_path: str | None = SCHEMA,
        autocommit: bool = True,
    ) -> Iterator[psycopg.Connection]:
        """独立管理连接，用完即关，不进入业务连接池。

        默认 autocommit，用于建库/授权与 catalog 检查；权限探测需要真实事务时显式关闭。
        """
        options = {"options": f"-c search_path={search_path}"} if search_path else {}
        connection = psycopg.connect(
            host=self.host,
            port=self.port,
            user=user,
            password=password,
            dbname=database,
            autocommit=autocommit,
            **options,
        )
        try:
            yield connection
        finally:
            connection.close()

    def admin(self, database: str = "postgres", *, search_path: str | None = None):
        return self.connect(
            user=self.admin_user, password=self.admin_password, database=database, search_path=search_path
        )

    def migration(self, database: str):
        return self.connect(
            user=self.migration_user, password=self.migration_password, database=database
        )

    def application(self, database: str):
        return self.connect(user=self.app_user, password=self.app_password, database=database)

    def describe(self) -> dict:
        """实例环境摘要，供验证报告使用（不含凭据）。"""
        with self.admin() as connection:
            row = connection.execute(
                "SELECT current_setting('server_version'), current_setting('TimeZone'), "
                "current_setting('server_encoding')"
            ).fetchone()
        return {"server_version": row[0], "default_timezone": row[1], "server_encoding": row[2]}

    # ---- 生命周期 ------------------------------------------------------

    def create_database(
        self,
        *,
        migrate: bool = True,
        grant: bool = True,
        timezone: str | None = None,
    ) -> PgDatabase:
        """创建本次用例专属空库：专用 schema、可选库级时区、迁移与最小授权。"""
        name = TEST_DATABASE_PREFIX + secrets.token_hex(6)
        # 建库/改库属性必须在事务块外，用独立 autocommit 管理连接执行。
        with self.admin() as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            if timezone:
                # 库级默认值让每一条新建连接都继承，不需要在池化连接上 SET。
                admin.execute(
                    sql.SQL("ALTER DATABASE {} SET timezone TO {}").format(
                        sql.Identifier(name), sql.Literal(timezone)
                    )
                )
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            admin.execute(
                sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                    sql.Identifier(name),
                    sql.Identifier(self.migration_user),
                    sql.Identifier(self.app_user),
                )
            )

        with self.admin(name) as connection:
            # schema 归迁移身份所有，应用身份因此既不是表 owner 也不是 schema owner。
            connection.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                    sql.Identifier(SCHEMA), sql.Identifier(self.migration_user)
                )
            )
            # public 对所有人关闭，避免应用身份借默认路径访问非预期对象。
            connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")

        database = PgDatabase(
            name=name,
            app_url=self.url(user=self.app_user, password=self.app_password, database=name),
            migration_url=self.url(
                user=self.migration_user, password=self.migration_password, database=name
            ),
            admin_url=self.url(user=self.admin_user, password=self.admin_password, database=name),
            timezone=timezone,
            migrated=migrate,
        )
        if migrate:
            # 迁移连接带 search_path=swim_cloud，六表与 alembic_version 都落在该 schema。
            migrate_database(database.migration_url)
        if grant:
            self.grant_application(database)
        return database

    def grant_application(self, database: PgDatabase) -> None:
        """应用身份只拿 schema USAGE、明确批准的十表 DML 与版本表 SELECT。"""
        with self.admin(database.name) as connection:
            connection.execute(
                sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(SCHEMA))
            )
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(SCHEMA), sql.Identifier(self.app_user)
                )
            )
            for table in APPROVED_APP_TABLES:
                connection.execute(
                    sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {}.{} TO {}").format(
                        sql.Identifier(SCHEMA), sql.Identifier(table), sql.Identifier(self.app_user)
                    )
                )
            if database.migrated:
                version_table = sql.SQL("{}.{}").format(
                    sql.Identifier(SCHEMA), sql.Identifier("alembic_version")
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(
                        version_table, sql.Identifier(self.app_user)
                    )
                )
                connection.execute(
                    sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
                        version_table, sql.Identifier(self.app_user)
                    )
                )

    def drop_database(self, name: str) -> None:
        if not name.startswith(TEST_DATABASE_PREFIX):
            raise PostgresEnvironmentError(f"只清理本次测试库，拒绝：{name!r}")
        with self.admin() as admin:
            # 独立 autocommit 连接；调用前用例侧必须已 dispose 业务连接池。
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )

    def database_names(self) -> list[str]:
        with self.admin() as connection:
            rows = connection.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE %s",
                (TEST_DATABASE_PREFIX + "%",),
            ).fetchall()
        return sorted(row[0] for row in rows)


# ---- 并发请求 ----------------------------------------------------------


def run_concurrently(app, jobs: list[Callable], timeout: float = 60.0) -> list:
    """用同步屏障让多个请求真正同时发起；有界超时后如实失败。"""
    from fastapi.testclient import TestClient

    barrier = threading.Barrier(len(jobs))
    results: list = [None] * len(jobs)
    errors: list[BaseException | None] = [None] * len(jobs)

    def worker(index: int, job: Callable) -> None:
        client = TestClient(app)
        try:
            barrier.wait(timeout=timeout)
            results[index] = job(client)
        except BaseException as error:  # 交给调用方断言，不在线程里吞掉
            errors[index] = error
        finally:
            client.close()

    threads = [
        threading.Thread(target=worker, args=(index, job), daemon=True)
        for index, job in enumerate(jobs)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    if stuck:
        raise AssertionError(f"并发请求未在有界时间内返回：{stuck}；不能把超时当作通过")
    for error in errors:
        if error is not None:
            raise error
    return results


def new_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid4().hex[:12]}@example.test"
