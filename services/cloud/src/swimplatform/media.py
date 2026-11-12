"""M2 云端训练会话、逻辑视频资产与资源级读取授权。

本模块只交付元数据与意图：没有分片、整对象校验、播放或 ready 转换。
上传意图在**单一事务**内写 Asset + UploadSession + 幂等记录，一次提交。
"""
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import Current, DB, as_utc, fail, membership, site_access
from .edge_registry import get_edge_identity, idempotency_key_digest, request_digest, server_now
from .media_access import (
    asset_read_predicate,
    build_page,
    can_manage_session,
    can_read_asset,
    can_read_session,
    decode_cursor,
    is_manager,
    page_limit,
    require_coach_or_manager,
    session_read_predicate,
    _encode,
)
from .models import (
    AssetReadGrant,
    Device,
    IdempotencyRecord,
    SessionReadGrant,
    SiteMembership,
    TenantMembership,
    TrainingSession,
    UploadSession,
    User,
    VideoAsset,
)
from .schemas import (
    AssetRead,
    EdgeUploadIntentCreate,
    GrantPut,
    Page,
    SessionCreate,
    SessionPatch,
    TrainingSessionRead,
    UploadIntentCreate,
    UploadIntentRead,
    UploadSessionRead,
)

router = APIRouter(prefix="/api/v1")
P = "/tenants/{tenant_id}/sites/{site_id}"

UPLOAD_TTL_HOURS = 24
UPLOAD_TTL_MAX_DAYS = 7

