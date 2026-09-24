from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer
from ..models.meetings import MeetingAvailabilityRequest, MeetingInvite
from ..models.user import User
from ..schemas.meetings import (
    AvailabilityCreate,
    AvailabilityFormIn,
    AvailabilityOut,
    AvailabilitySelectIn,
    InviteCreate,
    InviteOut,
)
from ..services.messaging import format_dt, now_utc, send_email_via_engine

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
public_router = APIRouter(prefix="/api/public/meetings", tags=["public-meetings"])


def _customer_name(db: Session, customer_id: int) -> tuple[Customer, str]:
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer, customer.customer_name or customer.account_name or "customer"


# ------------------------------------------------------------- invites
@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    payload: InviteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer, name = _customer_name(db, payload.customer_id)
    recipient = payload.recipient_email or customer.email
    subject = payload.subject or f"Meeting with Ambifo — {name}"
    body_template = (
        "Hi {{customer_name}},\n\n"
        "We look forward to meeting you. Join here:\n{{meeting_link}}\n\n"
        "{{agenda_block}}{{required_data_block}}Regards,\nThe Ambifo Team"
    )
    body = body_template.replace("{{agenda_block}}", payload.agenda and f"Agenda:\n{payload.agenda}\n\n" or "")
    body = body.replace("{{required_data_block}}", payload.required_data and f"Please bring:\n{payload.required_data}\n\n" or "")
    ctx = {"customer_name": name, "meeting_link": payload.meeting_link}

    send_email_via_engine(recipient, subject, body, ctx)

    invite = MeetingInvite(
        customer_id=payload.customer_id,
        recipient_email=recipient,
        subject=subject,
        meeting_link=payload.meeting_link,
        agenda=payload.agenda,
        required_data=payload.required_data,
        scheduled_at=payload.scheduled_at,
        created_by=current_user.username,
        created_at=now_utc(),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return _invite_out(db, invite)


@router.get("/invites", response_model=list[InviteOut])
def list_invites(
    customer_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(MeetingInvite)
    if customer_id:
        q = q.filter(MeetingInvite.customer_id == customer_id)
    return [_invite_out(db, i) for i in q.order_by(MeetingInvite.created_at.desc()).limit(min(limit, 500)).all()]


@router.get("/invites/{invite_id}", response_model=InviteOut)
def get_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    invite = db.get(MeetingInvite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    return _invite_out(db, invite)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    invite = db.get(MeetingInvite, invite_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    db.delete(invite)
    db.commit()


def _invite_out(db: Session, invite: MeetingInvite) -> InviteOut:
    customer = db.get(Customer, invite.customer_id)
    out = InviteOut.model_validate(invite)
    out.customer_name = customer.customer_name or customer.account_name if customer else None
    return out


# ------------------------------------------------------------- availability
@router.post("/availability", response_model=AvailabilityOut, status_code=status.HTTP_201_CREATED)
def create_availability(
    payload: AvailabilityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer, name = _customer_name(db, payload.customer_id)
    recipient = payload.recipient_email or customer.email
    subject = payload.subject or f"Pick a time to meet — {name}"
    token = token_urlsafe(24)
    expires_at = now_utc() + timedelta(days=payload.expires_days)

    base = f"{settings.frontend_url}/public/meetings/{token}"
    body = (
        "Hi {{customer_name}},\n\n"
        "Please pick the time that works best for you (one click):\n\n"
        "  Option 1 → {{option_1_link}}  ({{option_1_text}})\n"
        "  Option 2 → {{option_2_link}}  ({{option_2_text}})\n"
        "  Option 3 → {{option_3_link}}  ({{option_3_text}})\n\n"
        "Prefer to suggest your own slots? Open the form:\n{{form_link}}\n\n"
        "This link expires on {{expires_at}}.\n\nRegards,\nThe Ambifo Team"
    )
    ctx = {
        "customer_name": name,
        "option_1_link": f"{base}/1",
        "option_2_link": f"{base}/2",
        "option_3_link": f"{base}/3",
        "option_1_text": format_dt(payload.option_1_at),
        "option_2_text": format_dt(payload.option_2_at),
        "option_3_text": format_dt(payload.option_3_at),
        "form_link": f"{base}/form",
        "expires_at": format_dt(expires_at),
    }
    send_email_via_engine(recipient, subject, body, ctx, email_type="meeting-availability", customer_id=payload.customer_id)

    req = MeetingAvailabilityRequest(
        token=token,
        customer_id=payload.customer_id,
        recipient_email=recipient,
        subject=subject,
        option_1_at=payload.option_1_at,
        option_2_at=payload.option_2_at,
        option_3_at=payload.option_3_at,
        expires_at=expires_at,
        status="sent",
        created_by=current_user.username,
        created_at=now_utc(),
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return _availability_out(db, req)


@router.get("/availability", response_model=list[AvailabilityOut])
def list_availability(
    customer_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(MeetingAvailabilityRequest)
    if customer_id:
        q = q.filter(MeetingAvailabilityRequest.customer_id == customer_id)
    return [
        _availability_out(db, a)
        for a in q.order_by(MeetingAvailabilityRequest.created_at.desc()).limit(min(limit, 500)).all()
    ]


@router.get("/availability/{request_id}", response_model=AvailabilityOut)
def get_availability(
    request_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    req = db.get(MeetingAvailabilityRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Availability request not found")
    return _availability_out(db, req)


def _availability_out(db: Session, req: MeetingAvailabilityRequest) -> AvailabilityOut:
    customer = db.get(Customer, req.customer_id)
    out = AvailabilityOut.model_validate(req)
    out.customer_name = customer.customer_name or customer.account_name if customer else None
    return out


# ------------------------------------------------------------- public
def _get_public_request(db: Session, token: str) -> MeetingAvailabilityRequest:
    req = db.query(MeetingAvailabilityRequest).filter(MeetingAvailabilityRequest.token == token).first()
    if not req:
        raise HTTPException(status_code=404, detail="Link not found")
    if req.expires_at and req.expires_at < now_utc():
        req.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="This availability link has expired")
    return req


@public_router.get("/availability/{token}", response_model=AvailabilityOut)
def public_availability(token: str, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    return _availability_out(db, req)


@public_router.post("/availability/{token}/select", response_model=AvailabilityOut)
def public_availability_select(token: str, payload: AvailabilitySelectIn, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    if req.status in ("selected", "submitted-form"):
        raise HTTPException(status_code=409, detail="Already responded")
    if payload.option not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="option must be 1, 2 or 3")
    req.selected_option = payload.option
    req.selected_at = now_utc()
    req.status = "selected"
    customer = db.get(Customer, req.customer_id)
    if customer:
        option_dt = [req.option_1_at, req.option_2_at, req.option_3_at][payload.option - 1]
        note = f"[Meeting availability] Selected option {payload.option} ({format_dt(option_dt)})."
        customer.comment = f"{customer.comment or ''}\n{note}".strip()
    db.commit()
    db.refresh(req)
    return _availability_out(db, req)


@public_router.post("/availability/{token}/form", response_model=AvailabilityOut)
def public_availability_form(token: str, payload: AvailabilityFormIn, db: Session = Depends(get_db)):
    req = _get_public_request(db, token)
    if req.status in ("selected", "submitted-form"):
        raise HTTPException(status_code=409, detail="Already responded")
    slots = [payload.option_1_at, payload.option_2_at, payload.option_3_at]
    if len({s.isoformat() for s in slots}) != 3:
        raise HTTPException(status_code=422, detail="The three suggested times must be distinct")
    req.customer_option_1_at = payload.option_1_at
    req.customer_option_2_at = payload.option_2_at
    req.customer_option_3_at = payload.option_3_at
    req.extra_recipients = payload.extra_recipients
    req.customer_note = payload.customer_note
    req.customer_submitted_at = now_utc()
    req.status = "submitted-form"
    customer = db.get(Customer, req.customer_id)
    if customer:
        note = f"[Meeting availability] Submitted custom slots."
        customer.comment = f"{customer.comment or ''}\n{note}".strip()
    db.commit()
    db.refresh(req)
    return _availability_out(db, req)