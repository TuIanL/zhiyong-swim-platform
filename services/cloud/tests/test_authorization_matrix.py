"""角色与 operation 矩阵（design D4）。

本文件无 `postgresql` 标记：同一套断言在 SQLite 与 PostgreSQL 两个后端都运行，
是“共享 API 用例”的主体。17 个业务 operation 逐项覆盖；health/ready 单列。
"""
from types import SimpleNamespace

import pytest

from conftest import PASSWORD


@pytest.fixture
def world(client, seeded_account):
    accounts = {}
    for name in ("owner", "admin", "coach", "athlete", "outsider"):
        accounts[name] = seeded_account(name)
    tenant = client.post(
        "/api/v1/tenants", headers=accounts["owner"][1], json={"name": "team-a", "slug": "team-a"}
    ).json()
    for name, role in (("admin", "admin"), ("coach", "coach"), ("athlete", "athlete")):
        created = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            headers=accounts["owner"][1],
            json={"user_id": accounts[name][0]["id"], "role": role},
        )
        assert created.status_code == 201, created.text
    site = client.post(
        f"/api/v1/tenants/{tenant['id']}/sites", headers=accounts["owner"][1], json={"name": "第一训练馆"}
    ).json()
    return SimpleNamespace(
        tenant=tenant,
        site=site,
        owner=accounts["owner"],
        admin=accounts["admin"],
        coach=accounts["coach"],
        athlete=accounts["athlete"],
        outsider=accounts["outsider"],
        seed=seeded_account,
    )


def tenant_path(world, suffix=""):
    return f"/api/v1/tenants/{world.tenant['id']}{suffix}"


def test_health_readiness_and_public_auth_operations(world, client):
    # 两项健康操作不属于 17 个业务 operation，单独列明。
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200

    body = {"email": "fresh@example.test", "password": PASSWORD, "display_name": "Fresh"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert client.post("/api/v1/auth/register", json=body).status_code == 409
    # 公开注册不接受特权字段。
    for extra in ({"role": "admin"}, {"tenant_id": world.tenant["id"]}, {"is_active": True}):
        assert client.post(
            "/api/v1/auth/register",
            json={"email": f"x-{len(extra)}@example.test", "password": PASSWORD, "display_name": "X", **extra},
        ).status_code == 422
    assert client.post(
        "/api/v1/auth/login", json={"email": body["email"], "password": "Wrong-Password-2026"}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"email": body["email"], "password": PASSWORD}
    ).status_code == 200


def test_current_account_and_logout_follow_identity(world, client, seeded_account):
    for name in ("owner", "admin", "coach", "athlete", "outsider"):
        user, headers = world.__dict__[name]
        assert client.get("/api/v1/me", headers=headers).json() == user
    assert client.get("/api/v1/me").status_code == 401

    _, disposable = seeded_account("logout-target")
    assert client.post("/api/v1/auth/logout").status_code == 401
    assert client.post("/api/v1/auth/logout", headers=disposable).status_code == 204
    assert client.get("/api/v1/me", headers=disposable).status_code == 401


def test_tenant_creation_needs_no_membership_and_grants_owner(world, client, seeded_account):
    _, newcomer = seeded_account("newcomer")
    assert client.get("/api/v1/tenants", headers=newcomer).json() == []
    created = client.post(
        "/api/v1/tenants", headers=newcomer, json={"name": "own-team", "slug": "own-team"}
    )
    assert created.status_code == 201
    assert created.json()["role"] == "owner"
    assert [t["slug"] for t in client.get("/api/v1/tenants", headers=newcomer).json()] == ["own-team"]
    assert client.post(
        "/api/v1/tenants", headers=newcomer, json={"name": "dup", "slug": "own-team"}
    ).status_code == 409
    assert client.post("/api/v1/tenants", json={"name": "anon", "slug": "anon-team"}).status_code == 401


