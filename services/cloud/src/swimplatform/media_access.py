"""资源级读取授权的唯一定义处（S-read / S-manage / A-read）。

列表、详情、子列表与游标续页必须共用这里的谓词，避免各处手写条件漂移。
非 Owner/Admin 路径每次请求都要求**当前**角色为 coach：角色取自
`tenant_memberships`，不使用登录快照，也不因为授予过 grant 而永久放行。
"""
import base64
import binascii
import hashlib
import json
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .api import fail
from .models import AssetReadGrant, SessionReadGrant, TrainingSession, VideoAsset

MANAGER_ROLES = frozenset({"owner", "admin"})
COACH = "coach"

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
CURSOR_VERSION = 1


def is_manager(member) -> bool:
    return member.role in MANAGER_ROLES


def is_coach(member) -> bool:
    return member.role == COACH


def _active_grant_clause(model, now: datetime):
    return and_(
        model.revoked_at.is_(None),
        or_(model.expires_at.is_(None), model.expires_at > now),
    )


def session_read_predicate(user, member, now: datetime, model=TrainingSession):
    """给定用户与机构成员关系，构造该用户可见 Session 的 SQL 谓词。"""
    if is_manager(member):
        return model.tenant_id.isnot(None)
    if not is_coach(member):
        return model.id.is_(None)
    grant = (
        select(SessionReadGrant.id)
        .where(
            SessionReadGrant.tenant_id == model.tenant_id,
            SessionReadGrant.site_id == model.site_id,
            SessionReadGrant.session_id == model.id,
            SessionReadGrant.grantee_user_id == user.id,
            _active_grant_clause(SessionReadGrant, now),
        )
        .exists()
    )
    return or_(model.created_by_user_id == user.id, grant)


def asset_read_predicate(user, member, now: datetime):
    """A-read：创建者、显式 Asset grant，或对父 Session 有 S-read。"""
    if is_manager(member):
        return VideoAsset.tenant_id.isnot(None)
    if not is_coach(member):
        return VideoAsset.id.is_(None)
    asset_grant = (
        select(AssetReadGrant.id)
        .where(
            AssetReadGrant.tenant_id == VideoAsset.tenant_id,
            AssetReadGrant.site_id == VideoAsset.site_id,
            AssetReadGrant.asset_id == VideoAsset.id,
            AssetReadGrant.grantee_user_id == user.id,
            _active_grant_clause(AssetReadGrant, now),
        )
        .exists()
    )
    parent_read = (
        select(TrainingSession.id)
        .where(
            TrainingSession.id == VideoAsset.session_id,
            TrainingSession.tenant_id == VideoAsset.tenant_id,
            TrainingSession.site_id == VideoAsset.site_id,
            session_read_predicate(user, member, now),
        )
        .exists()
    )
    return or_(VideoAsset.created_by_user_id == user.id, asset_grant, parent_read)


def can_read_session(db: Session, session: TrainingSession, user, member, now: datetime) -> bool:
    if is_manager(member):
        return True
    if not is_coach(member):
        return False
    if session.created_by_user_id == user.id:
        return True
    return db.scalar(
        select(SessionReadGrant.id).where(
            SessionReadGrant.tenant_id == session.tenant_id,
            SessionReadGrant.site_id == session.site_id,
            SessionReadGrant.session_id == session.id,
            SessionReadGrant.grantee_user_id == user.id,
            _active_grant_clause(SessionReadGrant, now),
        ).limit(1)
    ) is not None


def can_manage_session(db: Session, session: TrainingSession, user, member) -> bool:
    if is_manager(member):
        return True
    return is_coach(member) and session.created_by_user_id == user.id


def can_read_asset(db: Session, asset: VideoAsset, session: TrainingSession, user, member, now: datetime) -> bool:
    if is_manager(member):
        return True
    if not is_coach(member):
        return False
    if asset.created_by_user_id == user.id:
        return True
    if db.scalar(
        select(AssetReadGrant.id).where(
            AssetReadGrant.tenant_id == asset.tenant_id,
            AssetReadGrant.site_id == asset.site_id,
            AssetReadGrant.asset_id == asset.id,
            AssetReadGrant.grantee_user_id == user.id,
            _active_grant_clause(AssetReadGrant, now),
        ).limit(1)
    ) is not None:
        return True
    return can_read_session(db, session, user, member, now)


def require_coach_or_manager(member):
    """创建 Session 的主体：Owner/Admin 或当前角色为 coach 的站点成员。"""
    if not (is_manager(member) or is_coach(member)):
        fail(403, "forbidden", "当前角色无训练会话创建权限")


def _encode(kind: str, tenant_id: str, site_id: str, filters: dict, created_at: datetime, row_id: str) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "k": kind,
        "t": tenant_id,
        "s": site_id,
        "f": _filter_digest(filters),
        "c": created_at.isoformat(),
        "i": row_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _filter_digest(filters: dict) -> str:
    normalized = json.dumps(filters, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(normalized).hexdigest()[:16]


def decode_cursor(cursor: str, *, kind: str, tenant_id: str, site_id: str, filters: dict) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            payload.get("v") != CURSOR_VERSION
            or payload.get("k") != kind
            or payload.get("t") != tenant_id
            or payload.get("s") != site_id
            or payload.get("f") != _filter_digest(filters)
        ):
            raise ValueError("cursor scope mismatch")
        return datetime.fromisoformat(payload["c"]), payload["i"]
    except (ValueError, KeyError, TypeError, binascii.Error):
        fail(422, "invalid_cursor", "游标无效或不属于当前查询范围")


def page_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1 or limit > MAX_PAGE_SIZE:
        fail(422, "validation_error", f"limit 须在 1 到 {MAX_PAGE_SIZE} 之间")
    return limit


def build_page(rows, limit: int, encode) -> dict:
    """rows 取 limit+1 条；多出的一条只用于判断是否还有下一页。"""
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode(items[-1]) if has_more and items else None
    return {"items": items, "next_cursor": next_cursor}
