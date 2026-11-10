"""PostgreSQL 六表基线及十表head迁移、schema落点与约束验证。

全部用例只在专用可销毁实例上运行；每个用例使用独立空库。
"""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from swimplatform.config import ROOT, Settings
from swimplatform.main import create_app
from swimplatform.migrate import migrate_database
from swimplatform.models import Base

from conftest import PASSWORD
from pg_support import SCHEMA

pytestmark = pytest.mark.postgresql

BASE_REVISION = "20261106_0001"
REVISION = "20261110_0002"
TABLES = {"users", "auth_sessions", "tenants", "tenant_memberships", "sites", "site_memberships"}
REGISTRY_TABLES = {"edge_nodes", "devices", "edge_credentials", "idempotency_records"}


def alembic_config(url: str) -> Config:
    """与 swimplatform.migrate 相同的定位方式；仅测试需要 downgrade 入口。"""
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/cloud/src/swimplatform/migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def render_type(column_type) -> str:
    # 反射出的 TIMESTAMP 的 str() 不含时区信息，需要单独取值判断。
    if isinstance(column_type, DateTime) and column_type.timezone:
        return "TIMESTAMP WITH TIME ZONE"
    return str(column_type)


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_revision_and_version_table_live_in_dedicated_schema(pg_databases):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW search_path")).scalar() == SCHEMA
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == REVISION
            # 版本表必须落在专用 schema，而不是偶然落到 public。
            locations = connection.execute(
                text(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name = ANY(:names)"
                ),
                {"names": sorted(TABLES | REGISTRY_TABLES | {"alembic_version"})},
            ).scalars().all()
            assert set(locations) == {SCHEMA}
            public_tables = connection.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            ).scalar()
            assert public_tables == 0
    finally:
        engine.dispose()


