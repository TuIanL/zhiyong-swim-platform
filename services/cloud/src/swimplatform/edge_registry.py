"""Cloud Edge Registry API and transaction boundary."""
import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import Current, DB, as_utc, fail, site_access
from .models import Device, EdgeCredential, EdgeNode, IdempotencyRecord
from .schemas import (
    DeviceCreate,
    DevicePatch,
    DeviceRead,
    EdgeCredentialIssue,
    EdgeCredentialIssued,
    EdgeCredentialRead,
    EdgeNodeCreate,
    EdgeNodePatch,
    EdgeNodeRead,
    HeartbeatRead,
    HeartbeatRequest,
)
from .security import token_hash

router = APIRouter(prefix="/api/v1")
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~:-]{8,128}$")
EDGE_TOKEN_PREFIX = "swim_edge_"
HEARTBEAT_INTERVAL_SECONDS = 30
ONLINE_WINDOW_SECONDS = 90


def server_now(request: Request) -> datetime:
    """UTC clock seam for deterministic tests; production uses the cloud service clock."""
    clock = getattr(request.app.state, "clock", None)
    value = clock() if clock else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError("server clock must return an aware datetime")
    return value.astimezone(UTC)


def is_online(node: EdgeNode, now: datetime) -> bool:
    last_seen = as_utc(node.last_seen_at)
    if node.status != "active" or last_seen is None:
        return False
    age = (now - last_seen).total_seconds()
    return 0 <= age < ONLINE_WINDOW_SECONDS


def edge_node_read(node: EdgeNode, now: datetime) -> EdgeNodeRead:
    return EdgeNodeRead(
        id=node.id,
        tenant_id=node.tenant_id,
        site_id=node.site_id,
        name=node.name,
        status=node.status,
        config_revision=node.config_revision,
        applied_config_revision=node.applied_config_revision,
        last_seen_at=as_utc(node.last_seen_at),
        online=is_online(node, now),
        software_version=node.software_version,
        health_status=node.health_status,
        observed_at_raw=node.observed_at_raw,
        created_by_user_id=node.created_by_user_id,
        created_at=as_utc(node.created_at),
        updated_at=as_utc(node.updated_at),
    )


def device_read(device: Device) -> DeviceRead:
    return DeviceRead(
        id=device.id,
        tenant_id=device.tenant_id,
        site_id=device.site_id,
        edge_node_id=device.edge_node_id,
        name=device.name,
        kind=device.kind,
        status=device.status,
        hardware_serial=device.hardware_serial,
        created_at=as_utc(device.created_at),
        updated_at=as_utc(device.updated_at),
    )


def credential_read(credential: EdgeCredential) -> EdgeCredentialRead:
    return EdgeCredentialRead(
        id=credential.id,
        edge_node_id=credential.edge_node_id,
        generation=credential.generation,
        issued_at=as_utc(credential.issued_at),
        expires_at=as_utc(credential.expires_at),
        issued_by_user_id=credential.issued_by_user_id,
        revoked_at=as_utc(credential.revoked_at),
        revoked_by_user_id=credential.revoked_by_user_id,
    )


def require_manager_site(db: Session, tenant_id: UUID, site_id: UUID, user):
    return site_access(db, tenant_id, site_id, user, manage=True)


def get_node(db: Session, tenant_id: UUID, site_id: UUID, edge_node_id: UUID) -> EdgeNode:
    node = db.scalar(select(EdgeNode).where(
        EdgeNode.id == str(edge_node_id),
        EdgeNode.tenant_id == str(tenant_id),
        EdgeNode.site_id == str(site_id),
    ))
    if not node:
        fail(404, "edge_node_not_found", "节点不存在或无访问权限")
    return node


def lock_node(db: Session, node_id: str) -> EdgeNode | None:
    query = select(EdgeNode).where(EdgeNode.id == node_id).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        # SQLite serializes writers at the database level; this conditional write acquires the
        # write lock before lifecycle checks without relying on a process-local mutex.
        result = db.execute(
            update(EdgeNode).where(EdgeNode.id == node_id).values(updated_at=EdgeNode.updated_at)
        )
        if result.rowcount != 1:
            return None
    return db.scalar(query)