def test_tenant_scoped_reads_matrix(world, client):
    cases = [
        ("", {"anon": 401, "outsider": 404, "athlete": 200, "coach": 200, "admin": 200, "owner": 200}),
        ("/members", {"anon": 401, "outsider": 404, "athlete": 403, "coach": 403, "admin": 200, "owner": 200}),
        ("/sites", {"anon": 401, "outsider": 404, "athlete": 200, "coach": 200, "admin": 200, "owner": 200}),
    ]
    for suffix, expected in cases:
        for name, status in expected.items():
            headers = None if name == "anon" else world.__dict__[name][1]
            response = client.get(tenant_path(world, suffix), headers=headers)
            assert response.status_code == status, (suffix, name, response.text)

    # 普通角色无显式授权时列表为空、详情 404；管理角色可见机构级场馆。
    assert client.get(tenant_path(world, "/sites"), headers=world.coach[1]).json() == []
    assert client.get(tenant_path(world, "/sites"), headers=world.athlete[1]).json() == []
    assert [s["id"] for s in client.get(tenant_path(world, "/sites"), headers=world.admin[1]).json()] == [world.site["id"]]

    site_path = tenant_path(world, f"/sites/{world.site['id']}")
    expected = {"anon": 401, "outsider": 404, "athlete": 404, "coach": 404, "admin": 200, "owner": 200}
    for name, status in expected.items():
        headers = None if name == "anon" else world.__dict__[name][1]
        assert client.get(site_path, headers=headers).status_code == status, name


def test_member_management_matrix(world, client, seeded_account):
    path = tenant_path(world, "/members")

    # 列表：owner/admin 可读，普通角色 403。
    for name, expected in (("admin", 200), ("coach", 403), ("athlete", 403), ("outsider", 404)):
        assert client.get(path, headers=world.__dict__[name][1]).status_code == expected, name

    # 新增：只有 owner 可写。
    target_ok, _ = seeded_account("target-ok")
    assert client.post(path, headers=world.admin[1], json={"user_id": target_ok["id"], "role": "coach"}).status_code == 403
    for name in ("coach", "athlete"):
        target, _ = seeded_account(f"target-{name}")
        assert client.post(path, headers=world.__dict__[name][1], json={"user_id": target["id"], "role": "coach"}).status_code == 403
    target_out, _ = seeded_account("target-out")
    assert client.post(path, headers=world.outsider[1], json={"user_id": target_out["id"], "role": "coach"}).status_code == 404
    assert client.post(path, json={"user_id": target_ok["id"], "role": "coach"}).status_code == 401

    added = client.post(path, headers=world.owner[1], json={"user_id": target_ok["id"], "role": "coach"})
    assert added.status_code == 201
    assert client.post(path, headers=world.owner[1], json={"user_id": target_ok["id"], "role": "coach"}).status_code == 409
    assert client.post(
        path, headers=world.owner[1], json={"user_id": f"{target_ok['id']}", "role": "owner"}
    ).status_code == 422

    # 改角色：owner 可改非 owner，admin 403，owner 自身 409。
    member_path = f"{path}/{target_ok['id']}"
    assert client.patch(member_path, headers=world.admin[1], json={"role": "athlete"}).status_code == 403
    assert client.patch(member_path, headers=world.owner[1], json={"role": "athlete"}).status_code == 200
    owner_self = f"{path}/{world.owner[0]['id']}"
    assert client.patch(owner_self, headers=world.owner[1], json={"role": "coach"}).status_code == 409

    # 移除：owner 可移除非 owner，admin 403，owner 自身 409。
    assert client.delete(member_path, headers=world.admin[1]).status_code == 403
    assert client.delete(member_path, headers=world.owner[1]).status_code == 204
    assert client.delete(owner_self, headers=world.owner[1]).status_code == 409


def test_site_write_matrix(world, client, seeded_account):
    create_path = tenant_path(world, "/sites")
    expected = {"anon": 401, "outsider": 404, "athlete": 403, "coach": 403}
    for name, status in expected.items():
        headers = None if name == "anon" else world.__dict__[name][1]
        assert client.post(create_path, headers=headers, json={"name": f"馆-{name}"}).status_code == status, name

    for name in ("admin", "owner"):
        created = client.post(create_path, headers=world.__dict__[name][1], json={"name": f"馆-{name}"})
        assert created.status_code == 201, name
    assert client.post(create_path, headers=world.owner[1], json={"name": "馆-owner"}).status_code == 409

    site_path = tenant_path(world, f"/sites/{world.site['id']}")
    for name, status in (("outsider", 404), ("athlete", 403), ("coach", 403), ("admin", 200), ("owner", 200)):
        response = client.patch(
            site_path, headers=world.__dict__[name][1], json={"name": f"改名-{name}"}
        )
        assert response.status_code == status, name
    assert client.patch(site_path, json={"name": "匿名"}).status_code == 401