STATUS_ENTRY = {
    "planned": {"recording", "cancelled"},
    "recording": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


# ---- 作用域与读取模型 ----------------------------------------------------


def _scope(db: Session, tenant_id: UUID, site_id: UUID, user):
    site = site_access(db, tenant_id, site_id, user)
    return site, membership(db, tenant_id, user.id)


def session_read(row: TrainingSession) -> TrainingSessionRead:
    return TrainingSessionRead(
        id=row.id, tenant_id=row.tenant_id, site_id=row.site_id,
        created_by_user_id=row.created_by_user_id, title=row.title, status=row.status,
        started_at=as_utc(row.started_at), completed_at=as_utc(row.completed_at),
        cancelled_at=as_utc(row.cancelled_at), created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def asset_read(row: VideoAsset) -> AssetRead:
    return AssetRead(
        id=row.id, tenant_id=row.tenant_id, site_id=row.site_id, session_id=row.session_id,
        origin=row.origin, created_by_user_id=row.created_by_user_id,
        source_edge_node_id=row.source_edge_node_id, source_device_id=row.source_device_id,
        derived_from_asset_id=row.derived_from_asset_id, status=row.status,
        failure_reason=row.failure_reason,
        capture_started_at_utc=as_utc(row.capture_started_at_utc),
        capture_ended_at_utc=as_utc(row.capture_ended_at_utc),
        device_capture_started_at_raw=row.device_capture_started_at_raw,
        device_capture_ended_at_raw=row.device_capture_ended_at_raw,
        device_time_basis=row.device_time_basis, device_timezone=row.device_timezone,
        device_utc_offset_minutes=row.device_utc_offset_minutes,
        video_timebase_kind=row.video_timebase_kind,
        video_timebase_metadata=row.video_timebase_metadata,
        device_clock_source=row.device_clock_source,
        device_clock_offset_ms=float(row.device_clock_offset_ms) if row.device_clock_offset_ms is not None else None,
        device_clock_accuracy_ms=(
            float(row.device_clock_accuracy_ms) if row.device_clock_accuracy_ms is not None else None
        ),
        received_at=as_utc(row.received_at), media_type=row.media_type, size_bytes=row.size_bytes,
        checksum_sha256=row.checksum_sha256, created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def upload_read(row: UploadSession) -> UploadSessionRead:
    return UploadSessionRead(
        id=row.id, asset_id=row.asset_id, status=row.status,
        initiator_user_id=row.initiator_user_id, initiator_edge_node_id=row.initiator_edge_node_id,
        expected_size_bytes=row.expected_size_bytes, expected_sha256=row.expected_sha256,
        media_type=row.media_type, expires_at=as_utc(row.expires_at), confirmed_parts=[],
        completed_at=as_utc(row.completed_at), failure_reason=row.failure_reason,
        created_at=as_utc(row.created_at), updated_at=as_utc(row.updated_at),
    )


def get_session(db: Session, tenant_id, site_id, session_id: UUID) -> TrainingSession:
    row = db.scalar(select(TrainingSession).where(
        TrainingSession.id == str(session_id),
        TrainingSession.tenant_id == str(tenant_id),
        TrainingSession.site_id == str(site_id),
    ))
    if not row:
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    return row


def get_asset(db: Session, tenant_id, site_id, asset_id: UUID) -> VideoAsset:
    row = db.scalar(select(VideoAsset).where(
        VideoAsset.id == str(asset_id),
        VideoAsset.tenant_id == str(tenant_id),
        VideoAsset.site_id == str(site_id),
    ))
    if not row:
        fail(404, "video_asset_not_found", "视频资产不存在或无访问权限")
    return row


def get_upload(db: Session, tenant_id, site_id, upload_id: UUID) -> UploadSession:
    row = db.scalar(select(UploadSession).where(
        UploadSession.id == str(upload_id),
        UploadSession.tenant_id == str(tenant_id),
        UploadSession.site_id == str(site_id),
    ))
    if not row:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    return row


def lock_session(db: Session, tenant_id, site_id, session_id) -> TrainingSession | None:
    scope = (
        TrainingSession.id == str(session_id),
        TrainingSession.tenant_id == str(tenant_id),
        TrainingSession.site_id == str(site_id),
    )
    query = select(TrainingSession).where(*scope).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        result = db.execute(update(TrainingSession).where(*scope).values(updated_at=TrainingSession.updated_at))
        if result.rowcount != 1:
            return None
    return db.scalar(query)


def lock_upload(db: Session, tenant_id, site_id, upload_id: str) -> UploadSession | None:
    """只在调用者已授权的 tenant/site 范围内加锁，避免跨机构探测触发行锁。"""
    scope = (
        UploadSession.id == upload_id,
        UploadSession.tenant_id == str(tenant_id),
        UploadSession.site_id == str(site_id),
    )
    query = select(UploadSession).where(*scope).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        result = db.execute(update(UploadSession).where(*scope).values(updated_at=UploadSession.updated_at))
        if result.rowcount != 1:
            return None
    return db.scalar(query)


# ---- 会话 ----------------------------------------------------------------


def _cursor_filters(status: str | None) -> dict:
    return {"status": status}


@router.get(P + "/training-sessions", response_model=Page)
def list_sessions(
    tenant_id: UUID, site_id: UUID, request: Request, user: Current, db: DB,
    status: Annotated[str | None, Query(pattern="^(planned|recording|completed|cancelled)$")] = None,
    limit: int | None = None, cursor: str | None = None,
):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    size = page_limit(limit)
    filters = _cursor_filters(status)
    query = select(TrainingSession).where(
        TrainingSession.tenant_id == str(tenant_id),
        TrainingSession.site_id == str(site_id),
        session_read_predicate(user, member, now),
    )
    if status:
        query = query.where(TrainingSession.status == status)
    if cursor:
        after, row_id = decode_cursor(
            cursor, kind="session", tenant_id=str(tenant_id), site_id=str(site_id), filters=filters
        )
        query = query.where(
            (TrainingSession.created_at < after)
            | ((TrainingSession.created_at == after) & (TrainingSession.id < row_id))
        )
    rows = db.scalars(
        query.order_by(TrainingSession.created_at.desc(), TrainingSession.id.desc()).limit(size + 1)
    ).all()
    page = build_page(
        rows, size,
        lambda row: _encode("session", str(tenant_id), str(site_id), filters, as_utc(row.created_at), row.id),
    )
    return Page(items=[session_read(row) for row in page["items"]], next_cursor=page["next_cursor"])


@router.post(P + "/training-sessions", response_model=TrainingSessionRead, status_code=201)
def create_session(
    tenant_id: UUID, site_id: UUID, payload: SessionCreate, request: Request,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")], user: Current, db: DB,
):
    _, member = _scope(db, tenant_id, site_id, user)
    require_coach_or_manager(member)
    key_digest = idempotency_key_digest(idempotency_header)
    digest = request_digest(payload)
    now = server_now(request)
    existing = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == str(tenant_id),
        IdempotencyRecord.site_id == str(site_id),
        IdempotencyRecord.user_id == user.id,
        IdempotencyRecord.operation == "training_session.create",
        IdempotencyRecord.target_id == str(site_id),
        IdempotencyRecord.key_hash == key_digest,
    ))
    if existing:
        if existing.request_hash != digest:
            fail(409, "idempotency_conflict", "同一幂等键已用于不同请求参数")
        row = db.get(TrainingSession, existing.resource_id)
        if not row:
            fail(409, "state_conflict", "幂等记录指向的会话不存在")
        return session_read(row)

    row = TrainingSession(
        tenant_id=str(tenant_id), site_id=str(site_id), created_by_user_id=user.id,
        title=payload.title, status="planned", created_at=now, updated_at=now,
    )
    db.add(row)
    db.flush()
    db.add(IdempotencyRecord(
        tenant_id=str(tenant_id), site_id=str(site_id), actor_kind="user", user_id=user.id,
        operation="training_session.create", target_id=str(site_id), key_hash=key_digest,
        request_hash=digest, resource_kind="training_session", resource_id=row.id,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == str(tenant_id),
            IdempotencyRecord.site_id == str(site_id),
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.operation == "training_session.create",
            IdempotencyRecord.target_id == str(site_id),
            IdempotencyRecord.key_hash == key_digest,
        ))
        if not replay:
            fail(409, "state_conflict", "会话写入冲突")
        if replay.request_hash != digest:
            fail(409, "idempotency_conflict", "同一幂等键已用于不同请求参数")
        return session_read(db.get(TrainingSession, replay.resource_id))
    return session_read(row)


@router.get(P + "/training-sessions/{session_id}", response_model=TrainingSessionRead)
def read_session(tenant_id: UUID, site_id: UUID, session_id: UUID, request: Request, user: Current, db: DB):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    row = get_session(db, tenant_id, site_id, session_id)
    if not can_read_session(db, row, user, member, now):
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    return session_read(row)


@router.patch(P + "/training-sessions/{session_id}", response_model=TrainingSessionRead)
def patch_session(
    tenant_id: UUID, site_id: UUID, session_id: UUID, payload: SessionPatch,
    request: Request, user: Current, db: DB,
):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    row = lock_session(db, tenant_id, site_id, session_id)
    if not row:
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    if not can_read_session(db, row, user, member, now):
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    if not can_manage_session(db, row, user, member):
        fail(403, "forbidden", "当前角色无该会话的管理权限")

    changes = payload.model_dump(exclude_unset=True)
    changed = False
    if "title" in changes and row.title != changes["title"]:
        row.title = changes["title"]
        changed = True
    target = changes.get("status")
    if target is not None and target != row.status:
        if target not in STATUS_ENTRY[row.status]:
            fail(409, "state_conflict", "会话状态迁移不允许")
        if target == "recording":
            row.status = "recording"
            row.started_at = now
        elif target == "completed":
            row.status = "completed"
            row.completed_at = now
        else:  # cancelled：同一事务内收口未完成上传与其 pending 资产
            db.execute(update(UploadSession).where(
                UploadSession.tenant_id == row.tenant_id,
                UploadSession.site_id == row.site_id,
                UploadSession.session_id == row.id,
                UploadSession.status.in_(("uploading", "completing")),
            ).values(status="failed", failure_reason="session_cancelled", updated_at=now))
            db.execute(update(VideoAsset).where(
                VideoAsset.tenant_id == row.tenant_id,
                VideoAsset.site_id == row.site_id,
                VideoAsset.session_id == row.id,
                VideoAsset.status == "pending_upload",
            ).values(status="failed", failure_reason="session_cancelled", updated_at=now))
            row.status = "cancelled"
            row.cancelled_at = now
        changed = True
    if not changed:
        db.rollback()
        return session_read(row)
    row.updated_at = now
    db.commit()
    return session_read(row)


# ---- 资产 ----------------------------------------------------------------


@router.get(P + "/training-sessions/{session_id}/video-assets", response_model=Page)
def list_session_assets(
    tenant_id: UUID, site_id: UUID, session_id: UUID, request: Request, user: Current, db: DB,
    status: Annotated[str | None, Query(pattern="^(pending_upload|ready|failed)$")] = None,
    limit: int | None = None, cursor: str | None = None,
):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    session = get_session(db, tenant_id, site_id, session_id)
    if not can_read_session(db, session, user, member, now):
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    size = page_limit(limit)
    filters = {"status": status, "session": session.id}
    query = select(VideoAsset).where(
        VideoAsset.tenant_id == str(tenant_id),
        VideoAsset.site_id == str(site_id),
        VideoAsset.session_id == session.id,
        asset_read_predicate(user, member, now),
    )
    if status:
        query = query.where(VideoAsset.status == status)
    if cursor:
        after, row_id = decode_cursor(
            cursor, kind="asset", tenant_id=str(tenant_id), site_id=str(site_id), filters=filters
        )
        query = query.where(
            (VideoAsset.created_at < after)
            | ((VideoAsset.created_at == after) & (VideoAsset.id < row_id))
        )
    rows = db.scalars(
        query.order_by(VideoAsset.created_at.desc(), VideoAsset.id.desc()).limit(size + 1)
    ).all()
    page = build_page(
        rows, size,
        lambda row: _encode("asset", str(tenant_id), str(site_id), filters, as_utc(row.created_at), row.id),
    )
    return Page(items=[asset_read(row) for row in page["items"]], next_cursor=page["next_cursor"])


@router.get(P + "/video-assets/{asset_id}", response_model=AssetRead)
def read_asset(tenant_id: UUID, site_id: UUID, asset_id: UUID, request: Request, user: Current, db: DB):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    row = get_asset(db, tenant_id, site_id, asset_id)
    session = get_session(db, tenant_id, site_id, UUID(row.session_id))
    if not can_read_asset(db, row, session, user, member, now):
        fail(404, "video_asset_not_found", "视频资产不存在或无访问权限")
    return asset_read(row)


# ---- 资源读取授权 --------------------------------------------------------


def _require_grant_manager(db, tenant_id, user):
    if not is_manager(membership(db, tenant_id, user.id)):
        fail(403, "forbidden", "当前角色无授权管理权限")


def _eligible_grantee(db, tenant_id, site_id, grantee_id):
    target = db.get(User, str(grantee_id))
    if not target or not target.is_active:
        fail(404, "user_not_found", "账号不存在")
    target_member = db.get(TenantMembership, (str(tenant_id), str(grantee_id)))
    if not target_member:
        # 非本机构成员与不存在的账号同样返回 404，避免泄露机构成员关系。
        fail(404, "user_not_found", "账号不存在")
    if target_member.role != "coach" or not db.get(SiteMembership, (str(tenant_id), str(site_id), str(grantee_id))):
        fail(422, "grantee_not_eligible", "受授人必须是本机构 coach 且具有该场馆访问权")
    return target


def _upsert_grant(db: Session, model, *, tenant_id, site_id, resource_key, resource_id,
                  session_id, grantee_id, grantor_id, expires_at, now):
    scope = [
        model.tenant_id == str(tenant_id),
        model.site_id == str(site_id),
        getattr(model, resource_key) == resource_id,
        model.grantee_user_id == str(grantee_id),
        model.revoked_at.is_(None),
    ]
    existing = db.scalar(select(model).where(*scope))
    if existing:
        existing.expires_at = expires_at
        existing.updated_at = now
        db.commit()
        return
    row = model(
        tenant_id=str(tenant_id), site_id=str(site_id), session_id=session_id,
        grantee_user_id=str(grantee_id), granted_by_user_id=grantor_id,
        granted_at=now, updated_at=now, expires_at=expires_at,
    )
    setattr(row, resource_key, resource_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # 并发写入由部分唯一索引裁定；输家改为刷新既有有效记录。
        db.rollback()
        existing = db.scalar(select(model).where(*scope))
        if not existing:
            fail(409, "state_conflict", "授权写入冲突")
        existing.expires_at = expires_at
        existing.updated_at = now
        db.commit()


def _revoke_grant(db: Session, model, *, tenant_id, site_id, resource_key, resource_id, grantee_id, user, now):
    scope = [
        model.tenant_id == str(tenant_id),
        model.site_id == str(site_id),
        getattr(model, resource_key) == resource_id,
        model.grantee_user_id == str(grantee_id),
        model.revoked_at.is_(None),
    ]
    result = db.execute(update(model).where(*scope).values(
        revoked_at=now, revoked_by_user_id=user.id, updated_at=now
    ))
    db.commit()
    return result.rowcount


@router.put(P + "/training-sessions/{session_id}/read-grants/{user_id}", status_code=204)
def put_session_grant(
    tenant_id: UUID, site_id: UUID, session_id: UUID, user_id: UUID, payload: GrantPut,
    request: Request, user: Current, db: DB,
):
    _require_grant_manager(db, tenant_id, user)
    _eligible_grantee(db, tenant_id, site_id, user_id)
    row = get_session(db, tenant_id, site_id, session_id)
    now = server_now(request)
    if payload.expires_at is not None and as_utc(payload.expires_at) <= now:
        fail(422, "validation_error", "expires_at 必须晚于当前时刻")
    _upsert_grant(
        db, SessionReadGrant, tenant_id=tenant_id, site_id=site_id, resource_key="session_id",
        resource_id=row.id, session_id=row.id, grantee_id=user_id, grantor_id=user.id,
        expires_at=payload.expires_at, now=now,
    )
    return Response(status_code=204)


@router.delete(P + "/training-sessions/{session_id}/read-grants/{user_id}", status_code=204)
def delete_session_grant(
    tenant_id: UUID, site_id: UUID, session_id: UUID, user_id: UUID, request: Request,
    user: Current, db: DB,
):
    _require_grant_manager(db, tenant_id, user)
    row = get_session(db, tenant_id, site_id, session_id)
    _revoke_grant(
        db, SessionReadGrant, tenant_id=tenant_id, site_id=site_id, resource_key="session_id",
        resource_id=row.id, grantee_id=user_id, user=user, now=server_now(request),
    )
    return Response(status_code=204)


@router.put(P + "/video-assets/{asset_id}/read-grants/{user_id}", status_code=204)
def put_asset_grant(
    tenant_id: UUID, site_id: UUID, asset_id: UUID, user_id: UUID, payload: GrantPut,
    request: Request, user: Current, db: DB,
):
    _require_grant_manager(db, tenant_id, user)
    _eligible_grantee(db, tenant_id, site_id, user_id)
    row = get_asset(db, tenant_id, site_id, asset_id)
    now = server_now(request)
    if payload.expires_at is not None and as_utc(payload.expires_at) <= now:
        fail(422, "validation_error", "expires_at 必须晚于当前时刻")
    _upsert_grant(
        db, AssetReadGrant, tenant_id=tenant_id, site_id=site_id, resource_key="asset_id",
        resource_id=row.id, session_id=row.session_id, grantee_id=user_id, grantor_id=user.id,
        expires_at=payload.expires_at, now=now,
    )
    return Response(status_code=204)


@router.delete(P + "/video-assets/{asset_id}/read-grants/{user_id}", status_code=204)
def delete_asset_grant(
    tenant_id: UUID, site_id: UUID, asset_id: UUID, user_id: UUID, request: Request,
    user: Current, db: DB,
):
    _require_grant_manager(db, tenant_id, user)
    row = get_asset(db, tenant_id, site_id, asset_id)
    _revoke_grant(
        db, AssetReadGrant, tenant_id=tenant_id, site_id=site_id, resource_key="asset_id",
        resource_id=row.id, grantee_id=user_id, user=user, now=server_now(request),
    )
    return Response(status_code=204)


# ---- 上传意图 ------------------------------------------------------------


def _asset_from_intent(
    *, tenant_id, site_id, session_id, origin, created_by_user_id, source_edge_node_id,
    source_device_id, payload, now,
) -> VideoAsset:
    meta = payload.capture_metadata
    return VideoAsset(
        tenant_id=str(tenant_id), site_id=str(site_id), session_id=session_id, origin=origin,
        created_by_user_id=created_by_user_id, source_edge_node_id=source_edge_node_id,
        source_device_id=source_device_id, status="pending_upload",
        capture_started_at_utc=meta.capture_started_at_utc, capture_ended_at_utc=meta.capture_ended_at_utc,
        device_capture_started_at_raw=meta.device_capture_started_at_raw,
        device_capture_ended_at_raw=meta.device_capture_ended_at_raw,
        device_time_basis=meta.device_time_basis, device_timezone=meta.device_timezone,
        device_utc_offset_minutes=meta.device_utc_offset_minutes,
        video_timebase_kind=meta.video_timebase_kind, video_timebase_metadata=meta.video_timebase_metadata,
        device_clock_source=meta.device_clock_source, device_clock_offset_ms=meta.device_clock_offset_ms,
        device_clock_accuracy_ms=meta.device_clock_accuracy_ms,
        media_type=payload.media_type, size_bytes=payload.expected_size_bytes,
        created_at=now, updated_at=now,
    )


def _find_intent_record(db: Session, *, tenant_id, site_id, operation, target_id, key_digest, user_id=None,
                        edge_node_id=None):
    query = select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == str(tenant_id),
        IdempotencyRecord.site_id == str(site_id),
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.target_id == str(target_id),
        IdempotencyRecord.key_hash == key_digest,
    )
    if edge_node_id is not None:
        query = query.where(IdempotencyRecord.actor_kind == "edge_node",
                            IdempotencyRecord.edge_node_id == edge_node_id)
    else:
        query = query.where(IdempotencyRecord.actor_kind == "user", IdempotencyRecord.user_id == user_id)
    return db.scalar(query)


def _replay_intent(db: Session, record: IdempotencyRecord, digest: str) -> UploadIntentRead:
    if record.request_hash != digest:
        fail(409, "idempotency_conflict", "同一幂等键已用于不同请求参数")
    upload = db.get(UploadSession, record.resource_id)
    if not upload:
        fail(409, "state_conflict", "幂等记录指向的上传会话不存在")
    asset = db.get(VideoAsset, upload.asset_id)
    if not asset:
        fail(409, "state_conflict", "幂等记录指向上传会话的资产不存在")
    return UploadIntentRead(upload_session=upload_read(upload), asset=asset_read(asset))


def _create_intent(
    db: Session, *, request, tenant_id, site_id, session, payload, origin,
    initiator_user_id=None, initiator_edge_node_id=None, source_edge_node_id=None, source_device_id=None,
    key_digest, digest,
):
    """单事务：Asset + UploadSession + 幂等记录，一次提交。"""
    now = server_now(request)
    asset = _asset_from_intent(
        tenant_id=tenant_id, site_id=site_id, session_id=session.id, origin=origin,
        created_by_user_id=initiator_user_id, source_edge_node_id=source_edge_node_id,
        source_device_id=source_device_id, payload=payload, now=now,
    )
    db.add(asset)
    db.flush()
    expires_at = now + timedelta(hours=UPLOAD_TTL_HOURS)
    upload = UploadSession(
        tenant_id=str(tenant_id), site_id=str(site_id), session_id=session.id, asset_id=asset.id,
        status="uploading", initiator_user_id=initiator_user_id,
        initiator_edge_node_id=initiator_edge_node_id,
        expected_size_bytes=payload.expected_size_bytes, expected_sha256=payload.expected_sha256,
        media_type=payload.media_type, expires_at=expires_at, created_at=now, updated_at=now,
    )
    db.add(upload)
    db.flush()
    db.add(IdempotencyRecord(
        tenant_id=str(tenant_id), site_id=str(site_id),
        actor_kind="edge_node" if initiator_edge_node_id else "user",
        user_id=initiator_user_id, edge_node_id=initiator_edge_node_id,
        operation="upload_intent.create", target_id=session.id, key_hash=key_digest,
        request_hash=digest, resource_kind="upload_session", resource_id=upload.id,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = _find_intent_record(
            db, tenant_id=tenant_id, site_id=site_id, operation="upload_intent.create",
            target_id=session.id, key_digest=key_digest, user_id=initiator_user_id,
            edge_node_id=initiator_edge_node_id,
        )
        if not replay:
            fail(409, "state_conflict", "上传意图写入冲突")
        return _replay_intent(db, replay, digest)
    return UploadIntentRead(upload_session=upload_read(upload), asset=asset_read(asset))


def _session_for_intent(db: Session, tenant_id, site_id, session_id) -> TrainingSession:
    row = get_session(db, tenant_id, site_id, session_id)
    if row.status == "cancelled":
        fail(409, "state_conflict", "已取消的会话不接受新的上传意图")
    return row


def _assert_intent_allowed(db: Session, session: TrainingSession, user, member, now):
    if not can_read_session(db, session, user, member, now):
        fail(404, "training_session_not_found", "训练会话不存在或无访问权限")
    if not can_manage_session(db, session, user, member):
        fail(403, "forbidden", "当前角色无该会话的上传权限")
    if session.status == "cancelled":
        fail(409, "state_conflict", "已取消的会话不接受新的上传意图")


@router.post(P + "/training-sessions/{session_id}/upload-sessions", response_model=UploadIntentRead, status_code=201)
def create_upload_intent(
    tenant_id: UUID, site_id: UUID, session_id: UUID, payload: UploadIntentCreate, request: Request,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")], user: Current, db: DB,
):
    _, member = _scope(db, tenant_id, site_id, user)
    session = get_session(db, tenant_id, site_id, session_id)
    now = server_now(request)
    _assert_intent_allowed(db, session, user, member, now)
    key_digest = idempotency_key_digest(idempotency_header)
    digest = request_digest(payload)
    existing = _find_intent_record(
        db, tenant_id=tenant_id, site_id=site_id, operation="upload_intent.create",
        target_id=session.id, key_digest=key_digest, user_id=user.id,
    )
    if existing:
        return _replay_intent(db, existing, digest)
    return _create_intent(
        db, request=request, tenant_id=tenant_id, site_id=site_id, session=session, payload=payload,
        origin="manual", initiator_user_id=user.id, key_digest=key_digest, digest=digest,
    )


def _materialize_expiry(db: Session, upload: UploadSession, now: datetime) -> bool:
    if upload.status != "uploading" or as_utc(upload.expires_at) > now:
        return False
    result = db.execute(update(UploadSession).where(
        UploadSession.id == upload.id, UploadSession.status == "uploading",
    ).values(status="expired", failure_reason="upload_expired", updated_at=now))
    if result.rowcount == 1:
        db.execute(update(VideoAsset).where(
            VideoAsset.id == upload.asset_id, VideoAsset.status == "pending_upload",
        ).values(status="failed", failure_reason="upload_expired", updated_at=now))
    db.commit()
    return result.rowcount == 1


def _user_can_touch_upload(db: Session, upload: UploadSession, session, user, member, now) -> bool:
    if upload.initiator_user_id != user.id:
        return False
    return can_read_session(db, session, user, member, now) and can_manage_session(db, session, user, member)


@router.get(P + "/upload-sessions/{upload_session_id}", response_model=UploadSessionRead)
def read_upload_session(
    tenant_id: UUID, site_id: UUID, upload_session_id: UUID, request: Request, user: Current, db: DB,
):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    upload = lock_upload(db, tenant_id, site_id, str(upload_session_id))
    if not upload:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session = get_session(db, tenant_id, site_id, UUID(upload.session_id))
    if not _user_can_touch_upload(db, upload, session, user, member, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    _materialize_expiry(db, upload, now)
    db.refresh(upload)
    return upload_read(upload)


@router.post(P + "/upload-sessions/{upload_session_id}/abort", status_code=204)
def abort_upload_session(
    tenant_id: UUID, site_id: UUID, upload_session_id: UUID, request: Request, user: Current, db: DB,
):
    _, member = _scope(db, tenant_id, site_id, user)
    now = server_now(request)
    upload = lock_upload(db, tenant_id, site_id, str(upload_session_id))
    if not upload:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session = get_session(db, tenant_id, site_id, UUID(upload.session_id))
    if not _user_can_touch_upload(db, upload, session, user, member, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if _materialize_expiry(db, upload, now):
        return Response(status_code=204)
    if upload.status != "uploading":
        db.rollback()
        return Response(status_code=204)
    result = db.execute(update(UploadSession).where(
        UploadSession.id == upload.id, UploadSession.status == "uploading",
    ).values(status="aborted", failure_reason="upload_aborted", updated_at=now))
    if result.rowcount == 1:
        db.execute(update(VideoAsset).where(
            VideoAsset.id == upload.asset_id, VideoAsset.status == "pending_upload",
        ).values(status="failed", failure_reason="upload_aborted", updated_at=now))
    db.commit()
    return Response(status_code=204)


# ---- Edge 上传意图 -------------------------------------------------------


@router.post("/edge/sessions/{session_id}/upload-sessions", response_model=UploadIntentRead, status_code=201)
def create_edge_upload_intent(
    session_id: UUID, payload: EdgeUploadIntentCreate, request: Request, db: DB,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
):
    now = server_now(request)
    node, _ = get_edge_identity(db, authorization, now)
    session = _session_for_intent(db, node.tenant_id, node.site_id, session_id)
    device = db.get(Device, str(payload.device_id))
    if (
        not device
        or device.tenant_id != node.tenant_id
        or device.site_id != node.site_id
        or device.edge_node_id != node.id
    ):
        fail(404, "device_not_found", "设备不存在或不属于该节点")
    if device.status != "active":
        fail(409, "state_conflict", "设备已停用，不能创建上传意图")
    key_digest = idempotency_key_digest(idempotency_header)
    digest = request_digest(payload)
    existing = _find_intent_record(
        db, tenant_id=node.tenant_id, site_id=node.site_id, operation="upload_intent.create",
        target_id=session.id, key_digest=key_digest, edge_node_id=node.id,
    )
    if existing:
        return _replay_intent(db, existing, digest)
    return _create_intent(
        db, request=request, tenant_id=node.tenant_id, site_id=node.site_id, session=session,
        payload=payload, origin="edge", initiator_edge_node_id=node.id,
        source_edge_node_id=node.id, source_device_id=device.id, key_digest=key_digest, digest=digest,
    )


def _edge_upload(db: Session, node, upload_id: str) -> UploadSession:
    upload = lock_upload(db, node.tenant_id, node.site_id, upload_id)
    if not upload or upload.initiator_edge_node_id != node.id:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    return upload


@router.get("/edge/upload-sessions/{upload_session_id}", response_model=UploadSessionRead)
def read_edge_upload_session(
    upload_session_id: UUID, request: Request, db: DB,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
):
    now = server_now(request)
    node, _ = get_edge_identity(db, authorization, now)
    upload = _edge_upload(db, node, str(upload_session_id))
    _materialize_expiry(db, upload, now)
    return upload_read(_edge_upload(db, node, str(upload_session_id)))


@router.post("/edge/upload-sessions/{upload_session_id}/abort", status_code=204)
def abort_edge_upload_session(
    upload_session_id: UUID, request: Request, db: DB,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
):
    now = server_now(request)
    node, _ = get_edge_identity(db, authorization, now)
    upload = _edge_upload(db, node, str(upload_session_id))
    if _materialize_expiry(db, upload, now):
        return Response(status_code=204)
    if upload.status != "uploading":
        db.rollback()
        return Response(status_code=204)
    result = db.execute(update(UploadSession).where(
        UploadSession.id == upload.id, UploadSession.status == "uploading",
    ).values(status="aborted", failure_reason="upload_aborted", updated_at=now))
    if result.rowcount == 1:
        db.execute(update(VideoAsset).where(
            VideoAsset.id == upload.asset_id, VideoAsset.status == "pending_upload",
        ).values(status="failed", failure_reason="upload_aborted", updated_at=now))
    db.commit()
    return Response(status_code=204)
