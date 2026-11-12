"""新Edge Registry四表的跨后端约束与历史归属检查。"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

TABLES = {
    "users", "auth_sessions", "tenants", "tenant_memberships", "sites", "site_memberships",
    "edge_nodes", "devices", "edge_credentials", "idempotency_records",
}


def seed_scope(engine):
    now = datetime.now(UTC)
    ids = {key: str(uuid4()) for key in ("user", "tenant", "site", "tenant_b", "site_b", "node")}
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (id,email,display_name,password_hash,is_active,failed_logins,created_at) "
            "VALUES (:id,'owner@example.test','Owner','x',true,0,:now)"
        ), {"id": ids["user"], "now": now})
        connection.execute(text(
            "INSERT INTO tenants (id,name,slug,created_at) VALUES (:id,'A','tenant-a',:now)"
        ), {"id": ids["tenant"], "now": now})
        connection.execute(text(
            "INSERT INTO sites (id,tenant_id,name,address,timezone,created_at) "
            "VALUES (:id,:tenant,'A-site','','UTC',:now)"
        ), {"id": ids["site"], "tenant": ids["tenant"], "now": now})
        connection.execute(text(
            "INSERT INTO tenant_memberships (tenant_id,user_id,role) VALUES (:tenant,:user,'owner')"
        ), {"tenant": ids["tenant"], "user": ids["user"]})
        connection.execute(text(
            "INSERT INTO tenants (id,name,slug,created_at) VALUES (:id,'B','tenant-b',:now)"
        ), {"id": ids["tenant_b"], "now": now})
        connection.execute(text(
            "INSERT INTO sites (id,tenant_id,name,address,timezone,created_at) "
            "VALUES (:id,:tenant,'B-site','','UTC',:now)"
        ), {"id": ids["site_b"], "tenant": ids["tenant_b"], "now": now})
        connection.execute(text(
            "INSERT INTO edge_nodes (id,tenant_id,site_id,name,status,config_revision,credential_generation,"
            "created_by_user_id,created_at,updated_at) "
            "VALUES (:id,:tenant,:site,'Node','pending',1,0,:user,:now,:now)"
        ), {"id": ids["node"], "tenant": ids["tenant"], "site": ids["site"], "user": ids["user"], "now": now})
    return ids


def test_head_has_original_six_tables_and_four_additive_tables(app):
    names = set(inspect(app.state.engine).get_table_names())
    assert names == TABLES | {"alembic_version"}


def test_camera_device_ids_are_independent_and_member_removal_keeps_history(app):
    ids = seed_scope(app.state.engine)
    now = datetime.now(UTC)
    with app.state.engine.begin() as connection:
        for _ in range(2):
            connection.execute(text(
                "INSERT INTO devices (id,tenant_id,site_id,edge_node_id,name,kind,status,hardware_serial,created_at,updated_at) "
                "VALUES (:id,:tenant,:site,:node,'Camera','camera','active','same-serial',:now,:now)"
            ), {"id": str(uuid4()), "tenant": ids["tenant"], "site": ids["site"], "node": ids["node"], "now": now})
        # Registry history references a User, never the revocable membership row.
        connection.execute(text(
            "DELETE FROM tenant_memberships WHERE tenant_id=:tenant AND user_id=:user"
        ), {"tenant": ids["tenant"], "user": ids["user"]})
        assert connection.execute(
            text("SELECT count(*) FROM devices WHERE edge_node_id=:node"), {"node": ids["node"]}
        ).scalar_one() == 2


def test_registry_checks_and_composite_scope_foreign_keys(app):
    ids = seed_scope(app.state.engine)
    now = datetime.now(UTC)
    invalid_rows = [
        ("edge_nodes", "id,tenant_id,site_id,name,status,config_revision,credential_generation,created_by_user_id,created_at,updated_at",
         ":id,:tenant,:site,'Bad status','online',1,0,:user,:now,:now"),
        ("devices", "id,tenant_id,site_id,edge_node_id,name,kind,status,created_at,updated_at",
         ":id,:tenant,:site,:node,'Cart','cart','active',:now,:now"),
    ]
    with app.state.engine.connect() as connection:
        for table, columns, values in invalid_rows:
            with pytest.raises(IntegrityError):
                connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), {
                    "id": str(uuid4()), "tenant": ids["tenant"], "site": ids["site"], "node": ids["node"],
                    "user": ids["user"], "now": now,
                })
            connection.rollback()
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO devices (id,tenant_id,site_id,edge_node_id,name,kind,status,created_at,updated_at) "
                "VALUES (:id,:tenant,:site,:node,'Cross','camera','active',:now,:now)"
            ), {"id": str(uuid4()), "tenant": ids["tenant_b"], "site": ids["site_b"],
                "node": ids["node"], "now": now})
        connection.rollback()


def test_restrict_preserves_site_node_and_credential_history(app):
    ids = seed_scope(app.state.engine)
    now = datetime.now(UTC)
    credential_id = str(uuid4())
    with app.state.engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO edge_credentials (id,tenant_id,site_id,edge_node_id,generation,token_hash,issued_at,expires_at,issued_by_user_id) "
            "VALUES (:id,:tenant,:site,:node,0,:hash,:now,:expires,:user)"
        ), {"id": credential_id, "tenant": ids["tenant"], "site": ids["site"], "node": ids["node"],
            "hash": "a" * 64, "now": now, "expires": now + timedelta(days=7), "user": ids["user"]})
    with app.state.engine.connect() as connection:
        for statement, params in [
            ("DELETE FROM sites WHERE id=:id", {"id": ids["site"]}),
            ("DELETE FROM edge_nodes WHERE id=:id", {"id": ids["node"]}),
            ("DELETE FROM users WHERE id=:id", {"id": ids["user"]}),
        ]:
            with pytest.raises(IntegrityError):
                connection.execute(text(statement), params)
            connection.rollback()
