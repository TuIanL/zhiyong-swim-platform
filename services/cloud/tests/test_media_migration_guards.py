"""迁移守卫：已发布迁移不变、SQLite 重建回滚、PostgreSQL 受控中断回滚。"""
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from swimplatform.config import ROOT

VERSIONS = ROOT / "services/cloud/src/swimplatform/migrations/versions"
BASE_REVISION = "20261106_0001"
REGISTRY_REVISION = "20261110_0002"
HEAD_REVISION = "20261112_0003"

# 已发布的 0001/0002 不允许被改写；本轮只新增 0003。
PUBLISHED_DIGESTS = {
    "20261106_0001_cloud_identity.py": "6a4659cd493aa242deebc70ca13952c43a55c72316c328ef5693cb8380f4ff22",
    "20261110_0002_cloud_edge_registry.py": "11c957cbff22f83f60cc63fae1fd7531b98ec5a06d01e484cd09a7ca48cfe2bd",
}


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/cloud/src/swimplatform/migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def columns(url: str, table: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_published_migrations_are_unchanged():
    for name, digest in PUBLISHED_DIGESTS.items():
        content = (VERSIONS / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest, f"{name} 已被改写"


@pytest.mark.sqlite
def test_sqlite_rebuild_failure_rolls_back_table_and_version(tmp_path):
    url = f"sqlite:///{tmp_path / 'rebuild.sqlite3'}"
    config = alembic_config(url)
    command.upgrade(config, REGISTRY_REVISION)

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            now = datetime.now(UTC)
            connection.execute(text(
                "INSERT INTO tenants (id, name, slug, created_at) VALUES ('t-1','T','t-1', :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO sites (id, tenant_id, name, address, timezone, created_at) "
                "VALUES ('s-1','t-1','S1','','UTC', :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
                "VALUES ('u-1','legacy@example.test','L','x',1,0, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO idempotency_records "
                "(id, tenant_id, site_id, user_id, operation, target_id, key_hash, request_hash, "
                " resource_kind, resource_id, created_at) "
                "VALUES ('i-1','t-1','s-1','u-1','edge_node.create','s-1',:key,:request,'edge_node','r-1', :now)"
            ), {"key": "a" * 64, "request": "b" * 64, "now": now})
            # 制造重建阶段的真实冲突：目标临时表已存在。
            connection.execute(text("CREATE TABLE idempotency_records_new (id TEXT PRIMARY KEY)"))
    finally:
        engine.dispose()

    with pytest.raises(Exception):
        command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalar_one() == REGISTRY_REVISION
            assert connection.execute(text(
                "SELECT count(*) FROM idempotency_records"
            )).scalar_one() == 1
            assert set(inspect(connection).get_table_names()) == {
                "alembic_version", "users", "auth_sessions", "tenants", "tenant_memberships",
                "sites", "site_memberships", "edge_nodes", "devices", "edge_credentials",
                "idempotency_records", "idempotency_records_new",
            }
        # 旧表结构未被部分改写：重建失败后不得留下 actor_kind 列。
        assert "actor_kind" not in columns(url, "idempotency_records")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE idempotency_records_new"))
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert "actor_kind" in columns(url, "idempotency_records")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalar_one() == HEAD_REVISION
            assert connection.execute(text(
                "SELECT key_hash FROM idempotency_records"
            )).scalar_one() == "a" * 64
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_postgres_interrupted_idempotency_extension_rolls_back(pg_databases, pg_environment):
    database = pg_databases(migrate=False, grant=False)
    config = alembic_config(database.migration_url)
    command.upgrade(config, REGISTRY_REVISION)

    admin_engine = create_engine(database.admin_url)
    try:
        with admin_engine.begin() as connection:
            # 回填之后、索引替换之前失败：同名索引已存在。
            connection.execute(text(
                "CREATE INDEX uq_idempotency_user_scope_key ON swim_cloud.idempotency_records (id)"
            ))
        with pytest.raises(Exception):
            command.upgrade(config, "head")

        with admin_engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM swim_cloud.alembic_version"
            )).scalar_one() == REGISTRY_REVISION
            assert connection.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'swim_cloud' AND table_name = 'idempotency_records' "
                "AND column_name IN ('actor_kind', 'edge_node_id')"
            )).scalar_one() == 0
            assert connection.execute(text(
                "SELECT to_regclass('swim_cloud.training_sessions') IS NULL"
            )).scalar_one()
        with admin_engine.begin() as connection:
            connection.execute(text("DROP INDEX swim_cloud.uq_idempotency_user_scope_key"))

        command.upgrade(config, "head")
        with admin_engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM swim_cloud.alembic_version"
            )).scalar_one() == HEAD_REVISION
            assert connection.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'swim_cloud' AND table_name = 'idempotency_records' "
                "AND column_name IN ('actor_kind', 'edge_node_id')"
            )).scalar_one() == 2
    finally:
        admin_engine.dispose()
    pg_environment.grant_application(database)
