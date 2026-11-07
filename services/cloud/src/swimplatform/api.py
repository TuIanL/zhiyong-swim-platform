from datetime import UTC, datetime, timedelta
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuthSession, Site, SiteMembership, Tenant, TenantMembership, User
from .schemas import Credentials, MemberCreate, MemberRead, MemberRole, Registration, SessionRead, SiteCreate, SiteGrant, SiteRead, TenantCreate, TenantRead, UserRead
from .security import DUMMY_PASSWORD, password_hash, token_hash, verify_password

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)


def fail(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


def as_utc(value: datetime | None) -> datetime | None:
    """把数据库读出的时间归一到 UTC 绝对瞬间。

    PostgreSQL 在带时区列上返回 aware datetime，偏移随该连接的会话时区变化；
    SQLite 则按既有约定返回朴素 UTC 值。前者必须 astimezone 保留瞬间，后者直接
    补 tzinfo；用 replace 重标 aware 值会把非 UTC 会话的截止时间整体平移。
    """
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def db_session(request: Request):
    with request.app.state.sessions() as db:
        yield db


DB = Annotated[Session, Depends(db_session)]


def identity(request: Request, db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials or credentials.scheme.lower() != "bearer" or len(credentials.credentials) > 256:
        fail(401, "unauthorized", "请登录")
    key = token_hash(credentials.credentials)
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == key, AuthSession.expires_at > datetime.now(UTC)))
    user = db.get(User, session.user_id) if session else None
    if not user or not user.is_active:
        fail(401, "unauthorized", "登录已失效")
    request.state.session_hash = key
    return user


Current = Annotated[User, Depends(identity)]


def membership(db, tenant_id, user_id):
    result = db.get(TenantMembership, (str(tenant_id), user_id))
    if not result:
        fail(404, "tenant_not_found", "机构不存在或无访问权限")
    return result


def manager(db, tenant_id, user_id, *, owner=False):
    member = membership(db, tenant_id, user_id)
    if member.role not in ({"owner"} if owner else {"owner", "admin"}):
        fail(403, "forbidden", "当前角色无管理权限")
    return member


def site_access(db, tenant_id, site_id, user, *, manage=False):
    member = membership(db, tenant_id, user.id)
    site = db.scalar(select(Site).where(Site.id == str(site_id), Site.tenant_id == str(tenant_id)))
    if not site:
        fail(404, "site_not_found", "场馆不存在或无访问权限")
    if manage:
        manager(db, tenant_id, user.id)
    elif member.role not in {"owner", "admin"} and not db.get(SiteMembership, (str(tenant_id), str(site_id), user.id)):
        fail(404, "site_not_found", "场馆不存在或无访问权限")
    return site


def commit(db, code="conflict", message="记录已存在"):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, code, message)


@router.post("/auth/register", response_model=UserRead, status_code=201)
def register(payload: Registration, db: DB):
    # 注册只创建账号，不接收 role、tenant_id 或管理员标志。
    user = User(email=payload.email, display_name=payload.display_name, password_hash=password_hash(payload.password))
    db.add(user)
    commit(db, "account_conflict", "该账号无法注册")
    return user


@router.post("/auth/login", response_model=SessionRead)
def login(payload: Credentials, request: Request, db: DB):
    user = db.scalar(select(User).where(User.email == payload.email).with_for_update())
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_PASSWORD)
    now = datetime.now(UTC)
    locked = bool(user and user.locked_until and as_utc(user.locked_until) > now)
    if not user or not valid or not user.is_active or locked:
        if user and not locked:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now + timedelta(minutes=15)
            db.commit()
        fail(401, "invalid_credentials", "账号或密码无效，或账号暂不可用")
    user.failed_logins = 0
    user.locked_until = None
    raw = secrets.token_urlsafe(32)
    expires = now + timedelta(seconds=request.app.state.settings.session_seconds)
    db.add(AuthSession(token_hash=token_hash(raw), user_id=user.id, expires_at=expires))
    db.commit()
    return SessionRead(access_token=raw, expires_at=expires, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
def me(user: Current):
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: Current, db: DB):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == request.state.session_hash, AuthSession.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@router.post("/tenants", response_model=TenantRead, status_code=201)
def create_tenant(payload: TenantCreate, user: Current, db: DB):
    tenant = Tenant(name=payload.name, slug=payload.slug)
    db.add(tenant)
    try:
        db.flush()
        db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "tenant_conflict", "机构标识已存在")
    return TenantRead(id=tenant.id, name=tenant.name, slug=tenant.slug, role="owner")


@router.get("/tenants", response_model=list[TenantRead])
def list_tenants(user: Current, db: DB):
    rows = db.execute(select(Tenant, TenantMembership.role).join(TenantMembership).where(TenantMembership.user_id == user.id).order_by(Tenant.created_at)).all()
    return [TenantRead(id=t.id, name=t.name, slug=t.slug, role=role) for t, role in rows]