def lock_manager_node(db: Session, tenant_id: str, site_id: str, node_id: str) -> EdgeNode | None:
    """Lock only a Node inside the manager's already-authorized Tenant/Site scope."""
    scope = (
        EdgeNode.id == node_id,
        EdgeNode.tenant_id == tenant_id,
        EdgeNode.site_id == site_id,
    )
    query = select(EdgeNode).where(*scope).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        # Preserve the SQLite write-serialization behavior while applying the same scope
        # predicate before attempting the conditional write.
        result = db.execute(
            update(EdgeNode).where(*scope).values(updated_at=EdgeNode.updated_at)
        )
        if result.rowcount != 1:
            return None
    return db.scalar(query)


def idempotency_key_digest(value: str) -> str:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        fail(422, "invalid_idempotency_key", "Idempotency-Key须为8至128位受限ASCII字符")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def request_digest(payload) -> str:
    normalized = payload.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def find_idempotency(db, *, tenant_id, site_id, user_id, operation, target_id, key_hash):
    return db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == tenant_id,
        IdempotencyRecord.site_id == site_id,
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.target_id == target_id,
        IdempotencyRecord.key_hash == key_hash,
    ))


def handle_existing(record: IdempotencyRecord | None, digest: str, *, secret_once=False):
    if not record:
        return None
    if record.request_hash != digest:
        fail(409, "idempotency_conflict", "同一幂等键已用于不同请求参数")
    if secret_once:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "credential_secret_not_replayable",
                "message": "凭据明文仅在首次签发响应中返回",
                "credential_id": record.resource_id,
            },
        )


def resource_from_record(db, record: IdempotencyRecord, model):
    return db.get(model, record.resource_id)


def commit_idempotently(
    db: Session,
    *,
    tenant_id: str,
    site_id: str,
    user_id: str,
    operation: str,
    target_id: str,
    key_digest: str,
    request_digest_value: str,
    resource_kind: str,
    resource,
    secret_once: bool = False,
):
    record = find_idempotency(
        db, tenant_id=tenant_id, site_id=site_id, user_id=user_id,
        operation=operation, target_id=target_id, key_hash=key_digest,
    )
    if record:
        handle_existing(record, request_digest_value, secret_once=secret_once)
        existing = resource_from_record(db, record, type(resource))
        if existing is None:
            fail(409, "registry_conflict", "幂等记录指向的资源不存在")
        return existing, False

    db.add(resource)
    db.flush()
    db.add(IdempotencyRecord(
        tenant_id=tenant_id,
        site_id=site_id,
        user_id=user_id,
        operation=operation,
        target_id=target_id,
        key_hash=key_digest,
        request_hash=request_digest_value,
        resource_kind=resource_kind,
        resource_id=resource.id,
    ))
    try:
        db.commit()
        return resource, True
    except IntegrityError:
        db.rollback()
        record = find_idempotency(
            db, tenant_id=tenant_id, site_id=site_id, user_id=user_id,
            operation=operation, target_id=target_id, key_hash=key_digest,
        )
        if not record:
            fail(409, "registry_conflict", "资源写入冲突")
        handle_existing(record, request_digest_value, secret_once=secret_once)
        existing = resource_from_record(db, record, type(resource))
        if existing is None:
            fail(409, "registry_conflict", "幂等记录指向的资源不存在")
        return existing, False


def get_edge_identity(db: Session, authorization: str | None, now: datetime) -> tuple[EdgeNode, EdgeCredential]:
    if not authorization:
        fail(401, "edge_unauthorized", "缺少Edge凭据")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.startswith(EDGE_TOKEN_PREFIX) or len(token) > 256:
        fail(401, "edge_unauthorized", "Edge凭据无效")
    digest = token_hash(token)
    initial = db.scalar(select(EdgeCredential).where(EdgeCredential.token_hash == digest))
    if not initial:
        fail(401, "edge_unauthorized", "Edge凭据无效")
    node = lock_node(db, initial.edge_node_id)
    if not node:
        fail(401, "edge_unauthorized", "Edge凭据无效")
    credential_query = select(EdgeCredential).where(
        EdgeCredential.id == initial.id,
        EdgeCredential.token_hash == digest,
    ).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        credential_query = credential_query.with_for_update()
    credential = db.scalar(credential_query)
    if (
        not credential
        or credential.revoked_at is not None
        or credential.generation != node.credential_generation
        or as_utc(credential.expires_at) <= now
        or node.status != "active"
    ):
        fail(401, "edge_unauthorized", "Edge凭据无效或节点未激活")
    return node, credential


