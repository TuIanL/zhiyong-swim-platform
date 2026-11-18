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
HEAD_REVISION = "20261114_0004"

# 已发布的 0001–0003 不允许被改写；本轮只新增 0004。
PUBLISHED_DIGESTS = {
    "20261106_0001_cloud_identity.py": "6a4659cd493aa242deebc70ca13952c43a55c72316c328ef5693cb8380f4ff22",
    "20261110_0002_cloud_edge_registry.py": "11c957cbff22f83f60cc63fae1fd7531b98ec5a06d01e484cd09a7ca48cfe2bd",
    "20261112_0003_cloud_session_asset.py": "0c830b7c901683b7f03cde8e7d1a966c24bc9c530b0fe5b623a868b409f89f77",
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
def test_sqlite_foreign_keys_stay_enabled_during_explicit_migration(tmp_path, monkeypatch):
    """在 Alembic 实际使用的 SQLite 连接上核对连接、事务和完成后的 FK 状态。"""
    import sqlite3
    import sqlalchemy
    from sqlalchemy import event

    url = f"sqlite:///{tmp_path / 'foreign-keys.sqlite3'}"
    config = alembic_config(url)
    command.upgrade(config, REGISTRY_REVISION)

    observed = {
        "before_transaction": None,
        "inside_transaction": None,
        "inside_transaction_active": False,
        "inside_transaction_violation_rejected": False,
        "after_migration_connection": None,
        "after_migration_transaction_active": None,
    }
    original_factory = sqlalchemy.engine_from_config

    def observed_engine_factory(*args, **kwargs):
        engine = original_factory(*args, **kwargs)
        probing = {"active": False}

        @event.listens_for(engine, "after_cursor_execute")
        def inspect_migration_connection(connection, cursor, statement, parameters, context, executemany):
            if probing["active"]:
                return
            normalized = " ".join(statement.upper().split())
            if normalized == "PRAGMA FOREIGN_KEYS=ON":
                probing["active"] = True
                try:
                    dbapi_connection = connection.connection.driver_connection
                    observed["before_transaction"] = dbapi_connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                finally:
                    probing["active"] = False
            elif normalized == "BEGIN":
                probing["active"] = True
                try:
                    dbapi_connection = connection.connection.driver_connection
                    observed["inside_transaction"] = dbapi_connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                    observed["inside_transaction_active"] = dbapi_connection.in_transaction
                finally:
                    probing["active"] = False
            elif normalized.startswith("UPDATE ALEMBIC_VERSION") and not observed[
                "inside_transaction_violation_rejected"
            ]:
                probing["active"] = True
                try:
                    dbapi_connection = connection.connection.driver_connection
                    assert dbapi_connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
                    dbapi_connection.execute("SAVEPOINT fk_probe")
                    try:
                        dbapi_connection.execute(
                            "INSERT INTO training_sessions "
                            "(id, tenant_id, site_id, created_by_user_id, status, created_at, updated_at) "
                            "VALUES ('fk-probe', 'missing-tenant', 'missing-site', 'missing-user', "
                            "'planned', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
                        )
                    except sqlite3.IntegrityError:
                        dbapi_connection.execute("ROLLBACK TO fk_probe")
                        dbapi_connection.execute("RELEASE fk_probe")
                        observed["inside_transaction_violation_rejected"] = True
                    else:
                        dbapi_connection.execute("ROLLBACK TO fk_probe")
                        dbapi_connection.execute("RELEASE fk_probe")
                finally:
                    probing["active"] = False

        @event.listens_for(engine, "close")
        def inspect_connection_after_migration(dbapi_connection, connection_record):
            observed["after_migration_connection"] = dbapi_connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0]
            observed["after_migration_transaction_active"] = dbapi_connection.in_transaction

        return engine

    monkeypatch.setattr(sqlalchemy, "engine_from_config", observed_engine_factory)
    command.upgrade(config, "head")

    assert observed == {
        "before_transaction": 1,
        "inside_transaction": 1,
        "inside_transaction_active": True,
        "inside_transaction_violation_rejected": True,
        "after_migration_connection": 1,
        "after_migration_transaction_active": False,
    }


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


@pytest.mark.sqlite
def test_m3_interrupted_sqlite_parent_rebuild_rolls_back_then_retries(tmp_path):
    url = f"sqlite:///{tmp_path / 'm3-interrupted.sqlite3'}"
    config = alembic_config(url)
    command.upgrade(config, REGISTRY_REVISION)
    command.upgrade(config, HEAD_REVISION)
    command.downgrade(config, "20261112_0003")

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE _alembic_tmp_video_assets (id TEXT PRIMARY KEY)"))
        with pytest.raises(Exception):
            command.upgrade(config, HEAD_REVISION)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261112_0003"
            assert "storage_object_ref" not in columns(url, "video_assets")
            assert "part_size_bytes" not in columns(url, "upload_sessions")
            names = set(inspect(connection).get_table_names())
            assert not names.intersection({"media_objects", "upload_parts", "media_jobs", "media_cleanup_candidates"})
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE _alembic_tmp_video_assets"))
        command.upgrade(config, HEAD_REVISION)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD_REVISION
            assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()