@router.get("/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: UUID, user: Current, db: DB):
    member = membership(db, tenant_id, user.id)
    tenant = db.get(Tenant, str(tenant_id))
    return TenantRead(id=tenant.id, name=tenant.name, slug=tenant.slug, role=member.role)


@router.get("/tenants/{tenant_id}/members", response_model=list[MemberRead])
def list_members(tenant_id: UUID, user: Current, db: DB):
    manager(db, tenant_id, user.id)
    rows = db.execute(select(User, TenantMembership.role).join(TenantMembership).where(TenantMembership.tenant_id == str(tenant_id)).order_by(User.display_name)).all()
    return [MemberRead(user_id=u.id, display_name=u.display_name, role=role) for u, role in rows]


@router.post("/tenants/{tenant_id}/members", response_model=MemberRead, status_code=201)
def add_member(tenant_id: UUID, payload: MemberCreate, user: Current, db: DB):
    manager(db, tenant_id, user.id, owner=True)
    target = db.get(User, str(payload.user_id))
    if not target or not target.is_active:
        fail(404, "user_not_found", "账号不存在")
    db.add(TenantMembership(tenant_id=str(tenant_id), user_id=target.id, role=payload.role))
    commit(db, "member_conflict", "成员已存在")
    return MemberRead(user_id=target.id, display_name=target.display_name, role=payload.role)


@router.patch("/tenants/{tenant_id}/members/{user_id}", response_model=MemberRead)
def change_member(tenant_id: UUID, user_id: UUID, payload: MemberRole, user: Current, db: DB):
    manager(db, tenant_id, user.id, owner=True)
    target = membership(db, tenant_id, str(user_id))
    if target.role == "owner":
        fail(409, "owner_transfer_required", "首版不支持修改机构所有者")
    target.role = payload.role
    db.commit()
    account = db.get(User, str(user_id))
    return MemberRead(user_id=account.id, display_name=account.display_name, role=target.role)


@router.delete("/tenants/{tenant_id}/members/{user_id}", status_code=204)
def remove_member(tenant_id: UUID, user_id: UUID, user: Current, db: DB):
    manager(db, tenant_id, user.id, owner=True)
    target = membership(db, tenant_id, str(user_id))
    if target.role == "owner":
        fail(409, "owner_transfer_required", "不能移除机构所有者")
    db.delete(target)
    db.commit()
    return Response(status_code=204)


@router.post("/tenants/{tenant_id}/sites", response_model=SiteRead, status_code=201)
def create_site(tenant_id: UUID, payload: SiteCreate, user: Current, db: DB):
    manager(db, tenant_id, user.id)
    site = Site(tenant_id=str(tenant_id), **payload.model_dump())
    db.add(site)
    commit(db, "site_conflict", "本机构场馆名称已存在")
    return site


@router.get("/tenants/{tenant_id}/sites", response_model=list[SiteRead])
def list_sites(tenant_id: UUID, user: Current, db: DB):
    member = membership(db, tenant_id, user.id)
    query = select(Site).where(Site.tenant_id == str(tenant_id))
    if member.role not in {"owner", "admin"}:
        query = query.join(SiteMembership, (SiteMembership.site_id == Site.id) & (SiteMembership.tenant_id == Site.tenant_id)).where(SiteMembership.user_id == user.id)
    return db.scalars(query.order_by(Site.created_at)).all()


@router.get("/tenants/{tenant_id}/sites/{site_id}", response_model=SiteRead)
def get_site(tenant_id: UUID, site_id: UUID, user: Current, db: DB):
    return site_access(db, tenant_id, site_id, user)


@router.patch("/tenants/{tenant_id}/sites/{site_id}", response_model=SiteRead)
def update_site(tenant_id: UUID, site_id: UUID, payload: SiteCreate, user: Current, db: DB):
    site = site_access(db, tenant_id, site_id, user, manage=True)
    for key, value in payload.model_dump().items():
        setattr(site, key, value)
    commit(db, "site_conflict", "本机构场馆名称已存在")
    return site


@router.post("/tenants/{tenant_id}/sites/{site_id}/members", status_code=201)
def grant_site(tenant_id: UUID, site_id: UUID, payload: SiteGrant, user: Current, db: DB):
    site_access(db, tenant_id, site_id, user, manage=True)
    membership(db, tenant_id, str(payload.user_id))
    db.add(SiteMembership(tenant_id=str(tenant_id), site_id=str(site_id), user_id=str(payload.user_id)))
    commit(db, "grant_conflict", "成员已有场馆授权")
    return {"user_id": str(payload.user_id), "site_id": str(site_id)}


@router.delete("/tenants/{tenant_id}/sites/{site_id}/members/{user_id}", status_code=204)
def revoke_site(tenant_id: UUID, site_id: UUID, user_id: UUID, user: Current, db: DB):
    site_access(db, tenant_id, site_id, user, manage=True)
    db.execute(delete(SiteMembership).where(SiteMembership.tenant_id == str(tenant_id), SiteMembership.site_id == str(site_id), SiteMembership.user_id == str(user_id)))
    db.commit()
    return Response(status_code=204)