@router.get("/tenants/{tenant_id}/sites/{site_id}/edge-nodes", response_model=list[EdgeNodeRead])
def list_edge_nodes(
    tenant_id: UUID, site_id: UUID, request: Request, user: Current, db: DB,
    status: Annotated[str | None, Query(pattern="^(pending|active|disabled)$")] = None,
):
    require_manager_site(db, tenant_id, site_id, user)
    query = select(EdgeNode).where(
        EdgeNode.tenant_id == str(tenant_id), EdgeNode.site_id == str(site_id)
    )
    if status:
        query = query.where(EdgeNode.status == status)
    rows = db.scalars(query.order_by(EdgeNode.created_at, EdgeNode.id)).all()
    now = server_now(request)
    return [edge_node_read(row, now) for row in rows]


@router.post("/tenants/{tenant_id}/sites/{site_id}/edge-nodes", response_model=EdgeNodeRead, status_code=201)
def create_edge_node(
    tenant_id: UUID, site_id: UUID, payload: EdgeNodeCreate, request: Request,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")], user: Current, db: DB,
):
    site = require_manager_site(db, tenant_id, site_id, user)
    key_digest = idempotency_key_digest(idempotency_header)
    now = server_now(request)
    node = EdgeNode(
        tenant_id=str(tenant_id), site_id=str(site_id), name=payload.name,
        status="pending", config_revision=1, credential_generation=0,
        created_by_user_id=user.id, created_at=now, updated_at=now,
    )
    node, _ = commit_idempotently(
        db, tenant_id=str(tenant_id), site_id=site.id, user_id=user.id,
        operation="edge_node.create", target_id=site.id, key_digest=key_digest,
        request_digest_value=request_digest(payload), resource_kind="edge_node", resource=node,
    )
    return edge_node_read(node, server_now(request))


@router.get("/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}", response_model=EdgeNodeRead)
def read_edge_node(tenant_id: UUID, site_id: UUID, edge_node_id: UUID, request: Request, user: Current, db: DB):
    require_manager_site(db, tenant_id, site_id, user)
    return edge_node_read(get_node(db, tenant_id, site_id, edge_node_id), server_now(request))


@router.patch("/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}", response_model=EdgeNodeRead)
def update_edge_node(
    tenant_id: UUID, site_id: UUID, edge_node_id: UUID, payload: EdgeNodePatch,
    request: Request, user: Current, db: DB,
):
    require_manager_site(db, tenant_id, site_id, user)
    node = lock_manager_node(db, str(tenant_id), str(site_id), str(edge_node_id))
    if not node:
        fail(404, "edge_node_not_found", "节点不存在或无访问权限")
    now = server_now(request)
    changes = payload.model_dump(exclude_unset=True)
    changed = False
    if "name" in changes:
        if node.name != changes["name"]:
            node.name = changes["name"]
            changed = True
    if "status" in changes:
        target_status = changes["status"]
        if target_status != node.status:
            changed = True
            allowed = {
                "pending": {"active", "disabled"},
                "active": {"disabled"},
                "disabled": {"active"},
            }
            if target_status not in allowed[node.status]:
                fail(409, "state_conflict", "节点状态迁移不允许")
            if target_status == "disabled":
                node.status = "disabled"
                node.credential_generation += 1
                db.execute(update(EdgeCredential).where(
                    EdgeCredential.tenant_id == node.tenant_id,
                    EdgeCredential.site_id == node.site_id,
                    EdgeCredential.edge_node_id == node.id,
                    EdgeCredential.revoked_at.is_(None),
                ).values(revoked_at=now, revoked_by_user_id=user.id))
            elif target_status == "active" and node.status == "disabled":
                fresh = db.scalar(select(EdgeCredential.id).where(
                    EdgeCredential.edge_node_id == node.id,
                    EdgeCredential.generation == node.credential_generation,
                    EdgeCredential.revoked_at.is_(None),
                    EdgeCredential.expires_at > now,
                ).limit(1))
                if not fresh:
                    fail(409, "state_conflict", "恢复节点前须为当前代签发有效新凭据")
                node.status = "active"
            else:
                node.status = target_status
    if not changed:
        return edge_node_read(node, server_now(request))
    node.updated_at = now
    db.commit()
    return edge_node_read(node, now)


@router.get(
    "/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials",
    response_model=list[EdgeCredentialRead],
)
def list_edge_credentials(tenant_id: UUID, site_id: UUID, edge_node_id: UUID, user: Current, db: DB):
    require_manager_site(db, tenant_id, site_id, user)
    get_node(db, tenant_id, site_id, edge_node_id)
    rows = db.scalars(select(EdgeCredential).where(
        EdgeCredential.tenant_id == str(tenant_id),
        EdgeCredential.site_id == str(site_id),
        EdgeCredential.edge_node_id == str(edge_node_id),
    ).order_by(EdgeCredential.issued_at, EdgeCredential.id)).all()
    return [credential_read(row) for row in rows]