@pytest.mark.sqlite
def test_m3_upgrade_preserves_legacy_asset_upload_grants_and_idempotency(tmp_path):
    from uuid import uuid4

    url = f"sqlite:///{tmp_path / 'm3-history.sqlite3'}"
    config = alembic_config(url)
    command.upgrade(config, "20261112_0003")
    ids = {name: str(uuid4()) for name in ("tenant", "site", "user", "grantee", "session", "asset", "upload", "sg", "ag", "idem")}
    now = "2026-11-12T10:00:00+00:00"
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id,email,display_name,password_hash,is_active,failed_logins,created_at) "
                "VALUES (:id,'owner@history.test','Owner','x',1,0,:now)"
            ), {"id": ids["user"], "now": now})
            connection.execute(text(
                "INSERT INTO users (id,email,display_name,password_hash,is_active,failed_logins,created_at) "
                "VALUES (:id,'grantee@history.test','Grantee','x',1,0,:now)"
            ), {"id": ids["grantee"], "now": now})
            connection.execute(text("INSERT INTO tenants (id,name,slug,created_at) VALUES (:id,'T','history-t',:now)"),
                               {"id": ids["tenant"], "now": now})
            connection.execute(text(
                "INSERT INTO sites (id,tenant_id,name,address,timezone,created_at) VALUES (:id,:tenant,'S','','UTC',:now)"
            ), {"id": ids["site"], "tenant": ids["tenant"], "now": now})
            connection.execute(text(
                "INSERT INTO training_sessions (id,tenant_id,site_id,created_by_user_id,title,status,created_at,updated_at) "
                "VALUES (:id,:tenant,:site,:user,'History','planned',:now,:now)"
            ), {"id": ids["session"], "tenant": ids["tenant"], "site": ids["site"], "user": ids["user"], "now": now})
            connection.execute(text(
                "INSERT INTO video_assets (id,tenant_id,site_id,session_id,origin,created_by_user_id,status,"
                "device_capture_started_at_raw,device_capture_ended_at_raw,device_time_basis,video_timebase_kind,"
                "device_clock_source,size_bytes,media_type,created_at,updated_at) "
                "VALUES (:id,:tenant,:site,:session,'manual',:user,'pending_upload',:raw_start,:raw_end,'unknown',"
                "'relative','unknown',4096,'video/mp4',:now,:now)"
            ), {"id": ids["asset"], "tenant": ids["tenant"], "site": ids["site"], "session": ids["session"],
                "user": ids["user"], "raw_start": "  old camera start  ", "raw_end": " old camera end ", "now": now})
            connection.execute(text(
                "INSERT INTO upload_sessions (id,tenant_id,site_id,session_id,asset_id,status,initiator_user_id,"
                "expected_size_bytes,expected_sha256,media_type,expires_at,created_at,updated_at) "
                "VALUES (:id,:tenant,:site,:session,:asset,'uploading',:user,4096,:sha,'video/mp4',:expires,:now,:now)"
            ), {"id": ids["upload"], "tenant": ids["tenant"], "site": ids["site"], "session": ids["session"],
                "asset": ids["asset"], "user": ids["user"], "sha": "a"*64,
                "expires": "2026-11-13T10:00:00+00:00", "now": now})
            for table, row_id, values in (
                ("session_read_grants", ids["sg"], ("session_id", ids["session"])),
                ("asset_read_grants", ids["ag"], ("asset_id", ids["asset"])),
            ):
                extra_col, extra_val = values
                columns_sql = "id,tenant_id,site_id," + ("session_id," if table == "session_read_grants" else "session_id,asset_id,")
                values_sql = ":id,:tenant,:site," + (":resource," if table == "session_read_grants" else ":session,:resource,")
                if table == "asset_read_grants":
                    resource_value = ids["asset"]
                else:
                    resource_value = ids["session"]
                connection.execute(text(
                    f"INSERT INTO {table} ({columns_sql}grantee_user_id,granted_by_user_id,granted_at,updated_at) "
                    f"VALUES ({values_sql}:grantee,:grantor,:now,:now)"
                ), {"id": row_id, "tenant": ids["tenant"], "site": ids["site"], "session": ids["session"],
                    "resource": resource_value, "grantee": ids["grantee"], "grantor": ids["user"], "now": now})
            connection.execute(text(
                "INSERT INTO idempotency_records (id,tenant_id,site_id,actor_kind,user_id,operation,target_id,key_hash,"
                "request_hash,resource_kind,resource_id,created_at) "
                "VALUES (:id,:tenant,:site,'user',:user,'upload_intent.create',:target,:key,:request,'upload_session',:resource,:now)"
            ), {"id": ids["idem"], "tenant": ids["tenant"], "site": ids["site"], "user": ids["user"],
                "target": ids["session"], "key": "b"*64, "request": "c"*64,
                "resource": ids["upload"], "now": now})

        with engine.connect() as connection:
            before = {
                table: [dict(row) for row in connection.execute(text(f"SELECT * FROM {table}" )).mappings()]
                for table in ("video_assets", "upload_sessions", "session_read_grants", "asset_read_grants", "idempotency_records")
            }
        command.upgrade(config, HEAD_REVISION)
        with engine.connect() as connection:
            for table, rows in before.items():
                after = [dict(row) for row in connection.execute(text(f"SELECT * FROM {table}" )).mappings()]
                for old, new in zip(rows, after, strict=True):
                    assert {key: new[key] for key in old} == old, table
            assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
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
