"""应用数据库身份的权限探测（design D2）。

验证的是数据库层权限分离：应用身份能完成正常业务，但无法 DDL、建库、建角色、
临时建表、TRUNCATE、写迁移版本表或提权为迁移身份。
这不等于 RLS 行级隔离已实现。
"""
from contextlib import contextmanager

import psycopg
import pytest

from pg_support import ADMIN_USER, APP_USER, APPROVED_APP_TABLES, MIGRATION_USER, SCHEMA

pytestmark = pytest.mark.postgresql

INSUFFICIENT_PRIVILEGE = "42501"


def scalar(connection, statement: str, params=None):
    return connection.execute(statement, params).fetchone()[0]


@contextmanager
def app_connection(environment, database, *, autocommit: bool = False):
    """默认真实事务：失败后必须回滚，并确认连接仍可用。"""
    with environment.connect(
        user=environment.app_user,
        password=environment.app_password,
        database=database.name,
        autocommit=autocommit,
    ) as connection:
        yield connection


@contextmanager
def denied(connection, statement: str, params=None, *, rollback: bool = True):
    with pytest.raises(psycopg.Error) as captured:
        connection.execute(statement, params)
    assert getattr(captured.value, "sqlstate", None) == INSUFFICIENT_PRIVILEGE, captured.value
    if rollback:
        connection.rollback()
    yield


def test_application_role_attributes_and_no_migration_membership(pg_environment, pg_databases):
    database = pg_databases()
    with pg_environment.admin(database.name, search_path=SCHEMA) as connection:
        assert connection.execute(
            "SELECT rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (APP_USER,),
        ).fetchone() == (False, True, False, False, True, False, False)

        assert scalar(
            connection, "SELECT pg_has_role(%s, %s, 'MEMBER')", (APP_USER, MIGRATION_USER)
        ) is False
        assert scalar(
            connection,
            "SELECT count(*) FROM pg_auth_members m "
            "JOIN pg_roles member_role ON member_role.oid = m.member "
            "WHERE member_role.rolname = %s",
            (APP_USER,),
        ) == 0

        # 十张批准业务表加版本表共 11 张，全部归迁移身份所有。
        assert connection.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = %s", (SCHEMA,)
        ).fetchall() == [(MIGRATION_USER,)] * (len(APPROVED_APP_TABLES) + 1)
        assert scalar(
            connection,
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s",
            (SCHEMA,),
        ) == MIGRATION_USER

        assert connection.execute(
            "SELECT has_schema_privilege(%s, %s, 'USAGE'), has_schema_privilege(%s, %s, 'CREATE')",
            (APP_USER, SCHEMA, APP_USER, SCHEMA),
        ).fetchone() == (True, False)
        assert connection.execute(
            "SELECT has_database_privilege(%s, %s, 'CONNECT'), "
            "has_database_privilege(%s, %s, 'TEMPORARY'), "
            "has_database_privilege(%s, %s, 'CREATE')",
            (APP_USER, database.name, APP_USER, database.name, APP_USER, database.name),
        ).fetchone() == (True, False, False)
        assert scalar(
            connection, "SELECT has_schema_privilege(%s, 'public', 'USAGE')", (APP_USER,)
        ) is False


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE probe (id int)",
        "CREATE TEMP TABLE probe (id int)",
        "CREATE SCHEMA probe_schema",
        "CREATE INDEX probe_idx ON users (email)",
        "ALTER TABLE users ADD COLUMN probe int",
        "TRUNCATE users",
        "CREATE ROLE probe_role",
    ],
)
def test_application_cannot_run_ddl_or_privilege_escalation(pg_environment, pg_databases, statement):
    database = pg_databases()
    with app_connection(pg_environment, database) as connection:
        with denied(connection, statement):
            pass
        # 失败事务回滚后，同一连接仍能正常读取业务表。
        assert scalar(connection, "SELECT count(*) FROM users") == 0


def test_application_cannot_create_database(pg_environment, pg_databases):
    database = pg_databases()
    # CREATE DATABASE 不能进事务块，必须用 autocommit 连接，否则会先报 25001 掩盖权限结论。
    with app_connection(pg_environment, database, autocommit=True) as connection:
        with denied(connection, "CREATE DATABASE probe_database", rollback=False):
            pass
        assert scalar(connection, "SELECT count(*) FROM users") == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO alembic_version (version_num) VALUES ('probe')",
        "UPDATE alembic_version SET version_num = 'probe'",
        "DELETE FROM alembic_version",
        "TRUNCATE alembic_version",
    ],
)
def test_application_cannot_write_migration_version_table(pg_environment, pg_databases, statement):
    database = pg_databases()
    with app_connection(pg_environment, database) as connection:
        with denied(connection, statement):
            pass
        assert scalar(connection, "SELECT version_num FROM alembic_version") == "20261110_0002"


@pytest.mark.parametrize(
    "statement",
    [
        f"SET ROLE {MIGRATION_USER}",
        f"SET ROLE {ADMIN_USER}",
        f"SET SESSION AUTHORIZATION {MIGRATION_USER}",
    ],
)
def test_application_cannot_switch_to_migration_role(pg_environment, pg_databases, statement):
    database = pg_databases()
    with app_connection(pg_environment, database) as connection:
        with denied(connection, statement):
            pass
        assert scalar(connection, "SELECT current_user") == APP_USER


def test_application_can_use_business_tables_and_read_version(pg_environment, pg_databases):
    database = pg_databases()
    with app_connection(pg_environment, database) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name, password_hash, is_active, failed_logins, created_at) "
            "VALUES ('u-1', 'u-1@example.test', 'U', 'x', true, 0, now())"
        )
        connection.execute("UPDATE users SET display_name = 'U2' WHERE id = 'u-1'")
        connection.commit()
        assert scalar(connection, "SELECT display_name FROM users WHERE id = 'u-1'") == "U2"
        assert scalar(connection, "SELECT version_num FROM alembic_version") == "20261110_0002"
        connection.execute("DELETE FROM users WHERE id = 'u-1'")
        connection.commit()
        assert scalar(connection, "SELECT count(*) FROM users") == 0


def test_public_schema_is_closed_to_application(pg_environment, pg_databases):
    database = pg_databases()
    with app_connection(pg_environment, database) as connection:
        with denied(connection, "CREATE TABLE public.probe (id int)"):
            pass
        with denied(connection, "SELECT * FROM public.alembic_version"):
            pass


def test_unapproved_canary_table_is_not_granted_dml(pg_environment, pg_databases):
    database = pg_databases()
    with pg_environment.admin(database.name) as admin:
        admin.execute("CREATE TABLE swim_cloud.unapproved_canary (id integer PRIMARY KEY)")
    with pg_environment.application(database.name) as app_connection:
        with denied(app_connection, "SELECT * FROM unapproved_canary"):
            pass
        with denied(app_connection, "INSERT INTO unapproved_canary (id) VALUES (1)"):
            pass
        assert app_connection.execute("SELECT count(*) FROM edge_nodes").fetchone()[0] == 0