@router.post(
    "/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials",
    response_model=EdgeCredentialIssued,
    status_code=201,
)
def issue_edge_credential(
    tenant_id: UUID, site_id: UUID, edge_node_id: UUID, payload: EdgeCredentialIssue, request: Request,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")], user: Current, db: DB,
):
    require_manager_site(db, tenant_id, site_id, user)
    node = lock_manager_node(db, str(tenant_id), str(site_id), str(edge_node_id))
    if not node:
        fail(404, "edge_node_not_found", "节点不存在或无访问权限")
    key_digest = idempotency_key_digest(idempotency_header)
    target = str(edge_node_id)
    digest = request_digest(payload)
    existing = find_idempotency(
        db, tenant_id=str(tenant_id), site_id=str(site_id), user_id=user.id,
        operation="edge_credential.issue", target_id=target, key_hash=key_digest,
    )
    if existing:
        handle_existing(existing, digest, secret_once=True)
    now = server_now(request)
    expires_at = payload.expires_at or (now + timedelta(days=7))
    if expires_at <= now or expires_at > now + timedelta(days=30):
        fail(422, "invalid_credential_expiry", "凭据期限须大于当前时刻且不超过30天")
    token = EDGE_TOKEN_PREFIX + secrets.token_urlsafe(32)
    credential = EdgeCredential(
        tenant_id=str(tenant_id), site_id=str(site_id), edge_node_id=node.id,
        generation=node.credential_generation, token_hash=token_hash(token),
        issued_at=now, expires_at=expires_at, issued_by_user_id=user.id,
    )
    credential, created = commit_idempotently(
        db, tenant_id=str(tenant_id), site_id=str(site_id), user_id=user.id,
        operation="edge_credential.issue", target_id=target, key_digest=key_digest,
        request_digest_value=digest, resource_kind="edge_credential", resource=credential,
        secret_once=True,
    )
    if not created:
        # A prior response may have committed while this request waited for the node row lock.
        fail(409, "credential_secret_not_replayable", "凭据明文仅在首次签发响应中返回")
    response = credential_read(credential).model_dump()
    return EdgeCredentialIssued(**response, token=token)


@router.delete(
    "/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials/{credential_id}",
    status_code=204,
)
def revoke_edge_credential(
    tenant_id: UUID, site_id: UUID, edge_node_id: UUID, credential_id: UUID,
    request: Request, user: Current, db: DB,
):
    require_manager_site(db, tenant_id, site_id, user)
    node = lock_manager_node(db, str(tenant_id), str(site_id), str(edge_node_id))
    if not node:
        fail(404, "edge_node_not_found", "节点不存在或无访问权限")
    credential_query = select(EdgeCredential).where(
        EdgeCredential.id == str(credential_id),
        EdgeCredential.tenant_id == str(tenant_id),
        EdgeCredential.site_id == str(site_id),
        EdgeCredential.edge_node_id == node.id,
    ).execution_options(populate_existing=True)
    if db.bind.dialect.name == "postgresql":
        credential_query = credential_query.with_for_update()
    credential = db.scalar(credential_query)
    if not credential:
        fail(404, "credential_not_found", "凭据不存在或无访问权限")
    if credential.revoked_at is None:
        credential.revoked_at = server_now(request)
        credential.revoked_by_user_id = user.id
        db.commit()
    return Response(status_code=204)


@router.get("/tenants/{tenant_id}/sites/{site_id}/devices", response_model=list[DeviceRead])
def list_devices(
    tenant_id: UUID, site_id: UUID, user: Current, db: DB,
    edge_node_id: UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(active|disabled)$")] = None,
):
    require_manager_site(db, tenant_id, site_id, user)
    query = select(Device).where(Device.tenant_id == str(tenant_id), Device.site_id == str(site_id))
    if edge_node_id:
        query = query.where(Device.edge_node_id == str(edge_node_id))
    if status:
        query = query.where(Device.status == status)
    return [device_read(row) for row in db.scalars(query.order_by(Device.created_at, Device.id)).all()]


