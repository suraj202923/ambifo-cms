from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer
from ..models.gathering import (
    GatheringBlockStorageDetail,
    GatheringFileNasDetail,
    GatheringRequest,
    GatheringServerDetail,
)
from ..models.user import User
from ..schemas.gathering import (
    BlockStorageDetailOut,
    FileNasDetailOut,
    GatheringDetailOut,
    GatheringPublicOut,
    GatheringRequestCreate,
    GatheringRequestOut,
    GatheringSubmitIn,
    GatheringSubmitResult,
    GatheringVerifyIn,
    ServerDetailOut,
)
from ..security import hash_password, verify_password
from ..services.messaging import format_dt, now_utc, send_email_via_engine

router = APIRouter(prefix="/api/gathering", tags=["gathering"])
public_router = APIRouter(prefix="/api/public/gathering", tags=["public-gathering"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def _customer_name(db: Session, customer_id: int) -> tuple[Customer, str]:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer, customer.customer_name or customer.account_name or "customer"


def _request_out(db: Session, req: GatheringRequest) -> GatheringRequestOut:
    customer = db.get(Customer, req.customer_id)
    out = GatheringRequestOut.model_validate(req)
    out.customer_name = customer.customer_name or customer.account_name if customer else None
    out.server_count = (
        db.query(GatheringServerDetail).filter(GatheringServerDetail.gathering_request_id == req.id).count()
    )
    out.block_count = (
        db.query(GatheringBlockStorageDetail).filter(GatheringBlockStorageDetail.gathering_request_id == req.id).count()
    )
    out.file_count = (
        db.query(GatheringFileNasDetail).filter(GatheringFileNasDetail.gathering_request_id == req.id).count()
    )
    return out


def _detail_out(db: Session, req: GatheringRequest) -> GatheringDetailOut:
    base = _request_out(db, req)
    out = GatheringDetailOut.model_validate(base.model_dump())
    out.servers = [
        ServerDetailOut.model_validate(s)
        for s in db.query(GatheringServerDetail).filter(GatheringServerDetail.gathering_request_id == req.id).all()
    ]
    out.block_storage = [
        BlockStorageDetailOut.model_validate(b)
        for b in db.query(GatheringBlockStorageDetail).filter(GatheringBlockStorageDetail.gathering_request_id == req.id).all()
    ]
    out.file_nas = [
        FileNasDetailOut.model_validate(f)
        for f in db.query(GatheringFileNasDetail).filter(GatheringFileNasDetail.gathering_request_id == req.id).all()
    ]
    return out


def _public_out(db: Session, req: GatheringRequest) -> GatheringPublicOut:
    return GatheringPublicOut(
        customer_id=req.customer_id,
        note=req.note,
        expires_at=req.expires_at,
        access_key_hint=req.access_key_hint,
        access_verified_at=req.access_verified_at,
        is_locked=req.is_locked,
        status=req.status,
    )


# ------------------------------------------------------------- internal
@router.post("/requests", response_model=GatheringRequestOut, status_code=status.HTTP_201_CREATED)
def create_gathering_request(
    payload: GatheringRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer, name = _customer_name(db, payload.customer_id)
    token = token_urlsafe(24)
    expires_at = now() + timedelta(days=payload.expires_days)

    access_hash = None
    access_hint = None
    if payload.access_key:
        access_hash = hash_password(payload.access_key)
        access_hint = payload.access_key[-4:] if len(payload.access_key) >= 4 else payload.access_key

    req = GatheringRequest(
        token=token,
        customer_id=payload.customer_id,
        note=payload.note,
        expires_at=expires_at,
        access_key_hash=access_hash,
        access_key_hint=access_hint,
        status="sent",
        created_at=now(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    if payload.send_email:
        link = f"{settings.frontend_url}/public/gathering/{token}"
        subject = "Ambifo - Gathering Sheet & Information Request"
        body = (
            "Hi {{customer_name}},\n\n"
            "Use the link below to share your current infrastructure with us.\n{{gathering_form_link}}\n\n"
            "{{access_key_block}}{{note_block}}This link expires on {{expires_at}}.\n\nRegards,\nThe Ambifo Team"
        )
        body = body.replace("{{access_key_block}}", access_hint and f"Access key (last 4: {access_hint}) - you will be asked for it.\n\n" or "")
        body = body.replace("{{note_block}}", payload.note and f"Note: {payload.note}\n\n" or "")
        ctx = {
            "customer_name": name,
            "gathering_form_link": link,
            "expires_at": format_dt(expires_at),
        }
        try:
            send_email_via_engine(customer.email, subject, body, ctx,
                                  email_type="gathering", customer_id=customer.id)
        except Exception:  # noqa: BLE001 - link creation must not fail without SMTP
            pass

    return _request_out(db, req)


@router.get("/requests", response_model=list[GatheringRequestOut])
def list_gathering_requests(
    customer_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(GatheringRequest)
    if customer_id:
        q = q.filter(GatheringRequest.customer_id == customer_id)
    return [
        _request_out(db, r)
        for r in q.order_by(GatheringRequest.created_at.desc()).limit(min(limit, 500)).all()
    ]


@router.get("/requests/{request_id}", response_model=GatheringDetailOut)
def get_gathering_request(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return _detail_out(db, req)


@router.post("/requests/{request_id}/lock", response_model=GatheringRequestOut)
def lock_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.is_locked = True
    req.locked_at = now()
    req.locked_by = current_user.username
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


@router.post("/requests/{request_id}/unlock", response_model=GatheringRequestOut)
def unlock_request(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.is_locked = False
    req.locked_at = None
    req.locked_by = None
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


@router.post("/requests/{request_id}/renew", response_model=GatheringRequestOut)
def renew_request(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.token = token_urlsafe(24)
    req.expires_at = now() + timedelta(days=14)
    req.status = "sent"
    req.is_locked = False
    req.locked_at = None
    req.locked_by = None
    db.commit()
    db.refresh(req)
    return _request_out(db, req)


@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    for cls in (GatheringServerDetail, GatheringBlockStorageDetail, GatheringFileNasDetail):
        db.query(cls).filter(cls.gathering_request_id == request_id).update({cls.gathering_request_id: None})
    db.delete(req)
    db.commit()


@router.delete("/requests/{request_id}/details", status_code=status.HTTP_204_NO_CONTENT)
def delete_submitted_details(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(GatheringRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    db.query(GatheringServerDetail).filter(GatheringServerDetail.gathering_request_id == request_id).delete()
    db.query(GatheringBlockStorageDetail).filter(GatheringBlockStorageDetail.gathering_request_id == request_id).delete()
    db.query(GatheringFileNasDetail).filter(GatheringFileNasDetail.gathering_request_id == request_id).delete()
    db.commit()


# ------------------------------------------------------------- public
def _get_public_request(db: Session, token: str) -> GatheringRequest:
    req = db.query(GatheringRequest).filter(GatheringRequest.token == token).first()
    if not req:
        raise HTTPException(status_code=404, detail="Link not found")
    if req.is_locked:
        raise HTTPException(status_code=423, detail="This gathering request is locked")
    if req.expires_at and req.expires_at < now():
        req.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="This gathering link has expired")
    return req


@public_router.get("/{token}", response_model=GatheringPublicOut)
def public_gathering_info(token: str, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    return _public_out(db, req)


@public_router.post("/{token}/verify", response_model=GatheringPublicOut)
def public_gathering_verify(token: str, payload: GatheringVerifyIn, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    if not req.access_key_hash:
        return _public_out(db, req)
    if not verify_password(payload.access_key, req.access_key_hash):
        raise HTTPException(status_code=403, detail="Incorrect access key")
    req.access_verified_at = now()
    db.commit()
    return _public_out(db, req)


@public_router.post("/{token}/submit", response_model=GatheringSubmitResult)
def public_gathering_submit(token: str, payload: GatheringSubmitIn, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    if req.access_key_hash and not req.access_verified_at:
        raise HTTPException(status_code=403, detail="Access key not verified yet")

    req.company_website = payload.company_website
    req.current_tools = payload.current_tools
    req.pain_points = payload.pain_points
    req.submitted_at = now()
    req.status = "submitted"

    db.query(GatheringServerDetail).filter(GatheringServerDetail.gathering_request_id == req.id).delete()
    db.query(GatheringBlockStorageDetail).filter(GatheringBlockStorageDetail.gathering_request_id == req.id).delete()
    db.query(GatheringFileNasDetail).filter(GatheringFileNasDetail.gathering_request_id == req.id).delete()

    for s in payload.servers:
        db.add(GatheringServerDetail(
            customer_id=req.customer_id,
            gathering_request_id=req.id,
            server_name=s.server_name,
            cpu_cores=s.cpu_cores,
            memory_mb=s.memory_mb,
            provisioned_storage_gb=s.provisioned_storage_gb,
            operating_system=s.operating_system,
            is_virtual=s.is_virtual,
            hypervisor_name=s.hypervisor_name,
            cpu_string=s.cpu_string,
            environment=s.environment,
            sql_edition=s.sql_edition,
            application=s.application,
            cpu_utilization_peak=s.cpu_utilization_peak,
            memory_utilization_peak=s.memory_utilization_peak,
            time_in_use=s.time_in_use,
            annual_cost_usd=s.annual_cost_usd,
            storage_type=s.storage_type,
            created_at=now(),
        ))
    for b in payload.block_storage:
        db.add(GatheringBlockStorageDetail(
            customer_id=req.customer_id,
            gathering_request_id=req.id,
            volume_name=b.volume_name,
            total_used_capacity_gb=b.total_used_capacity_gb,
            total_provisioned_capacity_gb=b.total_provisioned_capacity_gb,
            peak_iops=b.peak_iops,
            peak_throughput_mbps=b.peak_throughput_mbps,
            average_iops=b.average_iops,
            average_throughput_mbps=b.average_throughput_mbps,
            array_name=b.array_name,
            average_latency_ms=b.average_latency_ms,
            application=b.application,
            created_at=now(),
        ))
    for f in payload.file_nas:
        db.add(GatheringFileNasDetail(
            customer_id=req.customer_id,
            gathering_request_id=req.id,
            file_server_share_name=f.file_server_share_name,
            total_used_capacity_gb=f.total_used_capacity_gb,
            access_protocol=f.access_protocol,
            total_provisioned_capacity_gb=f.total_provisioned_capacity_gb,
            storage_efficiency_ratio=f.storage_efficiency_ratio,
            peak_iops=f.peak_iops,
            peak_throughput_mbps=f.peak_throughput_mbps,
            average_iops=f.average_iops,
            average_throughput_mbps=f.average_throughput_mbps,
            storage_pool_name=f.storage_pool_name,
            array_name=f.array_name,
            array_vendor=f.array_vendor,
            average_latency_ms=f.average_latency_ms,
            application=f.application,
            created_at=now(),
        ))

    db.commit()
    return GatheringSubmitResult(ok=True, status="submitted", submitted_at=req.submitted_at)