def test_site_grant_and_revoke_matrix(world, client, seeded_account):
    grant_path = tenant_path(world, f"/sites/{world.site['id']}/members")

    outsider_target, _ = seeded_account("grant-outsider")
    assert client.post(grant_path, headers=world.owner[1], json={"user_id": outsider_target["id"]}).status_code == 404
    for name in ("coach", "athlete"):
        assert client.post(
            grant_path, headers=world.__dict__[name][1], json={"user_id": outsider_target["id"]}
        ).status_code == 403
    assert client.post(grant_path, json={"user_id": outsider_target["id"]}).status_code == 401

    for name in ("owner", "admin"):
        user, headers = world.__dict__[name]
        assert client.post(grant_path, headers=headers, json={"user_id": world.athlete[0]["id"]}).status_code == 201
        assert client.post(grant_path, headers=headers, json={"user_id": world.athlete[0]["id"]}).status_code == 409
        assert client.delete(f"{grant_path}/{world.athlete[0]['id']}", headers=headers).status_code == 204
    assert client.post(grant_path, headers=world.owner[1], json={"user_id": world.athlete[0]["id"]}).status_code == 201
    # 重复授权 409；授权后普通角色立即可以读取该场馆。
    assert client.post(grant_path, headers=world.owner[1], json={"user_id": world.athlete[0]["id"]}).status_code == 409
    assert client.get(tenant_path(world, f"/sites/{world.site['id']}"), headers=world.athlete[1]).status_code == 200
    assert [s["id"] for s in client.get(tenant_path(world, "/sites"), headers=world.athlete[1]).json()] == [world.site["id"]]

    revoke_path = f"{grant_path}/{world.athlete[0]['id']}"
    assert client.delete(revoke_path, headers=world.coach[1]).status_code == 403
    assert client.delete(revoke_path, headers=world.admin[1]).status_code == 204
    assert client.get(tenant_path(world, f"/sites/{world.site['id']}"), headers=world.athlete[1]).status_code == 404
    # 撤销不存在的授权仍返回 204，保持幂等语义。
    assert client.delete(revoke_path, headers=world.admin[1]).status_code == 204


def test_permission_changes_apply_to_existing_sessions(world, client):
    site_path = tenant_path(world, f"/sites/{world.site['id']}")
    grant_path = tenant_path(world, f"/sites/{world.site['id']}/members")

    assert client.post(grant_path, headers=world.owner[1], json={"user_id": world.coach[0]["id"]}).status_code == 201
    assert client.get(site_path, headers=world.coach[1]).status_code == 200
    assert client.delete(f"{grant_path}/{world.coach[0]['id']}", headers=world.owner[1]).status_code == 204
    # 同一个 token、无需重新登录，撤销立即生效。
    assert client.get(site_path, headers=world.coach[1]).status_code == 404

    assert client.get(tenant_path(world), headers=world.admin[1]).status_code == 200
    assert client.delete(
        tenant_path(world, f"/members/{world.admin[0]['id']}"), headers=world.owner[1]
    ).status_code == 204
    assert client.get(tenant_path(world), headers=world.admin[1]).status_code == 404


def test_admin_downgrade_and_management_exception(world, client):
    site_path = tenant_path(world, f"/sites/{world.site['id']}")
    grant_path = tenant_path(world, f"/sites/{world.site['id']}/members")

    # 管理角色不依赖显式授权；撤销其显式授权也不影响机构级权限。
    assert client.post(grant_path, headers=world.owner[1], json={"user_id": world.admin[0]["id"]}).status_code == 201
    assert client.delete(f"{grant_path}/{world.admin[0]['id']}", headers=world.owner[1]).status_code == 204
    assert client.get(site_path, headers=world.admin[1]).status_code == 200
    assert client.get(site_path, headers=world.owner[1]).status_code == 200

    # admin 降为 athlete 且没有场馆授权后，只能看到空列表。
    assert client.patch(
        tenant_path(world, f"/members/{world.admin[0]['id']}"), headers=world.owner[1], json={"role": "athlete"}
    ).status_code == 200
    assert client.get(tenant_path(world, "/sites"), headers=world.admin[1]).json() == []
    assert client.get(site_path, headers=world.admin[1]).status_code == 404