@router.post("/tenants/{tenant_id}/sites/{site_id}/devices", response_model=DeviceRead, status_code=201)
def create_device(
    tenant_id: UUID, site_id: UUID, payload: DeviceCreate, request: Request,
    idempotency_header: Annotated[str, Header(alias="Idempotency-Key")], user: Current, db: DB,
):
    site = require_manager_site(db, tenant_id, site_id, user)
    visible_node = get_node(db, tenant_id, site_id, payload.edge_node_id)
    key_digest = idempotency_key_digest(idempotency_header)
    digest = request_digest(payload)
    existing = find_idempotency(
        db, tenant_id=str(tenant_id), site_id=str(site_id), user_id=user.id,
        operation="device.create", target_id=visible_node.id, key_hash=key_digest,
    )
    if existing:
        handle_existing(existing, digest)
        existing_device = resource_from_record(db, existing, Device)
        if not existing_device:
            fail(409, "registry_conflict", "幂等记录指向的设备不存在")
        return device_read(existing_device)

    node = lock_node(db, visible_node.id)
    if not node or node.tenant_id != str(tenant_id) or node.site_id != str(site_id):
        fail(404, "edge_node_not_found", "节点不存在或无访问权限")
    if node.status != "active":
        fail(409, "state_conflict", "设备所属节点必须处于active状态")
    # If a same-key request committed while this request waited for the parent row lock,
    # replay its committed resource instead of creating another row.
    existing = find_idempotency(
        db, tenant_id=str(tenant_id), site_id=str(site_id), user_id=user.id,
        operation="device.create", target_id=node.id, key_hash=key_digest,
    )
    if existing:
        handle_existing(existing, digest)
        existing_device = resource_from_record(db, existing, Device)
        if not existing_device:
            fail(409, "registry_conflict", "幂等记录指向的设备不存在")
        return device_read(existing_device)
    now = server_now(request)
    device = Device(
        tenant_id=str(tenant_id), site_id=str(site_id), edge_node_id=node.id,
        name=payload.name, kind=payload.kind, status="active",
        hardware_serial=payload.hardware_serial, created_at=now, updated_at=now,
    )
    device, _ = commit_idempotently(
        db, tenant_id=str(tenant_id), site_id=site.id, user_id=user.id,
        operation="device.create", target_id=node.id, key_digest=key_digest,
        request_digest_value=digest, resource_kind="device", resource=device,
    )
    return device_read(device)


@router.get("/tenants/{tenant_id}/sites/{site_id}/devices/{device_id}", response_model=DeviceRead)
def read_device(tenant_id: UUID, site_id: UUID, device_id: UUID, user: Current, db: DB):
    require_manager_site(db, tenant_id, site_id, user)
    device = db.scalar(select(Device).where(
        Device.id == str(device_id), Device.tenant_id == str(tenant_id), Device.site_id == str(site_id)
    ))
    if not device:
        fail(404, "device_not_found", "设备不存在或无访问权限")
    return device_read(device)


@router.patch("/tenants/{tenant_id}/sites/{site_id}/devices/{device_id}", response_model=DeviceRead)
def update_device(
    tenant_id: UUID, site_id: UUID, device_id: UUID, payload: DevicePatch,
    request: Request, user: Current, db: DB,
):
    require_manager_site(db, tenant_id, site_id, user)
    device = db.scalar(select(Device).where(
        Device.id == str(device_id), Device.tenant_id == str(tenant_id), Device.site_id == str(site_id)
    ))
    if not device:
        fail(404, "device_not_found", "设备不存在或无访问权限")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") == "active":
        node = lock_node(db, device.edge_node_id)
        if not node or node.status != "active":
            fail(409, "state_conflict", "设备所属节点必须处于active状态")
    if all(getattr(device, key) == value for key, value in changes.items()):
        return device_read(device)
    for key, value in changes.items():
        setattr(device, key, value)
    device.updated_at = server_now(request)
    db.commit()
    return device_read(device)


@router.post("/edge/heartbeat", response_model=HeartbeatRead)
def heartbeat(
    payload: HeartbeatRequest, request: Request, db: DB,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
):
    now = server_now(request)
    node, _ = get_edge_identity(db, authorization, now)
    node.last_seen_at = now
    if payload.reported_config_revision is not None:
        node.applied_config_revision = payload.reported_config_revision
    if payload.observed_at_raw is not None:
        node.observed_at_raw = payload.observed_at_raw
    if payload.health is not None:
        if payload.health.software_version is not None:
            node.software_version = payload.health.software_version
        if payload.health.status is not None:
            node.health_status = payload.health.status
    node.updated_at = now
    db.commit()
    return HeartbeatRead(
        edge_node_id=node.id,
        last_seen_at=now,
        online=is_online(node, now),
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
        online_window_seconds=ONLINE_WINDOW_SECONDS,
    )