def test_six_tables_columns_and_nullability(pg_databases):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        inspector = inspect(engine)
        assert TABLES | REGISTRY_TABLES | {"alembic_version"} == set(inspector.get_table_names())

        expected = {
            "users": [
                ("id", "VARCHAR(36)", False),
                ("email", "VARCHAR(255)", False),
                ("display_name", "VARCHAR(80)", False),
                ("password_hash", "VARCHAR(255)", False),
                ("is_active", "BOOLEAN", False),
                ("failed_logins", "INTEGER", False),
                ("locked_until", "TIMESTAMP WITH TIME ZONE", True),
                ("created_at", "TIMESTAMP WITH TIME ZONE", False),
            ],
            "sites": [
                ("id", "VARCHAR(36)", False),
                ("tenant_id", "VARCHAR(36)", False),
                ("name", "VARCHAR(120)", False),
                ("address", "VARCHAR(300)", False),
                ("timezone", "VARCHAR(64)", False),
                ("created_at", "TIMESTAMP WITH TIME ZONE", False),
            ],
        }
        for table, columns in expected.items():
            actual = [
                (column["name"], render_type(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            ]
            assert actual == columns, table
    finally:
        engine.dispose()


def test_primary_unique_and_explicit_indexes(pg_databases):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        inspector = inspect(engine)
        primary_keys = {
            table: inspector.get_pk_constraint(table)["constrained_columns"] for table in TABLES
        }
        assert primary_keys == {
            "users": ["id"],
            "auth_sessions": ["token_hash"],
            "tenants": ["id"],
            "tenant_memberships": ["tenant_id", "user_id"],
            "sites": ["id"],
            "site_memberships": ["tenant_id", "site_id", "user_id"],
        }

        uniques = sorted(
            (table, tuple(constraint["column_names"]))
            for table in TABLES
            for constraint in inspector.get_unique_constraints(table)
        )
        assert uniques == [
            ("sites", ("tenant_id", "id")),
            ("sites", ("tenant_id", "name")),
            ("tenants", ("slug",)),
            ("users", ("email",)),
        ]

        # 显式索引 3 个；唯一约束背后的索引不算显式声明的业务索引。
        indexes = sorted(
            (table, index["name"], tuple(index["column_names"]))
            for table in TABLES
            for index in inspector.get_indexes(table)
            if not index.get("duplicates_constraint")
        )
        assert indexes == [
            ("auth_sessions", "ix_auth_sessions_expires_at", ("expires_at",)),
            ("auth_sessions", "ix_auth_sessions_user_id", ("user_id",)),
            ("sites", "ix_sites_tenant_id", ("tenant_id",)),
        ]
    finally:
        engine.dispose()


def test_foreign_keys_include_composites_and_cascade(pg_databases):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        inspector = inspect(engine)
        found = sorted(
            (
                table,
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk["options"] or {}).get("ondelete"),
            )
            for table in TABLES
            for fk in inspector.get_foreign_keys(table)
        )
        assert found == [
            ("auth_sessions", ("user_id",), "users", ("id",), "CASCADE"),
            ("site_memberships", ("tenant_id", "site_id"), "sites", ("tenant_id", "id"), "CASCADE"),
            ("site_memberships", ("tenant_id", "user_id"), "tenant_memberships", ("tenant_id", "user_id"), "CASCADE"),
            ("sites", ("tenant_id",), "tenants", ("id",), "CASCADE"),
            ("tenant_memberships", ("tenant_id",), "tenants", ("id",), "CASCADE"),
            ("tenant_memberships", ("user_id",), "users", ("id",), "CASCADE"),
        ]
    finally:
        engine.dispose()


def test_migration_matches_models_after_reflection(pg_databases):
    database = pg_databases()
    engine = create_engine(database.migration_url)
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        engine.dispose()


def test_incremental_revision_preserves_base_data_and_can_downgrade_to_base(pg_databases, pg_environment):
    database = pg_databases()
    config = alembic_config(database.migration_url)
    seed_engine = create_engine(database.app_url)
    try:
        with seed_engine.begin() as connection:
            seed(connection)
            connection.execute(text(
                "INSERT INTO sites (id,tenant_id,name,address,timezone,created_at) "
                "VALUES ('s-2','t-1','s-2','','UTC',now())"
            ))
    finally:
        seed_engine.dispose()

    command.downgrade(config, BASE_REVISION)
    assert table_names(database.migration_url) == TABLES | {"alembic_version"}
    base_engine = create_engine(database.migration_url)
    try:
        with base_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == BASE_REVISION
            assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM sites")).scalar_one() == 2
    finally:
        base_engine.dispose()

    migrate_database(database.migration_url)
    pg_environment.grant_application(database)
    assert table_names(database.migration_url) == TABLES | REGISTRY_TABLES | {"alembic_version"}
    head_engine = create_engine(database.app_url)
    try:
        with head_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
            assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM sites")).scalar_one() == 2
    finally:
        head_engine.dispose()


SEED = [
    text(
        "INSERT INTO users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
        "VALUES ('u-1', 'u-1@example.test', 'U', 'x', true, 0, now())"
    ),
    text("INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-1', 'T1', 't-1', now())"),
    text(
        "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
        "VALUES ('s-1', 't-1', 's-1', '', 'Asia/Shanghai', now())"
    ),
    text("INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ('t-1', 'u-1', 'owner')"),
]


def seed(connection):
    for statement in SEED:
        connection.execute(statement)


def test_unique_constraints_reject_duplicates_without_residue(pg_databases):
    database = pg_databases()
    engine = create_engine(database.app_url)
    try:
        with engine.begin() as connection:
            seed(connection)
        duplicates = [
            "INSERT INTO users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
            "VALUES ('u-2', 'u-1@example.test', 'U2', 'x', true, 0, now())",
            "INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-2', 'T2', 't-1', now())",
            "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
            "VALUES ('s-2', 't-1', 's-1', '', 'Asia/Shanghai', now())",
            "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ('t-1', 'u-1', 'coach')",
        ]
        with engine.connect() as connection:
            for statement in duplicates:
                with pytest.raises(IntegrityError):
                    connection.execute(text(statement))
                connection.rollback()
            # 同机构同名被拒之后，不同机构的同名场馆仍然允许。
            connection.execute(
                text("INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-3', 'T3', 't-3', now())")
            )
            connection.execute(
                text(
                    "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
                    "VALUES ('s-3', 't-3', 's-1', '', 'Asia/Shanghai', now())"
                )
            )
            connection.commit()
            assert connection.execute(text("SELECT count(*) FROM sites")).scalar() == 2
    finally:
        engine.dispose()


def test_composite_foreign_keys_reject_cross_tenant_references(pg_databases):
    database = pg_databases()
    engine = create_engine(database.app_url)
    try:
        with engine.begin() as connection:
            seed(connection)
            connection.execute(
                text("INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-9', 'T9', 't-9', now())")
            )
            connection.execute(
                text(
                    "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
                    "VALUES ('s-9', 't-9', 's-9', '', 'Asia/Shanghai', now())"
                )
            )
        with engine.connect() as connection:
            # 机构 t-1 的授权不能引用机构 t-9 的场馆。
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO site_memberships (tenant_id, site_id, user_id) "
                        "VALUES ('t-1', 's-9', 'u-1')"
                    )
                )
            connection.rollback()
            # 也不能引用不属于该机构的成员关系。
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO site_memberships (tenant_id, site_id, user_id) "
                        "VALUES ('t-9', 's-9', 'u-1')"
                    )
                )
            connection.rollback()
            assert connection.execute(text("SELECT count(*) FROM site_memberships")).scalar() == 0
    finally:
        engine.dispose()


