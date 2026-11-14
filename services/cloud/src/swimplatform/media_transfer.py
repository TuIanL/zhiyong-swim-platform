"""M3 media transfer API and durable work processing.

External storage I/O is always between short SQL transactions. Every path which
mutates an upload follows Session → UploadSession → Asset → MediaObject → Job/Parts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import secrets
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import Current, DB, as_utc, fail, membership, site_access
from .edge_registry import (
    get_edge_identity_unlocked, idempotency_key_digest, lock_edge_identity, request_digest, server_now,
)
from .media import (
    MAX_NEW_INTENT_BYTES, _edge_upload, _user_can_touch_upload,
)
from .media_access import asset_read_predicate, can_read_asset
from .models import (
    AssetReadGrant, AuthSession, Device, EdgeCredential, EdgeNode, IdempotencyRecord,
    MediaCleanupCandidate,
    MediaJob, MediaObject, SiteMembership, TenantMembership, TrainingSession, UploadPart, UploadSession,
    SessionReadGrant, Site, User, VideoAsset, uid,
)
from .schemas import (
    AccessUrlRead, CompleteRead, CompleteRequest, PartConfirmedRead, PartConfirmation,
    PartPage, PartURLRead, PartURLsRequest, PreparationRead,
)
from .storage import StorageError, StorageProvider

router = APIRouter(prefix="/api/v1")
P = "/tenants/{tenant_id}/sites/{site_id}"
PART_BYTES = 16 * 1024 * 1024
MAX_PARTS_PER_UPLOAD = 10_000
MAX_PART_URL_TTL = 300
LEASE_SECONDS = 120
LEASE_RENEW_SECONDS = 30
MAX_JOB_ATTEMPTS = 5
ORPHAN_OBSERVATION_GRACE = timedelta(minutes=15)


def _provider(request: Request) -> StorageProvider:
    provider = getattr(request.app.state, "storage_provider", None)
    settings = request.app.state.settings
    if not settings.media_enabled or provider is None:
        fail(503, "storage_unavailable", "媒体传输 profile 未启用")
    return provider


def _lock_asset(db: Session, tenant_id: str, site_id: str, asset_id: str) -> VideoAsset | None:
    scope = (VideoAsset.id == asset_id, VideoAsset.tenant_id == tenant_id, VideoAsset.site_id == site_id)
    query = select(VideoAsset).where(*scope).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        result = db.execute(update(VideoAsset).where(*scope).values(updated_at=VideoAsset.updated_at))
        if result.rowcount != 1:
            return None
    return db.scalar(query)


def _lock_object(db: Session, tenant_id: str, site_id: str, upload_id: str) -> MediaObject | None:
    scope = (MediaObject.upload_session_id == upload_id,
             MediaObject.tenant_id == tenant_id, MediaObject.site_id == site_id)
    query = select(MediaObject).where(*scope).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        result = db.execute(update(MediaObject).where(*scope).values(updated_at=MediaObject.updated_at))
        if result.rowcount != 1:
            return None
    return db.scalar(query)


def _lock_transfer(db: Session, tenant_id: str, site_id: str, upload_id: str):
    """Acquire all business locks in the single documented parent-first order."""
    from .media import get_upload, lock_session_upload

    discovered = get_upload(db, UUID(tenant_id), UUID(site_id), UUID(upload_id))
    locked = lock_session_upload(db, UUID(tenant_id), UUID(site_id), upload_id)
    if not locked:
        return None
    session, upload = locked
    asset = _lock_asset(db, tenant_id, site_id, upload.asset_id)
    if not asset or asset.session_id != session.id:
        return None
    obj = _lock_object(db, tenant_id, site_id, upload_id)
    if discovered.session_id != session.id:
        return None
    return session, upload, asset, obj


def _user_transfer(db: Session, request: Request, tenant_id, site_id, upload_id, user):
    tenant, site = str(tenant_id), str(site_id)
    _, member = (site_access(db, tenant, site, user), membership(db, tenant, user.id))
    from .media import get_session, get_upload

    candidate = get_upload(db, tenant_id, site_id, upload_id)
    session = get_session(db, tenant_id, site_id, UUID(candidate.session_id))
    now = server_now(request)
    if not _user_can_touch_upload(db, candidate, session, user, member, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    locked = _lock_transfer(db, tenant, site, str(upload_id))
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, obj = locked
    if not _user_can_touch_upload(db, upload, session, user, member, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    return session, upload, asset, obj, member


def _edge_transfer(db: Session, node, credential, upload_id, now):
    upload = _edge_upload(db, node, str(upload_id))
    session, locked_upload, asset, obj = _lock_transfer(
        db, node.tenant_id, node.site_id, str(upload_id)
    )
    if locked_upload.initiator_edge_node_id != node.id:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    lock_edge_identity(db, node.id, credential.id, now)
    return session, locked_upload, asset, obj


def _terminalize_locked(db: Session, upload: UploadSession, asset: VideoAsset,
                        obj: MediaObject | None, reason: str, now: datetime) -> bool:
    """Pair an unfinished upload and Asset while the parent-first locks are held."""
    if upload.status not in {"uploading", "completing"} or asset.status != "pending_upload":
        return False
    upload_status = {
        "upload_aborted": "aborted", "upload_expired": "expired",
        "session_cancelled": "failed", "upload_failed": "failed",
        "validation_failed": "failed",
    }.get(reason)
    if upload_status is None:
        raise ValueError(f"unsupported upload failure reason: {reason}")
    upload.status, upload.failure_reason, upload.updated_at = upload_status, reason, now
    asset.status, asset.failure_reason, asset.updated_at = "failed", reason, now
    if obj:
        obj.phase, obj.updated_at = "delete_pending", now
        db.execute(update(MediaJob).where(
            MediaJob.object_id == obj.id,
            MediaJob.state.in_(("queued", "running", "retry_wait")),
        ).values(state="succeeded", lease_token=None, lease_until=None,
                 last_error_code=reason[:64], updated_at=now))
        kind = "object" if obj.object_version else "multipart"
        _enqueue_cleanup(db=db, obj=obj, kind=kind,
                         upload_id=None if kind == "object" else obj.provider_upload_id, now=now)
    return True


def _check_open(db: Session, session: TrainingSession, upload: UploadSession,
                asset: VideoAsset, obj: MediaObject | None, now: datetime):
    if upload.status != "uploading":
        _terminal_conflict(upload)
    if as_utc(upload.expires_at) <= now:
        _terminalize_locked(db, upload, asset, obj, "upload_expired", now)
        return False
    if session.status == "cancelled":
        _terminalize_locked(db, upload, asset, obj, "session_cancelled", now)
        return False
    if asset.status != "pending_upload":
        fail(409, "state_conflict", "资产状态不允许继续传输")
    return True


def _terminal_conflict(upload: UploadSession):
    if upload.status in {"failed", "expired", "aborted"}:
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if upload.status == "completed":
        fail(409, "state_conflict", "上传已经完成")
    fail(409, "state_conflict", "上传当前状态不允许此操作")


def expire_existing_upload(db: Session, upload: UploadSession, now: datetime) -> bool:
    """Expire while the caller already holds Session then UploadSession locks."""
    if upload.status not in {"uploading", "completing"} or as_utc(upload.expires_at) > now:
        return False
    asset = _lock_asset(db, upload.tenant_id, upload.site_id, upload.asset_id)
    if not asset:
        db.rollback()
        fail(409, "state_conflict", "上传资产不存在")
    obj = _lock_object(db, upload.tenant_id, upload.site_id, upload.id)
    if not _terminalize_locked(db, upload, asset, obj, "upload_expired", now):
        db.rollback()
        return False
    db.commit()
    return True


def abort_existing_upload(db: Session, upload: UploadSession, now: datetime) -> bool:
    """Abort an active upload using the canonical parent-first lock order."""
    if upload.status not in {"uploading", "completing"}:
        return False
    asset = _lock_asset(db, upload.tenant_id, upload.site_id, upload.asset_id)
    if not asset:
        db.rollback()
        fail(409, "state_conflict", "上传资产不存在")
    obj = _lock_object(db, upload.tenant_id, upload.site_id, upload.id)
    if not _terminalize_locked(db, upload, asset, obj, "upload_aborted", now):
        db.rollback()
        return False
    db.commit()
    return True


def cancel_session_uploads(db: Session, session: TrainingSession, now: datetime):
    """Cancel all not-yet-ready uploads, locking each entity level in order."""
    query = select(UploadSession).where(
        UploadSession.tenant_id == session.tenant_id,
        UploadSession.site_id == session.site_id,
        UploadSession.session_id == session.id,
        UploadSession.status.in_(("uploading", "completing")),
    ).order_by(UploadSession.id)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    uploads = db.scalars(query).all()
    if not uploads:
        return
    ids = [upload.id for upload in uploads]
    asset_query = select(VideoAsset).where(
        VideoAsset.tenant_id == session.tenant_id, VideoAsset.site_id == session.site_id,
        VideoAsset.session_id == session.id, VideoAsset.id.in_([u.asset_id for u in uploads]),
    ).order_by(VideoAsset.id)
    if db.bind.dialect.name == "postgresql":
        asset_query = asset_query.with_for_update()
    assets = db.scalars(asset_query).all()
    object_query = select(MediaObject).where(
        MediaObject.tenant_id == session.tenant_id, MediaObject.site_id == session.site_id,
        MediaObject.session_id == session.id, MediaObject.upload_session_id.in_(ids),
    ).order_by(MediaObject.id)
    if db.bind.dialect.name == "postgresql":
        object_query = object_query.with_for_update()
    objects = db.scalars(object_query).all()
    asset_by_id, object_by_upload = ({a.id: a for a in assets}, {o.upload_session_id: o for o in objects})
    for upload in uploads:
        asset = asset_by_id.get(upload.asset_id)
        if asset:
            _terminalize_locked(db, upload, asset, object_by_upload.get(upload.id),
                                "session_cancelled", now)


def _enqueue_cleanup(*, db: Session, obj: MediaObject, kind: str, upload_id: str | None, now: datetime):
    identity = f"{obj.provider_profile}\0{obj.bucket}\0{obj.object_key}\0{upload_id or ''}\0{obj.object_version or ''}"
    identity_hash = hashlib.sha256(identity.encode()).hexdigest()
    existing = db.scalar(select(MediaCleanupCandidate).where(MediaCleanupCandidate.identity_hash == identity_hash))
    if existing:
        return existing
    row = MediaCleanupCandidate(
        tenant_id=obj.tenant_id, site_id=obj.site_id, object_id=obj.id,
        session_id=obj.session_id, asset_id=obj.asset_id,
        provider_profile=obj.provider_profile, bucket=obj.bucket, object_key=obj.object_key,
        upload_id=upload_id, object_version=obj.object_version, kind=kind,
        identity_hash=identity_hash, first_seen_at=now, last_seen_at=now,
        not_before=max(now, as_utc(obj.last_signed_write_expires_at) or now) + timedelta(minutes=5),
        state="queued", next_attempt_at=now,
    )
    db.add(row)
    return row


def _object_key(tenant_id: str, site_id: str, session_id: str, asset_id: str,
                upload_id: str, generation: int, run_id: str | None = None) -> str:
    if run_id:
        return f"private/test/{run_id}/{tenant_id}/{site_id}/{session_id}/{asset_id}/{upload_id}/g{generation}"
    return f"private/{tenant_id}/{site_id}/{session_id}/{asset_id}/{upload_id}/g{generation}"


def _part_size(upload: UploadSession, number: int) -> int:
    if upload.part_size_bytes is None or upload.part_count is None or not 1 <= number <= upload.part_count:
        fail(422, "validation_error", "分片编号超出已登记布局")
    if number < upload.part_count:
        return upload.part_size_bytes
    return upload.expected_size_bytes - upload.part_size_bytes * (upload.part_count - 1)


def _preparation(upload: UploadSession) -> PreparationRead:
    return PreparationRead(
        upload_session_id=upload.id, asset_id=upload.asset_id,
        transfer_status="preparing", poll_url=f"/api/v1/upload-sessions/{upload.id}",
        retry_after_seconds=2,
    )


def _add_headers(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


def _manifest_digest(parts: list[dict]) -> str:
    normalized = [{"part_number": p["part_number"], "etag": p["etag"]} for p in parts]
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _all_provider_parts(provider: StorageProvider, obj: MediaObject) -> dict[int, dict]:
    if not obj.provider_upload_id:
        return {}
    marker = 0
    collected: dict[int, dict] = {}
    for _ in range(20):
        page = provider.list_parts(obj.object_key, obj.provider_upload_id, marker)
        for part in page["parts"]:
            number = int(part["PartNumber"])
            if number in collected:
                fail(503, "storage_unavailable", "对象存储返回重复分片编号")
            collected[number] = part
        if not page["truncated"]:
            return collected
        next_marker = page["next_marker"]
        if not next_marker or next_marker <= marker:
            fail(503, "storage_unavailable", "对象存储分片分页游标异常")
        marker = next_marker
    fail(503, "storage_unavailable", "对象存储分片分页超过有界上限")


def _find_multipart_uploads(provider: StorageProvider, key: str) -> list[str]:
    key_marker = upload_marker = None
    found: list[str] = []
    for _ in range(20):
        page = provider.list_multipart_uploads(key, key_marker, upload_marker)
        found.extend(str(item["UploadId"]) for item in page["uploads"] if item.get("Key") == key)
        if not page["truncated"]:
            return sorted(set(found))
        next_key, next_upload = page["key_marker"], page["upload_marker"]
        if not next_key or (next_key, next_upload) == (key_marker, upload_marker):
            fail(503, "storage_unavailable", "对象存储 multipart 分页游标异常")
        key_marker, upload_marker = next_key, next_upload
    fail(503, "storage_unavailable", "对象存储 multipart 分页超过有界上限")


def _same_etag(left: str, right: str) -> bool:
    return left.strip() == right.strip()


def _part_page(rows, generation: int, *, tenant_id: str, site_id: str, upload_id: str,
               limit: int, cursor: str | None):
    from .media_access import _encode, decode_cursor
    after = 0
    filters = {"upload_id": upload_id, "generation": generation}
    if cursor:
        _, row_id = decode_cursor(cursor, kind="media_part", tenant_id=tenant_id,
                                  site_id=site_id, filters=filters)
        try:
            after = int(row_id)
        except ValueError:
            fail(422, "invalid_cursor", "分片游标无效")
    selected = [p for p in rows if p.state in {"confirmed", "stale"} and p.part_number > after]
    page = selected[:limit + 1]
    has_more = len(page) > limit
    page = page[:limit]
    encoded = None
    if has_more and page:
        encoded = _encode("media_part", tenant_id, site_id, filters,
                          datetime(1970, 1, 1, tzinfo=UTC), str(page[-1].part_number))
    return PartPage(items=[PartConfirmedRead(part_number=p.part_number,
                                             size_bytes=p.actual_size_bytes,
                                             etag=p.etag,
                                             confirmed_at=as_utc(p.confirmed_at),
                                             state=p.state) for p in page],
                    next_cursor=encoded)


def _status_response(upload: UploadSession, asset: VideoAsset, *, poll_url: str) -> CompleteRead:
    from .media import asset_read, upload_read
    return CompleteRead(upload_session=upload_read(upload), asset=asset_read(asset), poll_url=poll_url)


def _user_identity_snapshot(db: Session, request: Request, user) -> dict:
    token_hash = getattr(request.state, "session_hash", None)
    auth = db.get(AuthSession, token_hash) if token_hash else None
    if not auth or auth.user_id != user.id:
        fail(401, "unauthorized", "登录已失效")
    return {"accepted_actor_kind": "user", "accepted_user_id": user.id,
            "accepted_auth_session_hash": token_hash}


def _edge_identity_snapshot(node, credential) -> dict:
    return {"accepted_actor_kind": "edge_node", "accepted_edge_node_id": node.id,
            "accepted_credential_id": credential.id}


def _create_idempotency(db: Session, *, tenant_id, site_id, actor_kind, actor_id,
                        operation, target_id, key_digest, digest, upload):
    row = IdempotencyRecord(
        tenant_id=tenant_id, site_id=site_id, actor_kind=actor_kind,
        user_id=actor_id if actor_kind == "user" else None,
        edge_node_id=actor_id if actor_kind == "edge_node" else None,
        operation=operation, target_id=target_id, key_hash=key_digest,
        request_hash=digest, resource_kind="upload_session", resource_id=upload.id,
    )
    db.add(row)
    return row


def _completion_result(db: Session, upload: UploadSession, asset: VideoAsset, *, poll_url: str):
    if upload.status in {"failed", "expired", "aborted"}:
        db.rollback()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if upload.status == "completed" and asset.status == "ready":
        return JSONResponse(status_code=200, content=_status_response(upload, asset, poll_url=poll_url).model_dump(mode="json"))
    return JSONResponse(status_code=202, content=_status_response(upload, asset, poll_url=poll_url).model_dump(mode="json"),
                        headers={"Location": poll_url, "Retry-After": "2"})


def _validate_manifest(payload: CompleteRequest, upload: UploadSession, rows: list[UploadPart]):
    parts = [p.model_dump() for p in payload.parts]
    numbers = [p["part_number"] for p in parts]
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        fail(422, "validation_error", "manifest 必须按分片编号升序且不重复")
    if upload.part_count is None or numbers != list(range(1, upload.part_count + 1)):
        fail(409, "part_not_confirmed", "manifest 未覆盖完整分片布局")
    by_number = {row.part_number: row for row in rows if row.state == "confirmed"}
    if len(by_number) != upload.part_count:
        fail(409, "part_not_confirmed", "仍有分片尚未确认")
    for part in parts:
        row = by_number.get(part["part_number"])
        if not row or not row.etag or not _same_etag(row.etag, part["etag"]):
            fail(409, "part_not_confirmed", "manifest 与已确认回执不一致")
    return parts


def _complete(
    *, db: Session, request: Request, provider: StorageProvider, tenant_id: str, site_id: str,
    upload_id: str, payload: CompleteRequest, key_header: str, actor_kind: str,
    actor_id: str, accepted: dict, authorized, identity_recheck=None,
):
    locked = _lock_transfer(db, tenant_id, site_id, upload_id)
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, obj = locked
    now = server_now(request)
    if not authorized(session, upload, asset, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if identity_recheck:
        identity_recheck()
    key_digest = idempotency_key_digest(key_header)
    digest = request_digest(payload)
    idem = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.site_id == site_id,
        IdempotencyRecord.actor_kind == actor_kind,
        IdempotencyRecord.user_id == (actor_id if actor_kind == "user" else None),
        IdempotencyRecord.edge_node_id == (actor_id if actor_kind == "edge_node" else None),
        IdempotencyRecord.operation == "upload.complete", IdempotencyRecord.target_id == upload_id,
        IdempotencyRecord.key_hash == key_digest,
    ))
    if idem and idem.request_hash != digest:
        db.rollback()
        fail(409, "idempotency_conflict", "同一幂等键已用于不同 manifest")
    if upload.status in {"uploading", "completing"} and (
        session.status == "cancelled" or as_utc(upload.expires_at) <= now
    ):
        reason = "session_cancelled" if session.status == "cancelled" else "upload_expired"
        _terminalize_locked(db, upload, asset, obj, reason, now)
        db.commit()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    requested_parts = [part.model_dump() for part in payload.parts]
    if idem:
        return _completion_result(db, upload, asset, poll_url=f"/api/v1/upload-sessions/{upload_id}")
    numbers = [part["part_number"] for part in requested_parts]
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        db.rollback()
        fail(422, "validation_error", "manifest 必须按分片编号升序且不重复")
    manifest_hash = _manifest_digest(requested_parts)
    # Once a completion manifest has been accepted, every later key is bound to it.
    if upload.complete_manifest_hash and upload.complete_manifest_hash != manifest_hash:
        db.rollback()
        fail(409, "state_conflict", "此上传已接受不同的完成清单")

    if upload.status in {"failed", "expired", "aborted"}:
        db.rollback()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if upload.status == "completed":
        if upload.complete_manifest_hash != manifest_hash or asset.status != "ready":
            db.rollback()
            fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
        _create_idempotency(db, tenant_id=tenant_id, site_id=site_id,
                            actor_kind=actor_kind, actor_id=actor_id, operation="upload.complete",
                            target_id=upload_id, key_digest=key_digest, digest=digest, upload=upload)
        db.commit()
        return _completion_result(db, upload, asset, poll_url=f"/api/v1/upload-sessions/{upload_id}")
    if upload.expected_size_bytes > MAX_NEW_INTENT_BYTES:
        db.rollback()
        fail(409, "transfer_policy_conflict", "历史意图超过 M3 物理传输策略上限")
    if not obj or obj.phase != "uploading" or not obj.provider_upload_id:
        db.rollback()
        fail(409, "state_conflict", "分片传输尚未准备完成")

    existing_job = db.scalar(select(MediaJob).where(MediaJob.object_id == obj.id, MediaJob.kind == "complete"))
    if upload.status == "completing":
        if not existing_job or upload.complete_manifest_hash != manifest_hash:
            db.rollback()
            fail(409, "state_conflict", "现有完成工作与本次 manifest 不一致")
        # A different key may observe the same durable operation but cannot create another worker.
        _create_idempotency(db, tenant_id=tenant_id, site_id=site_id,
                            actor_kind=actor_kind, actor_id=actor_id, operation="upload.complete",
                            target_id=upload_id, key_digest=key_digest, digest=digest, upload=upload)
        db.commit()
        return _completion_result(db, upload, asset, poll_url=f"/api/v1/upload-sessions/{upload_id}")

    rows_query = select(UploadPart).where(
        UploadPart.tenant_id == tenant_id, UploadPart.site_id == site_id,
        UploadPart.upload_session_id == upload_id,
    ).order_by(UploadPart.part_number)
    if db.bind.dialect.name == "postgresql":
        rows_query = rows_query.with_for_update()
    rows = db.scalars(rows_query).all()
    parts = _validate_manifest(payload, upload, rows)
    manifest_hash = _manifest_digest(parts)

    upload.status = "completing"
    upload.complete_manifest_hash = manifest_hash
    upload.complete_requested_at = now
    upload.updated_at = now
    for row in rows:
        row.request_hash = manifest_hash
        row.updated_at = now
    job = MediaJob(
        tenant_id=tenant_id, site_id=site_id, session_id=session.id,
        asset_id=asset.id, object_id=obj.id, kind="complete", state="queued",
        attempts=0, generation=1, next_attempt_at=now, updated_at=now, **accepted,
    )
    db.add(job)
    _create_idempotency(db, tenant_id=tenant_id, site_id=site_id,
                        actor_kind=actor_kind, actor_id=actor_id, operation="upload.complete",
                        target_id=upload_id, key_digest=key_digest, digest=digest, upload=upload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "state_conflict", "完成请求正在被另一个事务接受")
    return JSONResponse(status_code=202,
                        content=_status_response(upload, asset, poll_url=f"/api/v1/upload-sessions/{upload_id}").model_dump(mode="json"),
                        headers={"Location": f"/api/v1/upload-sessions/{upload_id}", "Retry-After": "2"})


@router.post(P + "/upload-sessions/{upload_session_id}/part-urls")
def user_part_urls(tenant_id: UUID, site_id: UUID, upload_session_id: UUID,
                   payload: PartURLsRequest, request: Request, response: Response,
                   user: Current, db: DB):
    provider = _provider(request)
    session, upload, asset, obj, _ = _user_transfer(db, request, tenant_id, site_id, upload_session_id, user)
    now = server_now(request)
    if not _check_open(db, session, upload, asset, obj, now):
        db.commit()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if upload.expected_size_bytes > MAX_NEW_INTENT_BYTES:
        db.rollback()
        fail(409, "transfer_policy_conflict", "历史意图超过 M3 物理传输策略上限")
    settings = request.app.state.settings
    part_size = settings.media_part_size_bytes
    count = math.ceil(upload.expected_size_bytes / part_size)
    if count > MAX_PARTS_PER_UPLOAD:
        db.rollback()
        fail(409, "transfer_policy_conflict", "声明大小超过当前分片布局能力")
    if any(number > count for number in payload.part_numbers):
        db.rollback()
        fail(422, "validation_error", "分片编号超出上传布局")
    if obj is None:
        upload.part_size_bytes, upload.part_count = part_size, count
        now = server_now(request)
        obj = MediaObject(
            tenant_id=upload.tenant_id, site_id=upload.site_id, session_id=upload.session_id,
            asset_id=asset.id, upload_session_id=upload.id, provider_profile=provider.profile,
            bucket=provider.bucket, object_key=_object_key(upload.tenant_id, upload.site_id,
                upload.session_id, asset.id, upload.id, 1, settings.media_run_id),
            phase="preparing", generation=1,
            created_at=now, updated_at=now,
        )
        db.add(obj)
        db.flush()
        db.add(MediaJob(tenant_id=upload.tenant_id, site_id=upload.site_id,
                        session_id=upload.session_id, asset_id=asset.id, object_id=obj.id,
                        kind="initialize", state="queued", attempts=0, generation=1,
                        next_attempt_at=now, updated_at=now))
        db.commit()
        body = _preparation(upload).model_dump(mode="json")
        return JSONResponse(status_code=202, content=body,
                            headers={"Location": body["poll_url"], "Retry-After": "2"})
    if obj.phase in {"reserved", "preparing"} or not obj.provider_upload_id:
        db.rollback()
        body = _preparation(upload).model_dump(mode="json")
        return JSONResponse(status_code=202, content=body,
                            headers={"Location": body["poll_url"], "Retry-After": "2"})
    if obj.phase != "uploading":
        db.rollback()
        fail(409, "state_conflict", "物理上传当前不可签名")
    auth = db.get(AuthSession, getattr(request.state, "session_hash", None))
    if not auth or as_utc(auth.expires_at) <= now:
        db.rollback()
        fail(401, "unauthorized", "登录已失效")
    auth_remaining = int((as_utc(auth.expires_at) - now).total_seconds())
    if auth_remaining < 1:
        db.rollback()
        fail(401, "unauthorized", "登录即将失效，无法签发分片 URL")
    expires_seconds = min(settings.media_part_url_seconds, MAX_PART_URL_TTL, auth_remaining)
    expires_at = now + timedelta(seconds=expires_seconds)
    if as_utc(upload.expires_at) <= expires_at:
        expires_seconds = int((as_utc(upload.expires_at) - now).total_seconds())
        if expires_seconds < 1:
            db.rollback()
            fail(409, "upload_not_completable", "上传意图即将到期，无法签发分片 URL")
        expires_at = now + timedelta(seconds=expires_seconds)
    if expires_at <= now:
        db.rollback()
        fail(409, "upload_not_completable", "上传意图已到期")
    numbers = payload.part_numbers
    expected = {number: _part_size(upload, number) for number in numbers}
    for number, size in expected.items():
        part = db.scalar(select(UploadPart).where(UploadPart.upload_session_id == upload.id,
                                                  UploadPart.part_number == number))
        if not part:
            part = UploadPart(tenant_id=upload.tenant_id, site_id=upload.site_id,
                              session_id=upload.session_id, asset_id=asset.id,
                              upload_session_id=upload.id, part_number=number,
                              expected_size_bytes=size, state="registered", created_at=now, updated_at=now)
            db.add(part)
        elif part.expected_size_bytes != size:
            db.rollback()
            fail(409, "state_conflict", "已登记分片布局与当前配置不一致")
    obj.last_signed_write_expires_at = max(
        [as_utc(obj.last_signed_write_expires_at) or now, expires_at]
    )
    obj.updated_at = now
    key, upload_id = obj.object_key, obj.provider_upload_id
    db.commit()
    try:
        items = [PartURLRead(part_number=n, url=provider.sign_part(key, upload_id, n, expires_seconds),
                             expires_at=expires_at, expected_size_bytes=size,
                             required_headers={}).model_dump(mode="json")
                 for n, size in expected.items()]
    except StorageError:
        fail(503, "storage_unavailable", "暂时无法签发分片 URL")
    _add_headers(response)
    return {"items": items}


@router.post("/edge/upload-sessions/{upload_session_id}/part-urls")
def edge_part_urls(upload_session_id: UUID, payload: PartURLsRequest, request: Request,
                   response: Response, db: DB,
                   authorization: Annotated[str | None, Header(alias="Authorization")] = None):
    now = server_now(request)
    node, credential = get_edge_identity_unlocked(db, authorization, now)
    # Reuse the user implementation's transaction and layout logic after Edge scope authentication.
    provider = _provider(request)
    session, upload, asset, obj = _edge_transfer(db, node, credential, upload_session_id, now)
    if not _check_open(db, session, upload, asset, obj, now):
        db.commit()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if upload.expected_size_bytes > MAX_NEW_INTENT_BYTES:
        db.rollback()
        fail(409, "transfer_policy_conflict", "历史意图超过 M3 物理传输策略上限")
    settings = request.app.state.settings
    part_size = settings.media_part_size_bytes
    count = math.ceil(upload.expected_size_bytes / part_size)
    if count > MAX_PARTS_PER_UPLOAD:
        db.rollback()
        fail(409, "transfer_policy_conflict", "声明大小超过当前分片布局能力")
    if any(number > count for number in payload.part_numbers):
        db.rollback()
        fail(422, "validation_error", "分片编号超出上传布局")
    if obj is None:
        upload.part_size_bytes, upload.part_count = part_size, count
        obj = MediaObject(tenant_id=upload.tenant_id, site_id=upload.site_id,
                          session_id=upload.session_id, asset_id=asset.id,
                          upload_session_id=upload.id, provider_profile=provider.profile,
                          bucket=provider.bucket, object_key=_object_key(upload.tenant_id, upload.site_id,
                              upload.session_id, asset.id, upload.id, 1, settings.media_run_id),
                          phase="preparing", generation=1,
                          created_at=now, updated_at=now)
        db.add(obj)
        db.flush()
        db.add(MediaJob(tenant_id=upload.tenant_id, site_id=upload.site_id,
                        session_id=upload.session_id, asset_id=asset.id, object_id=obj.id,
                        kind="initialize", state="queued", attempts=0, generation=1,
                        next_attempt_at=now, updated_at=now))
        db.commit()
        body = _preparation(upload).model_dump(mode="json")
        return JSONResponse(status_code=202, content=body,
                            headers={"Location": body["poll_url"], "Retry-After": "2"})
    if obj.phase in {"reserved", "preparing"} or not obj.provider_upload_id:
        db.rollback()
        body = _preparation(upload).model_dump(mode="json")
        return JSONResponse(status_code=202, content=body,
                            headers={"Location": body["poll_url"], "Retry-After": "2"})
    if obj.phase != "uploading":
        db.rollback()
        fail(409, "state_conflict", "物理上传当前不可签名")
    credential_remaining = int((as_utc(credential.expires_at) - now).total_seconds())
    if credential_remaining < 1:
        db.rollback()
        fail(401, "edge_unauthorized", "节点凭据即将失效，无法签发分片 URL")
    expires_seconds = min(settings.media_part_url_seconds, MAX_PART_URL_TTL, credential_remaining)
    expires_at = now + timedelta(seconds=expires_seconds)
    if as_utc(upload.expires_at) <= expires_at:
        expires_seconds = int((as_utc(upload.expires_at) - now).total_seconds())
        if expires_seconds < 1:
            db.rollback()
            fail(409, "upload_not_completable", "上传意图即将到期，无法签发分片 URL")
        expires_at = now + timedelta(seconds=expires_seconds)
    if expires_at <= now:
        db.rollback()
        fail(409, "upload_not_completable", "上传意图已到期")
    expected = {n: _part_size(upload, n) for n in payload.part_numbers}
    for number, size in expected.items():
        part = db.scalar(select(UploadPart).where(UploadPart.upload_session_id == upload.id,
                                                  UploadPart.part_number == number))
        if not part:
            db.add(UploadPart(tenant_id=upload.tenant_id, site_id=upload.site_id,
                              session_id=upload.session_id, asset_id=asset.id,
                              upload_session_id=upload.id, part_number=number,
                              expected_size_bytes=size, state="registered", created_at=now, updated_at=now))
        elif part.expected_size_bytes != size:
            db.rollback()
            fail(409, "state_conflict", "已登记分片布局与当前配置不一致")
    obj.last_signed_write_expires_at = max(as_utc(obj.last_signed_write_expires_at) or now, expires_at)
    key, provider_upload_id = obj.object_key, obj.provider_upload_id
    db.commit()
    try:
        items = [PartURLRead(part_number=n,
                             url=provider.sign_part(key, provider_upload_id, n, expires_seconds),
                             expires_at=expires_at, expected_size_bytes=size,
                             required_headers={}).model_dump(mode="json")
                 for n, size in expected.items()]
    except StorageError:
        fail(503, "storage_unavailable", "暂时无法签发分片 URL")
    _add_headers(response)
    return {"items": items}


def _confirm_part(*, db: Session, request: Request, provider: StorageProvider,
                  tenant_id: str, site_id: str, upload_id: str, part_number: int,
                  payload: PartConfirmation, authorized, identity_recheck=None):
    locked = _lock_transfer(db, tenant_id, site_id, upload_id)
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, obj = locked
    now = server_now(request)
    if not authorized(session, upload, asset, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if identity_recheck:
        identity_recheck()
    if not _check_open(db, session, upload, asset, obj, now):
        db.commit()
        fail(409, "upload_not_completable", f"上传已终结：{upload.status}/{upload.failure_reason}")
    if not obj or obj.phase != "uploading" or not obj.provider_upload_id:
        db.rollback()
        fail(409, "state_conflict", "物理上传尚未准备完成")
    part = db.scalar(select(UploadPart).where(UploadPart.tenant_id == tenant_id,
                                            UploadPart.site_id == site_id,
                                            UploadPart.upload_session_id == upload_id,
                                            UploadPart.part_number == part_number))
    if not part:
        db.rollback()
        fail(409, "part_not_confirmed", "该分片尚未签发")
    if payload.size_bytes != part.expected_size_bytes:
        db.rollback()
        fail(409, "part_conflict", "分片字节数与声明布局不一致")
    if part.state == "confirmed":
        if part.actual_size_bytes == payload.size_bytes and _same_etag(part.etag, payload.etag):
            response = PartConfirmedRead(part_number=part.part_number, size_bytes=part.actual_size_bytes,
                                         etag=part.etag, confirmed_at=as_utc(part.confirmed_at))
            db.rollback()
            return response
        db.rollback()
        fail(409, "part_conflict", "该分片已经以其他回执确认")
    key, provider_upload_id, generation = obj.object_key, obj.provider_upload_id, obj.generation
    db.commit()
    try:
        remote = _all_provider_parts(provider, obj)
    except StorageError:
        fail(503, "storage_unavailable", "暂时无法核对对象存储分片")
    actual = remote.get(part_number)
    if not actual or not _same_etag(str(actual.get("ETag", "")), payload.etag) or int(actual.get("Size", 0)) != payload.size_bytes:
        fail(409, "part_conflict", "对象存储中的分片回执或大小不一致")
    locked = _lock_transfer(db, tenant_id, site_id, upload_id)
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, obj2 = locked
    now = server_now(request)
    if not authorized(session, upload, asset, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if identity_recheck:
        identity_recheck()
    if (upload.status != "uploading" or not obj2 or obj2.generation != generation
            or obj2.provider_upload_id != provider_upload_id):
        db.rollback()
        fail(409, "state_conflict", "核对期间上传状态或代际已变化")
    part = db.scalar(select(UploadPart).where(UploadPart.tenant_id == tenant_id,
                                            UploadPart.site_id == site_id,
                                            UploadPart.upload_session_id == upload_id,
                                            UploadPart.part_number == part_number))
    if not part:
        db.rollback()
        fail(409, "part_conflict", "分片布局已经变化")
    if part.state == "confirmed":
        if part.actual_size_bytes != payload.size_bytes or not _same_etag(part.etag, payload.etag):
            db.rollback()
            fail(409, "part_conflict", "并发确认已保存不同回执")
    else:
        part.state, part.etag, part.actual_size_bytes = "confirmed", payload.etag, payload.size_bytes
        part.confirmed_at, part.updated_at = now, now
    db.commit()
    return PartConfirmedRead(part_number=part.part_number, size_bytes=part.actual_size_bytes,
                             etag=part.etag, confirmed_at=as_utc(part.confirmed_at))


@router.put(P + "/upload-sessions/{upload_session_id}/parts/{part_number}")
def user_confirm_part(tenant_id: UUID, site_id: UUID, upload_session_id: UUID,
                      part_number: int, payload: PartConfirmation, request: Request,
                      user: Current, db: DB):
    provider = _provider(request)
    def authorized(session, upload, asset, now):
        _, member = site_access(db, tenant_id, site_id, user), membership(db, tenant_id, user.id)
        return _user_can_touch_upload(db, upload, session, user, member, now)
    return _confirm_part(db=db, request=request, provider=provider, tenant_id=str(tenant_id),
                         site_id=str(site_id), upload_id=str(upload_session_id),
                         part_number=part_number, payload=payload, authorized=authorized)


@router.put("/edge/upload-sessions/{upload_session_id}/parts/{part_number}")
def edge_confirm_part(upload_session_id: UUID, part_number: int, payload: PartConfirmation,
                      request: Request, db: DB,
                      authorization: Annotated[str | None, Header(alias="Authorization")] = None):
    provider = _provider(request)
    node, credential = get_edge_identity_unlocked(db, authorization, server_now(request))
    return _confirm_part(db=db, request=request, provider=provider, tenant_id=node.tenant_id,
                         site_id=node.site_id, upload_id=str(upload_session_id),
                         part_number=part_number, payload=payload,
                         authorized=lambda _s, u, _a, _n: u.initiator_edge_node_id == node.id,
                         identity_recheck=lambda: lock_edge_identity(db, node.id, credential.id,
                                                                     server_now(request)))


def _list_parts(*, db: Session, request: Request, provider: StorageProvider,
                tenant_id: str, site_id: str, upload_id: str, limit: int, cursor: str | None,
                authorized, identity_recheck=None):
    locked = _lock_transfer(db, tenant_id, site_id, upload_id)
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, obj = locked
    now = server_now(request)
    if not authorized(session, upload, asset, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if identity_recheck:
        identity_recheck()
    rows = db.scalars(select(UploadPart).where(UploadPart.tenant_id == tenant_id,
                                               UploadPart.site_id == site_id,
                                               UploadPart.upload_session_id == upload_id)
                      .order_by(UploadPart.part_number)).all()
    if upload.status in {"completed", "failed", "expired", "aborted"}:
        generation = obj.generation if obj else 1
        db.rollback()
        return _part_page(rows, generation, tenant_id=tenant_id, site_id=site_id,
                          upload_id=upload_id, limit=limit, cursor=cursor)
    if not obj or not obj.provider_upload_id or obj.phase != "uploading":
        db.rollback()
        return _part_page(rows, obj.generation if obj else 1, tenant_id=tenant_id,
                          site_id=site_id, upload_id=upload_id, limit=limit, cursor=cursor)
    generation, object_id, key, provider_id = obj.generation, obj.id, obj.object_key, obj.provider_upload_id
    db.commit()
    try:
        remote = _all_provider_parts(provider, obj)
    except StorageError as exc:
        fail(503, "storage_unavailable", f"分片列表暂不可用：{exc.code}")
    locked = _lock_transfer(db, tenant_id, site_id, upload_id)
    if not locked:
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    session, upload, asset, current_obj = locked
    now = server_now(request)
    if not authorized(session, upload, asset, now):
        fail(404, "upload_session_not_found", "上传会话不存在或无访问权限")
    if identity_recheck:
        identity_recheck()
    if (not current_obj or current_obj.id != object_id or current_obj.generation != generation
            or upload.status not in {"uploading", "completing"}):
        db.rollback()
        fail(409, "state_conflict", "分片核对期间上传状态或代际已变化")
    current_rows = db.scalars(select(UploadPart).where(UploadPart.tenant_id == tenant_id,
                                                         UploadPart.site_id == site_id,
                                                         UploadPart.upload_session_id == upload_id)
                              .order_by(UploadPart.part_number).with_for_update() if db.bind.dialect.name == "postgresql" else
                              select(UploadPart).where(UploadPart.tenant_id == tenant_id,
                                                       UploadPart.site_id == site_id,
                                                       UploadPart.upload_session_id == upload_id)
                              .order_by(UploadPart.part_number)).all()
    mismatch = False
    for part in current_rows:
        remote_part = remote.get(part.part_number)
        if part.state == "confirmed" and (
            not remote_part or int(remote_part.get("Size", 0)) != part.actual_size_bytes
            or not _same_etag(str(remote_part.get("ETag", "")), part.etag)
        ):
            part.state = "stale"
            part.updated_at = now
            mismatch = True
        elif part.state == "registered" and remote_part:
            if int(remote_part.get("Size", 0)) == part.expected_size_bytes:
                part.state, part.etag = "confirmed", str(remote_part.get("ETag"))
                part.actual_size_bytes, part.confirmed_at, part.updated_at = int(remote_part["Size"]), now, now
            else:
                mismatch = True
    db.commit()
    if mismatch:
        fail(409, "part_conflict", "对象存储分片与确认快照不一致；需恢复或重新开始上传")
    return _part_page(current_rows, generation, tenant_id=tenant_id, site_id=site_id,
                      upload_id=upload_id, limit=limit, cursor=cursor)


@router.get(P + "/upload-sessions/{upload_session_id}/parts")
def user_list_parts(tenant_id: UUID, site_id: UUID, upload_session_id: UUID,
                    request: Request, user: Current, db: DB,
                    limit: int = Query(default=100, ge=1, le=1000), cursor: str | None = None):
    provider = _provider(request)
    def authorized(session, upload, asset, now):
        _, member = site_access(db, tenant_id, site_id, user), membership(db, tenant_id, user.id)
        return _user_can_touch_upload(db, upload, session, user, member, now)
    return _list_parts(db=db, request=request, provider=provider, tenant_id=str(tenant_id),
                       site_id=str(site_id), upload_id=str(upload_session_id), limit=limit,
                       cursor=cursor, authorized=authorized)


@router.get("/edge/upload-sessions/{upload_session_id}/parts")
def edge_list_parts(upload_session_id: UUID, request: Request, db: DB,
                    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
                    limit: int = Query(default=100, ge=1, le=1000), cursor: str | None = None):
    provider = _provider(request)
    node, credential = get_edge_identity_unlocked(db, authorization, server_now(request))
    return _list_parts(db=db, request=request, provider=provider, tenant_id=node.tenant_id,
                       site_id=node.site_id, upload_id=str(upload_session_id), limit=limit,
                       cursor=cursor,
                       authorized=lambda _s, u, _a, _n: u.initiator_edge_node_id == node.id,
                       identity_recheck=lambda: lock_edge_identity(db, node.id, credential.id,
                                                                   server_now(request)))


@router.post(P + "/upload-sessions/{upload_session_id}/complete")
def user_complete(tenant_id: UUID, site_id: UUID, upload_session_id: UUID,
                  payload: CompleteRequest, request: Request,
                  idempotency_header: Annotated[str, Header(alias="Idempotency-Key")],
                  user: Current, db: DB):
    provider = _provider(request)
    accepted = _user_identity_snapshot(db, request, user)
    def authorized(session, upload, asset, now):
        _, member = site_access(db, tenant_id, site_id, user), membership(db, tenant_id, user.id)
        return _user_can_touch_upload(db, upload, session, user, member, now)
    return _complete(db=db, request=request, provider=provider, tenant_id=str(tenant_id),
                     site_id=str(site_id), upload_id=str(upload_session_id), payload=payload,
                     key_header=idempotency_header, actor_kind="user", actor_id=user.id,
                     accepted=accepted, authorized=authorized)


@router.post("/edge/upload-sessions/{upload_session_id}/complete")
def edge_complete(upload_session_id: UUID, payload: CompleteRequest, request: Request, db: DB,
                  idempotency_header: Annotated[str, Header(alias="Idempotency-Key")],
                  authorization: Annotated[str | None, Header(alias="Authorization")] = None):
    provider = _provider(request)
    node, credential = get_edge_identity_unlocked(db, authorization, server_now(request))
    return _complete(db=db, request=request, provider=provider, tenant_id=node.tenant_id,
                     site_id=node.site_id, upload_id=str(upload_session_id), payload=payload,
                     key_header=idempotency_header, actor_kind="edge_node", actor_id=node.id,
                     accepted=_edge_identity_snapshot(node, credential),
                     authorized=lambda _s, u, _a, _n: u.initiator_edge_node_id == node.id,
                     identity_recheck=lambda: lock_edge_identity(db, node.id, credential.id,
                                                                 server_now(request)))


def _issue_access_url(*, tenant_id, site_id, asset_id, request, user, db, disposition):
    provider = _provider(request)
    site_access(db, tenant_id, site_id, user)
    member = membership(db, tenant_id, user.id)
    asset = db.scalar(select(VideoAsset).where(VideoAsset.id == str(asset_id),
                                              VideoAsset.tenant_id == str(tenant_id),
                                              VideoAsset.site_id == str(site_id)))
    if not asset:
        fail(404, "video_asset_not_found", "视频资产不存在或无访问权限")
    session = db.scalar(select(TrainingSession).where(TrainingSession.id == asset.session_id,
                                                      TrainingSession.tenant_id == asset.tenant_id,
                                                      TrainingSession.site_id == asset.site_id))
    now = server_now(request)
    if not can_read_asset(db, asset, session, user, member, now):
        fail(404, "video_asset_not_found", "视频资产不存在或无访问权限")
    if asset.status != "ready" or not asset.storage_object_ref:
        fail(409, "asset_not_ready", "视频资产尚未完成验证")
    obj = db.scalar(select(MediaObject).where(MediaObject.id == asset.storage_object_ref,
                                              MediaObject.tenant_id == asset.tenant_id,
                                              MediaObject.site_id == asset.site_id,
                                              MediaObject.session_id == asset.session_id,
                                              MediaObject.asset_id == asset.id,
                                              MediaObject.phase == "verified"))
    if not obj or not obj.object_version:
        fail(503, "media_unavailable", "已验证媒体对象暂不可用")
    auth = db.get(AuthSession, getattr(request.state, "session_hash", None))
    if not auth or auth.user_id != user.id or as_utc(auth.expires_at) <= now:
        fail(401, "unauthorized", "登录已失效")
    identity_remaining = int((as_utc(auth.expires_at) - now).total_seconds())
    if identity_remaining < 1:
        fail(401, "unauthorized", "登录即将失效，无法签发媒体访问 URL")
    deadlines = [as_utc(auth.expires_at)]
    if member.role not in {"owner", "admin"} and asset.created_by_user_id != user.id:
        if session.created_by_user_id == user.id:
            pass
        else:
            asset_grant = db.scalars(select(AssetReadGrant).where(
                AssetReadGrant.tenant_id == asset.tenant_id,
                AssetReadGrant.site_id == asset.site_id,
                AssetReadGrant.asset_id == asset.id,
                AssetReadGrant.grantee_user_id == user.id,
                AssetReadGrant.revoked_at.is_(None),
                (AssetReadGrant.expires_at.is_(None) | (AssetReadGrant.expires_at > now)),
            )).all()
            session_grant = db.scalars(select(SessionReadGrant).where(
                SessionReadGrant.tenant_id == session.tenant_id,
                SessionReadGrant.site_id == session.site_id,
                SessionReadGrant.session_id == session.id,
                SessionReadGrant.grantee_user_id == user.id,
                SessionReadGrant.revoked_at.is_(None),
                (SessionReadGrant.expires_at.is_(None) | (SessionReadGrant.expires_at > now)),
            )).all()
            grants = [*asset_grant, *session_grant]
            if grants:
                # Access is an OR over grants. An unbounded grant or the longest
                # valid grant is the authorization path that remains active longest.
                if any(grant.expires_at is None for grant in grants):
                    deadlines = []
                else:
                    deadlines.append(max(as_utc(grant.expires_at) for grant in grants))
    remaining = min((deadline - now).total_seconds() for deadline in deadlines) if deadlines else None
    if remaining is not None and int(remaining) < 1:
        fail(404, "video_asset_not_found", "资源授权即将失效，无法签发媒体访问 URL")
    ttl_candidates = [request.app.state.settings.media_read_url_seconds,
                      request.app.state.settings.media_read_url_max_seconds, 300]
    if remaining is not None:
        ttl_candidates.append(int(remaining))
    ttl = min(ttl_candidates)
    safe_name = f"video-{asset.id}.mp4"
    content = None
    if disposition == "attachment":
        content = f"attachment; filename*=UTF-8''{quote(safe_name, safe='')}"
    else:
        content = f"inline; filename*=UTF-8''{quote(safe_name, safe='')}"
    try:
        url = provider.sign_read(obj.object_key, obj.object_version, ttl, disposition=content)
    except StorageError:
        fail(503, "storage_unavailable", "无法签发媒体访问 URL")
    response = AccessUrlRead(asset_id=asset.id, url=url, expires_at=now + timedelta(seconds=ttl))
    return JSONResponse(status_code=200, content=response.model_dump(mode="json"),
                        headers={"Cache-Control": "private, no-store",
                                 "Referrer-Policy": "no-referrer"})


@router.post(P + "/video-assets/{asset_id}/playback-url")
def playback_url(tenant_id: UUID, site_id: UUID, asset_id: UUID,
                 request: Request, user: Current, db: DB):
    return _issue_access_url(tenant_id=tenant_id, site_id=site_id, asset_id=asset_id,
                             request=request, user=user, db=db, disposition="inline")


@router.post(P + "/video-assets/{asset_id}/download-url")
def download_url(tenant_id: UUID, site_id: UUID, asset_id: UUID,
                 request: Request, user: Current, db: DB):
    return _issue_access_url(tenant_id=tenant_id, site_id=site_id, asset_id=asset_id,
                             request=request, user=user, db=db, disposition="attachment")


def _claim_job(session_factory, now: datetime):
    token = uid()
    with session_factory() as db:
        query = select(MediaJob).where(
            ((MediaJob.state.in_(("queued", "retry_wait"))) & (MediaJob.next_attempt_at <= now))
            | ((MediaJob.state == "running") & (MediaJob.lease_until <= now)),
        ).order_by(MediaJob.next_attempt_at, MediaJob.created_at, MediaJob.id)
        if db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query.limit(1))
        if not job:
            return None
        job.state, job.lease_token = "running", token
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        job.generation += 1
        job.attempts += 1
        job.updated_at = now
        obj = db.get(MediaObject, job.object_id)
        result = {"id": job.id, "kind": job.kind, "object_id": job.object_id,
                  "upload_id": obj.upload_session_id if obj else None,
                  "generation": job.generation, "token": token,
                  "tenant_id": job.tenant_id, "site_id": job.site_id,
                  "session_id": job.session_id, "asset_id": job.asset_id,
                  "accepted_actor_kind": job.accepted_actor_kind,
                  "accepted_user_id": job.accepted_user_id,
                  "accepted_auth_session_hash": job.accepted_auth_session_hash,
                  "accepted_edge_node_id": job.accepted_edge_node_id,
                  "accepted_credential_id": job.accepted_credential_id,
                  "attempts": job.attempts}
        db.commit()
        return result


def _job_current(db: Session, snapshot: dict):
    query = select(MediaJob).where(MediaJob.id == snapshot["id"])
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    job = db.scalar(query.execution_options(populate_existing=True))
    return bool(job and job.state == "running" and job.lease_token == snapshot["token"]
                and job.generation == snapshot["generation"]
                and as_utc(job.lease_until) > datetime.now(UTC))


def _renew_job_lease(session_factory, snapshot: dict, now: datetime) -> bool:
    with session_factory() as db:
        result = db.execute(update(MediaJob).where(
            MediaJob.id == snapshot["id"], MediaJob.state == "running",
            MediaJob.lease_token == snapshot["token"],
            MediaJob.generation == snapshot["generation"],
        ).values(lease_until=now + timedelta(seconds=LEASE_SECONDS), updated_at=now))
        db.commit()
        return result.rowcount == 1


def _probe_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _job_retry_or_fail(session_factory, snapshot: dict, *, code: str, now: datetime):
    with session_factory() as db:
        job = db.get(MediaJob, snapshot["id"])
        if not job or job.state != "running" or job.lease_token != snapshot["token"]:
            return
        exhausted = job.attempts >= MAX_JOB_ATTEMPTS
        if exhausted:
            db.rollback()
            _exhausted_job_failure(session_factory, snapshot, code=code, now=now)
            return
        job.last_error_code = code[:64]
        job.state, job.lease_token, job.lease_until = "retry_wait", None, None
        job.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(job.attempts, 8)))
        job.updated_at = now
        db.commit()


def _exhausted_job_failure(session_factory, snapshot: dict, *, code: str, now: datetime):
    """After bounded retry exhaustion, atomically fail the business pair and job."""
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            return
        _session, upload, asset, obj = locked
        job = db.scalar(select(MediaJob).where(MediaJob.id == snapshot["id"]).execution_options(populate_existing=True))
        if not job or not _job_current(db, snapshot):
            db.rollback()
            return
        if upload.status in {"uploading", "completing"}:
            _terminalize_locked(db, upload, asset, obj, "upload_failed", now)
        job.state, job.last_error_code = "failed", code[:64]
        job.lease_token, job.lease_until, job.updated_at = None, None, now
        db.commit()


def process_media_job(session_factory, provider: StorageProvider, settings, *, now: datetime | None = None) -> bool:
    """Claim and process one durable initialize/complete job; suitable for a supervisor loop."""
    now = now or datetime.now(UTC)
    snapshot = _claim_job(session_factory, now)
    if not snapshot:
        return False
    try:
        if snapshot["kind"] == "initialize":
            _process_initialize(session_factory, provider, snapshot, now)
        elif snapshot["kind"] == "complete":
            _process_complete(session_factory, provider, settings, snapshot, now)
        else:
            raise StorageError("unsupported_job")
    except (StorageError, OSError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, StorageError) else "media_io_error"
        _job_retry_or_fail(session_factory, snapshot, code=code, now=datetime.now(UTC))
    return True


def _process_initialize(session_factory, provider: StorageProvider, snapshot: dict, now: datetime):
    provider.check_capabilities()
    with session_factory() as db:
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], _job_upload_id(db, snapshot))
        if not locked:
            return
        session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        if not job or not _job_current(db, snapshot):
            db.rollback()
            return
        if upload.status != "uploading" or session.status == "cancelled" or as_utc(upload.expires_at) <= now:
            reason = "session_cancelled" if session.status == "cancelled" else "upload_expired"
            _terminalize_locked(db, upload, asset, obj, reason, now)
            job.state, job.lease_token, job.lease_until = "succeeded", None, None
            db.commit()
            return
        key = obj.object_key
        generation = obj.generation
        existing_id = obj.provider_upload_id
        if existing_id:
            job.state, job.lease_token, job.lease_until = "succeeded", None, None
            obj.phase, obj.updated_at = "uploading", now
            db.commit()
            return
        obj.phase = "preparing"
        obj.updated_at = now
        db.commit()
    metadata = {"tenant-id": snapshot["tenant_id"], "site-id": snapshot["site_id"],
                "session-id": snapshot["session_id"], "asset-id": snapshot["asset_id"],
                "upload-session-id": _job_upload_id_from_snapshot(snapshot),
                "owner": "swim-platform", "purpose": "isolated-media-transfer"}
    run_id = getattr(settings, "media_run_id", None)
    if run_id:
        metadata["run-id"] = run_id
    provider_ids = _find_multipart_uploads(provider, key)
    provider_id = provider_ids[0] if provider_ids else provider.create_multipart(key, metadata)
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            db.rollback()
            return
        session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        if not job or not _job_current(db, snapshot) or obj.generation != generation:
            _enqueue_cleanup(db=db, obj=obj, kind="multipart", upload_id=provider_id, now=datetime.now(UTC))
            db.commit()
            return
        if upload.status != "uploading" or session.status == "cancelled":
            obj.phase = "delete_pending"
            _enqueue_cleanup(db=db, obj=obj, kind="multipart", upload_id=provider_id, now=datetime.now(UTC))
            job.state, job.lease_token, job.lease_until = "succeeded", None, None
            db.commit()
            return
        obj.provider_upload_id, obj.phase, obj.updated_at = provider_id, "uploading", datetime.now(UTC)
        for extra_id in provider_ids[1:]:
            _enqueue_cleanup(db=db, obj=obj, kind="multipart", upload_id=extra_id, now=datetime.now(UTC))
        job.state, job.lease_token, job.lease_until = "succeeded", None, None
        job.updated_at = datetime.now(UTC)
        db.commit()


def _job_upload_id(db: Session, snapshot: dict) -> str:
    obj = db.get(MediaObject, snapshot["object_id"])
    return obj.upload_session_id if obj else ""


def _job_upload_id_from_snapshot(snapshot: dict) -> str:
    return snapshot.get("upload_id") or snapshot["object_id"]


def _process_complete(session_factory, provider: StorageProvider, settings, snapshot: dict, now: datetime):
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            return
        session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        if not job or not _job_current(db, snapshot):
            db.rollback()
            return
        if upload.status != "completing" or not obj or obj.phase in {"delete_pending", "deleted"}:
            db.rollback()
            return
        now = datetime.now(UTC)
        if session.status == "cancelled" or as_utc(upload.expires_at) <= now:
            reason = "session_cancelled" if session.status == "cancelled" else "upload_expired"
            _terminalize_locked(db, upload, asset, obj, reason, now)
            job.state, job.lease_token, job.lease_until = "succeeded", None, None
            job.last_error_code = reason
            db.commit()
            return
        rows = db.scalars(select(UploadPart).where(UploadPart.tenant_id == upload.tenant_id,
                                                   UploadPart.site_id == upload.site_id,
                                                   UploadPart.upload_session_id == upload.id)
                          .order_by(UploadPart.part_number)).all()
        manifest = [{"part_number": p.part_number, "etag": p.etag,
                     "expected_size_bytes": p.expected_size_bytes}
                    for p in rows if p.state == "confirmed"]
        if len(manifest) != upload.part_count or _manifest_digest(manifest) != upload.complete_manifest_hash:
            db.rollback()
            raise StorageError("manifest_changed")
        object_snapshot = {"id": obj.id, "key": obj.object_key, "upload_id": obj.provider_upload_id,
                           "version": obj.object_version, "generation": obj.generation}
        expected_size, expected_sha256 = upload.expected_size_bytes, upload.expected_sha256
        declared_media_type = upload.media_type
        db.commit()

    expected_metadata = {
        "owner": "swim-platform", "purpose": "isolated-media-transfer",
        "tenant-id": snapshot["tenant_id"], "site-id": snapshot["site_id"],
        "session-id": snapshot["session_id"], "asset-id": snapshot["asset_id"],
        "upload-session-id": _job_upload_id_from_snapshot(snapshot),
    }
    if getattr(settings, "media_run_id", None):
        expected_metadata["run-id"] = settings.media_run_id

    # A worker may die after CompleteMultipartUpload commits remotely but before
    # recording the returned version locally. First resume a previously recorded
    # immutable version; otherwise discover and bind a completed object before
    # touching the now-consumed multipart upload. This also makes later validation
    # failures clean up the exact object version instead of mistaking an absent MPU
    # for proof that no physical object exists.
    version_id = object_snapshot["version"]
    head = None
    if version_id:
        head = provider.head_object(object_snapshot["key"], version_id)
    else:
        try:
            latest = provider.head_object(object_snapshot["key"])
        except StorageError as exc:
            if exc.code != "not_found":
                raise
            latest = None
        if latest and latest.get("version_id"):
            version_id = latest["version_id"]

    if not version_id:
        remote_parts = _all_provider_parts(provider, _object_snapshot(object_snapshot, snapshot))
        for part in manifest:
            provider_part = remote_parts.get(part["part_number"])
            if (
                not provider_part
                or not _same_etag(str(provider_part.get("ETag", "")), part["etag"])
                or int(provider_part.get("Size", 0)) != part["expected_size_bytes"]
            ):
                raise StorageError("part_manifest_changed")
        try:
            completion = provider.complete_multipart(
                object_snapshot["key"], object_snapshot["upload_id"], manifest
            )
            version_id = completion.get("version_id")
        except StorageError as exc:
            if exc.code != "not_found":
                raise
        if not version_id:
            try:
                latest = provider.head_object(object_snapshot["key"])
            except StorageError as exc:
                if exc.code != "not_found":
                    raise
                raise StorageError("complete_result_ambiguous") from exc
            version_id = latest.get("version_id")
        if not version_id:
            raise StorageError("version_id_missing")
    if head is None:
        head = provider.head_object(object_snapshot["key"], version_id)
    object_snapshot["version"] = version_id
    if not _record_assembled(session_factory, snapshot, object_snapshot, version_id, head, now):
        return

    returned_metadata = {str(k).lower(): str(v) for k, v in (head.get("metadata") or {}).items()}
    if (head.get("version_id") != version_id
            or any(returned_metadata.get(key) != value for key, value in expected_metadata.items())):
        _terminal_job_failure(session_factory, snapshot, "upload_failed", "object_identity_mismatch", now)
        return
    if head.get("size") != expected_size:
        _terminal_job_failure(session_factory, snapshot, "validation_failed", "size_mismatch", now)
        return
    digest, size = hashlib.sha256(), 0
    with tempfile.TemporaryDirectory(prefix="swim-media-verify-") as temp_dir:
        if shutil.disk_usage(temp_dir).free < expected_size + 32 * 1024 * 1024:
            raise StorageError("verifier_disk_budget_exceeded")
        path = Path(temp_dir) / "media.bin"
        total_deadline = time.monotonic() + 600
        next_renewal = time.monotonic() + LEASE_RENEW_SECONDS
        with provider.open_object(object_snapshot["key"], version_id) as stream, path.open("xb") as output:
            os.chmod(path, 0o600)
            while True:
                if time.monotonic() >= total_deadline:
                    raise StorageError("verifier_total_budget_exceeded")
                if time.monotonic() >= next_renewal:
                    if not _renew_job_lease(session_factory, snapshot, datetime.now(UTC)):
                        raise StorageError("worker_lease_lost")
                    next_renewal = time.monotonic() + LEASE_RENEW_SECONDS
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > min(expected_size, MAX_NEW_INTENT_BYTES):
                    raise StorageError("object_too_large")
                digest.update(chunk)
                output.write(chunk)
        output_hash = digest.hexdigest()
        if size != expected_size:
            _terminal_job_failure(session_factory, snapshot, "validation_failed", "size_mismatch", now)
            return
        if output_hash != expected_sha256:
            _terminal_job_failure(session_factory, snapshot, "validation_failed", "hash_mismatch", now)
            return
        probe_version = subprocess.run(
            [settings.media_ffprobe_path, "-version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=2,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "HOME": temp_dir},
        )
        version_line = probe_version.stdout.decode("ascii", errors="ignore").splitlines()
        if probe_version.returncode != 0 or not version_line or not version_line[0].startswith("ffprobe version 6.1.1"):
            raise StorageError("ffprobe_version_mismatch")
        probe = subprocess.run(
            [settings.media_ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe",
             "-max_alloc", str(64 * 1024 * 1024), "-probesize", str(5 * 1024 * 1024),
             "-analyzeduration", str(5 * 1000 * 1000),
             "-show_entries", "format=format_name", "-of", "json", str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=10, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                         "LC_ALL": "C", "HOME": temp_dir},
            preexec_fn=_probe_limits,
        )
        if probe.returncode != 0 or len(probe.stdout) > 4096:
            _terminal_job_failure(session_factory, snapshot, "validation_failed", "media_probe_failed", now)
            return
        try:
            format_name = json.loads(probe.stdout).get("format", {}).get("format_name", "")
        except (ValueError, AttributeError):
            format_name = ""
        if "mp4" not in format_name.split(","):
            _terminal_job_failure(session_factory, snapshot, "validation_failed", "media_type_mismatch", now)
            return
    declared = (declared_media_type or "").lower()
    if declared not in {"", "application/octet-stream", "video/mp4"}:
        _terminal_job_failure(session_factory, snapshot, "validation_failed", "media_type_mismatch", now)
        return
    _finalize_ready(session_factory, provider, snapshot, object_snapshot, version_id,
                    size=size, sha256=output_hash, media_type="video/mp4", now=now)


def _object_snapshot(values: dict, snapshot: dict) -> MediaObject:
    return MediaObject(id=values["id"], tenant_id=snapshot["tenant_id"], site_id=snapshot["site_id"],
                       session_id=snapshot["session_id"], asset_id=snapshot["asset_id"],
                       upload_session_id=_job_upload_id_from_snapshot(snapshot),
                       provider_profile="s3", bucket="", object_key=values["key"],
                       provider_upload_id=values["upload_id"], generation=values["generation"], phase="assembled")


def _record_assembled(session_factory, snapshot: dict, object_snapshot: dict,
                      version_id: str, head: dict, now: datetime) -> bool:
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            return False
        session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        if not job or obj.generation != object_snapshot["generation"]:
            db.rollback()
            return False
        if (upload.status != "completing" or session.status == "cancelled"
                or asset.status != "pending_upload"):
            # The provider may finish CompleteMultipartUpload after Abort/Cancel won
            # the database race. Bind the exact immutable version to a cleanup
            # tombstone so an MPU-not-found response cannot hide a leaked object.
            if asset.status == "ready" and asset.storage_object_ref == obj.id:
                db.rollback()
                return False
            obj.object_version = version_id
            obj.phase, obj.assembled_at, obj.updated_at = "delete_pending", now, now
            obj.observed_size_bytes = head.get("size")
            _enqueue_cleanup(db=db, obj=obj, kind="object", upload_id=None, now=now)
            job.state, job.lease_token, job.lease_until = "succeeded", None, None
            job.last_error_code = upload.failure_reason or "session_cancelled"
            job.updated_at = now
            db.commit()
            return False
        if not _job_current(db, snapshot):
            db.rollback()
            return False
        obj.object_version = version_id
        obj.phase, obj.assembled_at, obj.updated_at = "assembled", now, now
        obj.observed_size_bytes = head.get("size")
        db.commit()
        return True


def _accepted_identity_valid(db: Session, upload: UploadSession, asset: VideoAsset,
                             job: MediaJob, now: datetime) -> bool:
    if job.accepted_actor_kind == "user":
        user_query = select(User).where(User.id == job.accepted_user_id)
        auth_query = select(AuthSession).where(AuthSession.token_hash == job.accepted_auth_session_hash)
        member_query = select(TenantMembership).where(
            TenantMembership.tenant_id == upload.tenant_id,
            TenantMembership.user_id == job.accepted_user_id,
        )
        site_query = select(SiteMembership).where(
            SiteMembership.tenant_id == upload.tenant_id,
            SiteMembership.site_id == upload.site_id,
            SiteMembership.user_id == job.accepted_user_id,
        )
        if db.bind.dialect.name == "postgresql":
            user_query = user_query.with_for_update()
            auth_query, member_query, site_query = (
                auth_query.with_for_update(), member_query.with_for_update(), site_query.with_for_update()
            )
        user = db.scalar(user_query)
        auth, member, site_member = db.scalar(auth_query), db.scalar(member_query), db.scalar(site_query)
        session = db.get(TrainingSession, upload.session_id)
        if (not user or not user.is_active or not auth or auth.user_id != job.accepted_user_id
                or as_utc(auth.expires_at) <= now or not member):
            return False
        if member.role not in {"owner", "admin"} and not site_member:
            return False
        if member.role in {"owner", "admin"}:
            return True
        return member.role == "coach" and session and session.created_by_user_id == job.accepted_user_id
    if job.accepted_actor_kind == "edge_node":
        node_query = select(EdgeNode).where(EdgeNode.id == job.accepted_edge_node_id)
        credential_query = select(EdgeCredential).where(EdgeCredential.id == job.accepted_credential_id)
        device_query = select(Device).where(Device.id == asset.source_device_id) if asset.source_device_id else None
        if db.bind.dialect.name == "postgresql":
            node_query, credential_query = node_query.with_for_update(), credential_query.with_for_update()
            if device_query is not None:
                device_query = device_query.with_for_update()
        node, credential = db.scalar(node_query), db.scalar(credential_query)
        device = db.scalar(device_query) if device_query is not None else None
        return bool(node and node.status == "active" and credential and credential.edge_node_id == node.id
                    and credential.revoked_at is None and credential.generation == node.credential_generation
                    and as_utc(credential.expires_at) > now and device and device.status == "active"
                    and device.edge_node_id == node.id)
    return False


def _finalize_ready(session_factory, provider: StorageProvider, snapshot: dict,
                    object_snapshot: dict, version_id: str, *, size: int, sha256: str,
                    media_type: str, now: datetime):
    # The external exact-version HEAD happens before taking SQL locks; immutable provider versions
    # make the subsequent short transaction bind the bytes just checked without holding locks over I/O.
    head = provider.head_object(object_snapshot["key"], version_id)
    if head.get("version_id") != version_id or head.get("size") != size:
        _terminal_job_failure(session_factory, snapshot, "validation_failed", "object_changed", now)
        return
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            return
        session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        now = datetime.now(UTC)
        if not job or not _job_current(db, snapshot) or not obj or obj.generation != object_snapshot["generation"]:
            db.rollback()
            return
        if upload.status != "completing" or session.status == "cancelled" or as_utc(upload.expires_at) <= now:
            if upload.status == "completing" and (session.status == "cancelled" or as_utc(upload.expires_at) <= now):
                reason = "session_cancelled" if session.status == "cancelled" else "upload_expired"
                _terminalize_locked(db, upload, asset, obj, reason, now)
                job.state, job.lease_token, job.lease_until = "succeeded", None, None
                job.last_error_code = reason
            db.commit()
            return
        if not _accepted_identity_valid(db, upload, asset, job, now):
            _terminalize_locked(db, upload, asset, obj, "upload_failed", now)
            job.state, job.last_error_code, job.lease_token, job.lease_until = "succeeded", "authorization_lost", None, None
            db.commit()
            return
        if obj.object_version != version_id or obj.phase not in {"assembled", "verified"}:
            db.rollback()
            return
        obj.phase, obj.observed_size_bytes, obj.observed_sha256 = "verified", size, sha256
        obj.observed_media_type, obj.verified_at, obj.updated_at = media_type, now, now
        upload.status, upload.completed_at, upload.updated_at = "completed", now, now
        asset.status, asset.failure_reason = "ready", None
        asset.storage_object_ref = obj.id
        asset.size_bytes, asset.checksum_sha256 = size, sha256
        asset.media_type, asset.verified_size_bytes = media_type, size
        received_at = as_utc(obj.assembled_at) or now
        asset.verified_media_type, asset.verified_at, asset.received_at = media_type, now, received_at
        asset.updated_at = now
        job.state, job.lease_token, job.lease_until = "succeeded", None, None
        job.updated_at = now
        db.commit()


def _terminal_job_failure(session_factory, snapshot: dict, failure_reason: str,
                          code: str, now: datetime):
    with session_factory() as db:
        upload_id = _job_upload_id(db, snapshot)
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"], upload_id)
        if not locked:
            return
        _session, upload, asset, obj = locked
        job = db.get(MediaJob, snapshot["id"])
        if not job or not _job_current(db, snapshot):
            db.rollback()
            return
        if upload.status != "completing":
            db.rollback()
            return
        _terminalize_locked(db, upload, asset, obj, failure_reason, now)
        job.state, job.last_error_code, job.lease_token, job.lease_until = "succeeded", code, None, None
        job.updated_at = now
        db.commit()


def run_worker(session_factory, provider: StorageProvider, settings, *, once: bool = False,
               poll_seconds: float = 1.0):
    """Run a supervised durable worker loop; --once mode is used by tests and operators."""
    import time
    processed = 0
    while True:
        did_work = process_media_job(session_factory, provider, settings)
        processed += int(did_work)
        if once or not did_work:
            if once:
                return processed
            time.sleep(poll_seconds)


def sweep_expired(session_factory, *, now: datetime | None = None, limit: int = 100) -> int:
    """Materialize expired transfer states without requiring a client GET."""
    now = now or datetime.now(UTC)
    with session_factory() as db:
        ids = db.scalars(select(UploadSession.id).where(
            UploadSession.status.in_(("uploading", "completing")),
            UploadSession.expires_at <= now,
        ).order_by(UploadSession.expires_at, UploadSession.id).limit(max(1, min(limit, 1000)))).all()
    count = 0
    for upload_id in ids:
        with session_factory() as db:
            candidate = db.get(UploadSession, upload_id)
            if not candidate:
                continue
            locked = _lock_transfer(db, candidate.tenant_id, candidate.site_id, upload_id)
            if not locked:
                db.rollback()
                continue
            session, upload, asset, _obj = locked
            if upload.status in {"uploading", "completing"} and as_utc(upload.expires_at) <= now:
                _terminalize_locked(db, upload, asset, _obj, "upload_expired", now)
                db.commit()
                count += 1
            else:
                db.rollback()
    return count


def _orphan_key_scope(key: str, run_id: str) -> dict | None:
    parts = key.split("/")
    if len(parts) != 9 or parts[:3] != ["private", "test", run_id] or not parts[8].startswith("g"):
        return None
    try:
        tenant_id, site_id, session_id, asset_id, upload_id = (str(UUID(value)) for value in parts[3:8])
        generation = int(parts[8][1:])
    except (ValueError, TypeError):
        return None
    if generation < 1:
        return None
    return {"tenant_id": tenant_id, "site_id": site_id, "session_id": session_id,
            "asset_id": asset_id, "upload_id": upload_id, "generation": generation}


def discover_orphans(session_factory, provider: StorageProvider, settings, *,
                     now: datetime | None = None, limit: int = 100) -> dict:
    """Observe versioned, namespaced objects with no matching logical/storage row.

    First observation only creates a dry-run candidate. A later observation after the
    grace window queues it; the deletion path revalidates exact metadata and DB state.
    """
    now = now or datetime.now(UTC)
    if (settings.media_environment != "isolated-test" or settings.media_profile != "rustfs-isolated"
            or not settings.media_run_id):
        return {"scanned_versions": 0, "observed": 0, "queued": 0, "manual": 0}
    prefix = f"private/test/{settings.media_run_id}/"
    key_marker = version_marker = None
    scanned = observed = queued = manual = 0
    for _ in range(1000):
        page = provider.list_object_versions(prefix, key_marker, version_marker,
                                             max_keys=max(1, min(limit, 1000)))
        versions = page["versions"]
        scanned += len(versions)
        for entry in versions:
            if entry.get("IsDeleteMarker") or not entry.get("VersionId"):
                continue
            key, version_id = str(entry.get("Key", "")), str(entry["VersionId"])
            scope = _orphan_key_scope(key, settings.media_run_id)
            if not scope:
                continue
            try:
                head = provider.head_object(key, version_id)
            except StorageError as exc:
                if exc.code == "not_found":
                    continue
                raise
            metadata = {str(k).lower(): str(v) for k, v in (head.get("metadata") or {}).items()}
            expected = {"owner": "swim-platform", "purpose": "isolated-media-transfer",
                        "run-id": settings.media_run_id, "tenant-id": scope["tenant_id"],
                        "site-id": scope["site_id"], "session-id": scope["session_id"],
                        "asset-id": scope["asset_id"], "upload-session-id": scope["upload_id"]}
            metadata_valid = all(metadata.get(key_name) == value for key_name, value in expected.items())
            with session_factory() as db:
                site = db.get(Site, scope["site_id"])
                if not site or site.tenant_id != scope["tenant_id"]:
                    manual += 1
                    continue
                upload = db.get(UploadSession, scope["upload_id"])
                asset = db.get(VideoAsset, scope["asset_id"])
                session = db.get(TrainingSession, scope["session_id"])
                known_object = db.scalar(select(MediaObject.id).where(MediaObject.object_key == key))
                safe_scope = bool(
                    upload and asset and session and not known_object
                    and upload.tenant_id == scope["tenant_id"] and upload.site_id == scope["site_id"]
                    and upload.session_id == scope["session_id"] and upload.asset_id == scope["asset_id"]
                    and asset.tenant_id == scope["tenant_id"] and asset.site_id == scope["site_id"]
                    and asset.session_id == scope["session_id"] and asset.status == "failed"
                    and asset.storage_object_ref is None
                    and upload.status in {"failed", "expired", "aborted"}
                )
                if (known_object or (asset and asset.status == "ready")
                        or (upload and upload.status in {"uploading", "completing"})):
                    continue
                scope_valid = bool(
                    session and session.tenant_id == scope["tenant_id"]
                    and session.site_id == scope["site_id"]
                )
                identity = f"s3\0{settings.media_bucket}\0{key}\0\0{version_id}"
                identity_hash = hashlib.sha256(identity.encode()).hexdigest()
                candidate = db.scalar(select(MediaCleanupCandidate).where(
                    MediaCleanupCandidate.identity_hash == identity_hash
                ))
                if not candidate:
                    state = "observed" if metadata_valid and scope_valid and safe_scope else "manual"
                    code = None if state == "observed" else (
                        "unverified_metadata" if not metadata_valid else "retained_or_unknown_reference"
                    )
                    candidate = MediaCleanupCandidate(
                        tenant_id=scope["tenant_id"], site_id=scope["site_id"], object_id=None,
                        session_id=None, asset_id=None, provider_profile=settings.media_profile,
                        bucket=settings.media_bucket, object_key=key, object_version=version_id, kind="object",
                        identity_hash=identity_hash, first_seen_at=now, last_seen_at=now,
                        not_before=now + ORPHAN_OBSERVATION_GRACE, state=state, next_attempt_at=now,
                        generation=scope["generation"], last_error_code=code,
                        created_at=now, updated_at=now,
                    )
                    db.add(candidate)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                    if state == "observed":
                        observed += 1
                    else:
                        manual += 1
                    continue
                if candidate.state == "observed":
                    candidate.last_seen_at = now
                    candidate.updated_at = now
                    if (metadata_valid and scope_valid and safe_scope
                            and as_utc(candidate.first_seen_at) + ORPHAN_OBSERVATION_GRACE <= now):
                        candidate.state, candidate.next_attempt_at = "queued", now
                        queued += 1
                    else:
                        observed += 1
                    db.commit()
        if not page["truncated"]:
            return {"scanned_versions": scanned, "observed": observed,
                    "queued": queued, "manual": manual}
        next_markers = (page["key_marker"], page["version_marker"])
        if next_markers == (key_marker, version_marker) or next_markers == (None, None):
            raise StorageError("orphan_version_pagination_invalid")
        key_marker, version_marker = next_markers
    raise StorageError("orphan_version_pagination_limit")


def cleanup_candidates(session_factory, provider: StorageProvider, settings, *, execute: bool = False,
                       limit: int = 100, now: datetime | None = None) -> dict:
    """Inspect cleanup queue; physical deletion defaults to dry-run and is isolated-test gated."""
    now = now or datetime.now(UTC)
    limit = max(1, min(limit, 1000))
    discovery = discover_orphans(session_factory, provider, settings, now=now, limit=limit)
    with session_factory() as db:
        candidates = db.scalars(select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.state.in_(("observed", "queued", "retry_wait")),
            MediaCleanupCandidate.next_attempt_at <= now,
        ).order_by(MediaCleanupCandidate.not_before, MediaCleanupCandidate.id).limit(limit)).all()
        candidate_ids = [candidate.id for candidate in candidates]
        summary = [{"id": c.id, "kind": c.kind, "state": c.state,
                    "bucket": c.bucket, "key": c.object_key, "version_id": c.object_version,
                    "not_before": as_utc(c.not_before).isoformat()}
                   for c in candidates]
    if not execute:
        return {"dry_run": True, "discovery": discovery,
                "candidates": summary, "removed": 0, "failed": 0}
    if (
        settings.media_environment != "isolated-test"
        or settings.media_profile != "rustfs-isolated"
        or not settings.media_run_id
        or os.getenv("SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE", "false").lower() != "true"
    ):
        return {"dry_run": False, "candidates": summary, "removed": 0,
                "discovery": discovery, "failed": len(summary),
                "error": "destructive cleanup is not authorized for this isolated profile"}
    removed = failed = 0
    for candidate_id in candidate_ids:
        try:
            snapshot = _claim_cleanup_candidate(session_factory, candidate_id, now)
            if not snapshot:
                continue
            if snapshot["profile"] != settings.media_profile or snapshot["bucket"] != settings.media_bucket:
                raise StorageError("cleanup_scope_mismatch")
            expected_prefix = f"private/test/{settings.media_run_id}/"
            if not snapshot["key"].startswith(expected_prefix):
                raise StorageError("cleanup_run_mismatch")
            if snapshot["kind"] == "multipart":
                if not snapshot["upload_id"]:
                    raise StorageError("upload_id_unverified")
                provider.abort_multipart(snapshot["key"], snapshot["upload_id"])
                try:
                    residual = provider.list_parts(snapshot["key"], snapshot["upload_id"])
                except StorageError as exc:
                    if exc.code != "not_found":
                        raise
                else:
                    if residual["parts"] or residual["truncated"]:
                        raise StorageError("abort_unconfirmed")
            elif snapshot["kind"] == "object":
                if not snapshot["version_id"]:
                    raise StorageError("exact_version_required")
                try:
                    head = provider.head_object(snapshot["key"], snapshot["version_id"])
                except StorageError as exc:
                    if exc.code != "not_found":
                        raise
                else:
                    meta = {str(k).lower(): str(v) for k, v in head.get("metadata", {}).items()}
                    expected_meta = {
                        "owner": "swim-platform", "purpose": "isolated-media-transfer",
                        "run-id": settings.media_run_id, "tenant-id": snapshot["tenant_id"],
                        "site-id": snapshot["site_id"], "session-id": snapshot["session_id"],
                        "asset-id": snapshot["asset_id"],
                        "upload-session-id": snapshot["metadata_upload_id"],
                    }
                    if any(meta.get(key) != value for key, value in expected_meta.items()):
                        raise StorageError("cleanup_metadata_mismatch")
                    provider.delete_object(snapshot["key"], snapshot["version_id"])
                    try:
                        provider.head_object(snapshot["key"], snapshot["version_id"])
                    except StorageError as exc:
                        if exc.code != "not_found":
                            raise
                    else:
                        raise StorageError("delete_unconfirmed")
            else:
                raise StorageError("unsupported_cleanup_kind")
            _finish_cleanup_candidate(session_factory, snapshot, now)
            removed += 1
        except (StorageError, OSError) as exc:
            code = exc.code if isinstance(exc, StorageError) else "cleanup_io_error"
            if code in {"cleanup_metadata_mismatch", "cleanup_scope_mismatch", "cleanup_run_mismatch"}:
                _mark_cleanup_manual(session_factory, candidate_id, code, now)
            else:
                _retry_cleanup_candidate(session_factory, candidate_id, code=code, now=now)
            failed += 1
    return {"dry_run": False, "discovery": discovery,
            "candidates": summary, "removed": removed, "failed": failed}


def _claim_cleanup_candidate(session_factory, candidate_id: str, now: datetime) -> dict | None:
    with session_factory() as db:
        candidate = db.get(MediaCleanupCandidate, candidate_id)
        if not candidate or candidate.state not in {"observed", "queued", "retry_wait"} or as_utc(candidate.not_before) > now:
            return None
        if candidate.object_id is None:
            key_parts = candidate.object_key.split("/")
            scope = _orphan_key_scope(candidate.object_key, key_parts[2] if len(key_parts) > 2 else "")
            row_query = select(MediaCleanupCandidate).where(MediaCleanupCandidate.id == candidate_id)
            if db.bind.dialect.name == "postgresql":
                row_query = row_query.with_for_update()
            candidate = db.scalar(row_query.execution_options(populate_existing=True))
            if not scope or not candidate or candidate.state not in {"queued", "retry_wait"}:
                return None
            upload = db.get(UploadSession, scope["upload_id"])
            asset = db.get(VideoAsset, scope["asset_id"])
            media_object = db.scalar(select(MediaObject.id).where(MediaObject.object_key == candidate.object_key))
            if (not upload or not asset or media_object or upload.status not in {"failed", "expired", "aborted"}
                    or asset.status != "failed" or asset.storage_object_ref is not None
                    or upload.tenant_id != scope["tenant_id"] or upload.site_id != scope["site_id"]
                    or upload.session_id != scope["session_id"] or upload.asset_id != scope["asset_id"]):
                candidate.state, candidate.last_error_code, candidate.updated_at = (
                    "manual", "orphan_reference_changed", now
                )
                db.commit()
                return None
            token = uid()
            candidate.state, candidate.lease_token = "running", token
            candidate.lease_until, candidate.attempts = now + timedelta(seconds=LEASE_SECONDS), candidate.attempts + 1
            candidate.updated_at = now
            db.commit()
            return {"id": candidate.id, "object_id": None, "key": candidate.object_key,
                    "kind": candidate.kind, "upload_id": candidate.upload_id,
                    "version_id": candidate.object_version, "profile": candidate.provider_profile,
                    "bucket": candidate.bucket, "tenant_id": candidate.tenant_id,
                    "site_id": candidate.site_id, "session_id": scope["session_id"],
                    "asset_id": scope["asset_id"], "generation": scope["generation"],
                    "upload_session_id": scope["upload_id"], "metadata_upload_id": scope["upload_id"],
                    "lease_token": token}
        logical_upload_id = _upload_id_for_object(db, candidate.object_id)
        locked = _lock_transfer(db, candidate.tenant_id, candidate.site_id, logical_upload_id)
        if not locked:
            return None
        _session, upload, asset, obj = locked
        row_query = select(MediaCleanupCandidate).where(MediaCleanupCandidate.id == candidate_id)
        if db.bind.dialect.name == "postgresql":
            row_query = row_query.with_for_update()
        row = db.scalar(row_query.execution_options(populate_existing=True))
        if not row or not obj or obj.id != candidate.object_id:
            db.rollback()
            return None
        if asset.status == "ready" or asset.storage_object_ref == obj.id:
            row.state, row.last_error_code, row.updated_at = "manual", "retained_asset_reference", now
            db.commit()
            return None
        if upload.status in {"uploading", "completing"} and row.kind == "object":
            row.state, row.last_error_code, row.updated_at = "manual", "active_upload", now
            db.commit()
            return None
        token = uid()
        row.state, row.lease_token, row.lease_until = "running", token, now + timedelta(seconds=LEASE_SECONDS)
        row.attempts += 1
        row.updated_at = now
        obj.phase = "delete_pending"
        db.commit()
        return {"id": row.id, "object_id": obj.id, "key": obj.object_key,
                "kind": row.kind, "upload_id": row.upload_id,
                "version_id": row.object_version, "profile": row.provider_profile,
                "bucket": row.bucket, "tenant_id": row.tenant_id,
                "site_id": row.site_id, "session_id": row.session_id,
                "asset_id": row.asset_id, "metadata_upload_id": obj.upload_session_id,
                "generation": row.generation,
                "lease_token": token}


def _upload_id_for_object(db: Session, object_id: str) -> str:
    obj = db.get(MediaObject, object_id)
    return obj.upload_session_id if obj else ""


def _finish_cleanup_candidate(session_factory, snapshot: dict, now: datetime):
    with session_factory() as db:
        if snapshot["object_id"] is None:
            query = select(MediaCleanupCandidate).where(MediaCleanupCandidate.id == snapshot["id"])
            if db.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            candidate = db.scalar(query.execution_options(populate_existing=True))
            if not candidate or candidate.state != "running" or candidate.lease_token != snapshot["lease_token"]:
                db.rollback()
                return
            candidate.state, candidate.lease_token, candidate.lease_until = "deleted", None, None
            candidate.deleted_at, candidate.updated_at = now, now
            candidate.last_error_code = None
            db.commit()
            return
        locked = _lock_transfer(db, snapshot["tenant_id"], snapshot["site_id"],
                                _upload_id_for_object(db, snapshot["object_id"]))
        if not locked:
            return
        _session, upload, asset, obj = locked
        candidate_query = select(MediaCleanupCandidate).where(
            MediaCleanupCandidate.id == snapshot["id"],
        )
        if db.bind.dialect.name == "postgresql":
            candidate_query = candidate_query.with_for_update()
        candidate = db.scalar(candidate_query)
        if (not candidate or candidate.state != "running"
                or candidate.lease_token != snapshot["lease_token"]
                or asset.storage_object_ref == obj.id or asset.status == "ready"):
            db.rollback()
            return
        candidate.state, candidate.lease_token, candidate.lease_until = "deleted", None, None
        candidate.deleted_at, candidate.updated_at = now, now
        candidate.last_error_code = None
        if snapshot["kind"] == "object" and candidate.object_version == obj.object_version:
            obj.phase, obj.deleted_at, obj.updated_at = "deleted", now, now
        db.commit()


def _mark_cleanup_manual(session_factory, snapshot: dict | str, code: str, now: datetime):
    candidate_id = snapshot if isinstance(snapshot, str) else snapshot["id"]
    with session_factory() as db:
        row = db.get(MediaCleanupCandidate, candidate_id)
        if row and row.state in {"observed", "queued", "retry_wait", "running"}:
            row.state, row.lease_token, row.lease_until = "manual", None, None
            row.last_error_code, row.updated_at = code, now
            db.commit()


def _retry_cleanup_candidate(session_factory, candidate_id: str, *, code: str, now: datetime):
    with session_factory() as db:
        row = db.get(MediaCleanupCandidate, candidate_id)
        if not row or row.state != "running":
            return
        row.last_error_code = code[:64]
        row.state, row.lease_token, row.lease_until = "retry_wait", None, None
        row.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(row.attempts, 12)))
        row.updated_at = now
        db.commit()