def test_cross_tenant_site_id_is_rejected(world, client, seeded_account):
    _, other = seeded_account("other-owner")
    other_tenant = client.post(
        "/api/v1/tenants", headers=other, json={"name": "team-b", "slug": "team-b"}
    ).json()
    other_site = client.post(
        f"/api/v1/tenants/{other_tenant['id']}/sites", headers=other, json={"name": "B馆"}
    ).json()

    # 让 owner 同时属于两个机构：即便如此也不能用 A 的 tenant_id 访问 B 的场馆。
    assert client.post(
        f"/api/v1/tenants/{other_tenant['id']}/members",
        headers=other,
        json={"user_id": world.owner[0]["id"], "role": "coach"},
    ).status_code == 201
    assert [t["id"] for t in client.get("/api/v1/tenants", headers=world.owner[1]).json()] == [
        world.tenant["id"],
        other_tenant["id"],
    ]
    assert client.get(tenant_path(world, f"/sites/{other_site['id']}"), headers=world.owner[1]).status_code == 404
    assert client.get(f"/api/v1/tenants/{other_tenant['id']}/sites", headers=world.owner[1]).json() == []
    assert client.get(tenant_path(world), headers=world.owner[1]).status_code == 200


def database_snapshot(app):
    """拒绝请求前后比较持久化状态，不能只看HTTP错误码。"""
    from sqlalchemy import select
    from swimplatform.models import Base
    with app.state.engine.connect() as connection:
        return {
            table.name: [tuple(row) for row in connection.execute(select(table).order_by(*table.primary_key.columns))]
            for table in Base.metadata.sorted_tables
        }


DENIED_WRITES = [
    (operation, role, 401 if role == 'anon' else 404 if role == 'outsider' else 403)
    for operation in ('change_member', 'remove_member', 'grant_site', 'revoke_site')
    for role in ('anon', 'outsider', 'coach', 'athlete', 'admin')
    if not (role == 'admin' and operation in ('grant_site', 'revoke_site'))
]


@pytest.mark.parametrize('operation,role,status', DENIED_WRITES)
def test_denied_member_and_site_writes_have_no_persistent_effect(world, client, app, operation, role, status):
    target = world.coach[0]['id']
    member = tenant_path(world, f'/members/{target}')
    grants = tenant_path(world, f"/sites/{world.site['id']}/members")
    # 所有失败条件只来自操作者权限；目标成员、机构和场馆均真实存在且归属有效。
    assert client.post(grants, headers=world.owner[1], json={'user_id': target}).status_code == 201
    requests = {
        'change_member': ('PATCH', member, {'role': 'athlete'}),
        'remove_member': ('DELETE', member, None),
        'grant_site': ('POST', grants, {'user_id': world.athlete[0]['id']}),
        'revoke_site': ('DELETE', f'{grants}/{target}', None),
    }
    method, path, body = requests[operation]
    before = database_snapshot(app)
    headers = None if role == 'anon' else world.__dict__[role][1]
    response = client.request(method, path, headers=headers, **({'json': body} if body else {}))
    assert response.status_code == status, response.text
    assert database_snapshot(app) == before


@pytest.mark.parametrize('role', ['owner', 'admin'])
def test_revoking_manager_own_explicit_grant_preserves_tenant_scope(world, client, role):
    user, headers = world.__dict__[role]
    site = tenant_path(world, f"/sites/{world.site['id']}")
    grants = site + '/members'
    assert client.post(grants, headers=world.owner[1], json={'user_id': user['id']}).status_code == 201
    assert client.delete(f"{grants}/{user['id']}", headers=world.owner[1]).status_code == 204
    assert client.get(site, headers=headers).status_code == 200
    assert [s['id'] for s in client.get(tenant_path(world, '/sites'), headers=headers).json()] == [world.site['id']]
    assert client.post(tenant_path(world, '/sites'), headers=headers, json={'name': f'{role}-new'}).status_code == 201