def test_cascading_removal_keeps_unrelated_tenants(pg_databases):
    database = pg_databases()
    engine = create_engine(database.app_url)
    try:
        with engine.begin() as connection:
            seed(connection)
            connection.execute(
                text("INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-2', 'T2', 't-2', now())")
            )
            connection.execute(
                text(
                    "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
                    "VALUES ('s-2', 't-2', 's-2', '', 'Asia/Shanghai', now())"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO site_memberships (tenant_id, site_id, user_id) "
                    "VALUES ('t-1', 's-1', 'u-1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions (token_hash, user_id, expires_at, created_at) "
                    "VALUES ('hash-1', 'u-1', now() + interval '1 hour', now())"
                )
            )
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = 't-1'"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM site_memberships")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM sites WHERE tenant_id = 't-2'")).scalar() == 1
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM tenants WHERE id = 't-1'"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM sites WHERE tenant_id = 't-1'")).scalar() == 0
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id = 'u-1'"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM auth_sessions")).scalar() == 0
    finally:
        engine.dispose()


def test_downgrade_and_upgrade_roundtrip(pg_databases, pg_environment):
    database = pg_databases()
    config = alembic_config(database.migration_url)
    command.downgrade(config, "base")
    # 六张业务表移除；alembic_version 为空表属于 Alembic 的既有行为，不做额外清理。
    assert table_names(database.migration_url) == {"alembic_version"}

    migrate_database(database.migration_url)
    # 迁移脚本不管理对象权限：重建表后必须重新授权，这一点在验证报告中如实记录。
    pg_environment.grant_application(database)
    assert table_names(database.migration_url) == TABLES | REGISTRY_TABLES | {"alembic_version"}

    application = create_app(Settings(database_url=database.app_url))
    try:
        with TestClient(application) as client:
            assert client.get("/ready").status_code == 200
            body = {"email": "roundtrip@example.test", "password": PASSWORD, "display_name": "Roundtrip"}
            assert client.post("/api/v1/auth/register", json=body).status_code == 201
            token = client.post(
                "/api/v1/auth/login", json={"email": body["email"], "password": PASSWORD}
            ).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            tenant = client.post(
                "/api/v1/tenants", headers=headers, json={"name": "team-a", "slug": "team-a"}
            )
            assert tenant.status_code == 201
            created = client.post(
                f"/api/v1/tenants/{tenant.json()['id']}/sites", headers=headers, json={"name": "第一训练馆"}
            )
            assert created.status_code == 201
    finally:
        application.state.engine.dispose()


def test_interrupted_migration_rolls_back_ddl_and_version(pg_databases):
    database = pg_databases(migrate=False, grant=False)
    admin_engine = create_engine(database.admin_url)
    try:
        with admin_engine.begin() as connection:
            # 预置同名对象制造真实冲突：upgrade 在创建第五张表时失败。
            connection.execute(text("CREATE TABLE sites (id text PRIMARY KEY)"))

        with pytest.raises(Exception):
            migrate_database(database.migration_url)

        assert table_names(database.migration_url) == {"sites"}
        with admin_engine.connect() as connection:
            assert connection.execute(
                text("SELECT to_regclass('swim_cloud.alembic_version') IS NOT NULL")
            ).scalar() is False
        with admin_engine.begin() as connection:
            connection.execute(text("DROP TABLE sites"))

        # 移除冲突对象后可以正常升级，说明失败没有留下不可恢复状态。
        migrate_database(database.migration_url)
        assert table_names(database.migration_url) == TABLES | REGISTRY_TABLES | {"alembic_version"}
    finally:
        admin_engine.dispose()


def test_interrupted_registry_migration_rolls_back_new_ddl_and_keeps_base_revision(pg_databases):
    database = pg_databases(migrate=False, grant=False)
    config = alembic_config(database.migration_url)
    command.upgrade(config, BASE_REVISION)
    admin_engine = create_engine(database.admin_url)
    try:
        with admin_engine.begin() as connection:
            # Force failure after edge_nodes has been created inside the new migration.
            connection.execute(text("CREATE TABLE swim_cloud.devices (id text PRIMARY KEY)"))
        with pytest.raises(Exception):
            migrate_database(database.migration_url)
        assert table_names(database.migration_url) == TABLES | {"devices", "alembic_version"}
        with admin_engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM swim_cloud.alembic_version")
            ).scalar_one() == BASE_REVISION
            assert connection.execute(
                text("SELECT to_regclass('swim_cloud.edge_nodes') IS NULL")
            ).scalar_one()
        with admin_engine.begin() as connection:
            connection.execute(text("DROP TABLE swim_cloud.devices"))
        migrate_database(database.migration_url)
        assert table_names(database.migration_url) == TABLES | REGISTRY_TABLES | {"alembic_version"}
    finally:
        admin_engine.dispose()


def test_ready_semantics_on_empty_and_migrated_database(empty_database_url, pg_databases):
    blank = create_app(Settings(database_url=empty_database_url))
    try:
        with TestClient(blank) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 503
    finally:
        blank.state.engine.dispose()

    database = pg_databases()
    migrated = create_app(Settings(database_url=database.app_url))
    try:
        with TestClient(migrated) as client:
            assert client.get("/ready").status_code == 200
    finally:
        migrated.state.engine.dispose()
