import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.crm import (
    Customer,
    Lead,
    OpportunityCloudOperator,
    OpportunityFinancial,
    OpportunityHistory,
    OpportunitySegment,
    OpportunityStatus,
    OpportunityUpdateTag,
    PartnerReferenceContact,
)
from ..models.documents import CustomerDiagram, CustomerDocument, CustomerSOW
from ..models.email import EmailLog
from ..models.user import User
from ..schemas.crm import (
    BulkUpdate,
    CloudOperatorOut,
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    FinancialOut,
    FinancialUpdate,
    HistoryCreate,
    HistoryOut,
    SegmentOut,
    StatusOut,
    UpdateTagOut,
)
from ..services.numbering import assign_sr_no

router = APIRouter(prefix="/api", tags=["customers"])

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


def _sync_aws_calculator_background(customer_id: int, link: str, username: str) -> None:
    """Download the AWS Calculator CSV + PDF for a customer in the background
    and attach them to the customer's documents."""
    from ..database import SessionLocal
    from ..routers.documents import aws_calculator_import_sync

    def worker() -> None:
        db = SessionLocal()
        try:
            customer = db.get(Customer, customer_id)
            if customer:
                aws_calculator_import_sync(
                    db, customer, link, username or "system", with_bom=True
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "AWS calculator background sync failed for customer %s", customer_id
            )
        finally:
            db.close()

    threading.Thread(target=worker, name="aws-calc-sync", daemon=True).start()


def history_created(h: OpportunityHistory, customer_id: int, action: str, changes: str,
                    changed_by: str | None, tag: str | None = None, remark: str | None = None):
    h.customer_id = customer_id
    h.action = action
    h.changes_summary = changes
    h.changed_by = changed_by
    h.tag_name = tag
    h.remark = remark
    h.created_at = now()


@router.get("/lookups", response_model=dict)
def get_lookups(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    statuses = db.query(OpportunityStatus).filter(OpportunityStatus.is_active).order_by(OpportunityStatus.name).all()
    segments = db.query(OpportunitySegment).filter(OpportunitySegment.is_active).order_by(OpportunitySegment.name).all()
    clouds = db.query(OpportunityCloudOperator).filter(OpportunityCloudOperator.is_active).order_by(OpportunityCloudOperator.name).all()
    tags = db.query(OpportunityUpdateTag).filter(OpportunityUpdateTag.is_active).order_by(OpportunityUpdateTag.name).all()
    users = db.query(User).order_by(User.username).all()
    return {
        "statuses": [StatusOut.model_validate(s) for s in statuses],
        "segments": [SegmentOut.model_validate(s) for s in segments],
        "cloud_operators": [CloudOperatorOut.model_validate(c) for c in clouds],
        "update_tags": [UpdateTagOut.model_validate(t) for t in tags],
        "users": [{"id": u.id, "username": u.username} for u in users],
    }


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    search: str | None = Query(default=None),
    segment: str | None = Query(default=None),
    deal_status: str | None = Query(default=None),
    assignee_id: int | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(Customer)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.customer_name.ilike(like),
                Customer.account_name.ilike(like),
                Customer.email.ilike(like),
                Customer.city.ilike(like),
                Customer.opportunity_id.ilike(like),
            )
        )
    if segment:
        q = q.filter(Customer.segment == segment)
    if deal_status:
        q = q.filter(Customer.deal_status == deal_status)
    if assignee_id:
        q = q.filter(Customer.assign_to_user_id == assignee_id)
    # Default to newest Sr. No. first so paging stays coherent with the UI sort
    # (unnumbered legacy rows sink to the bottom).
    q = q.order_by(Customer.sr_no.desc().nullslast(), Customer.id.desc()).limit(limit).offset(offset)
    return q.all()


@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    exists = db.query(Customer).filter(Customer.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=409, detail="Customer with this email already exists")
    customer = Customer(**payload.model_dump())
    assign_sr_no(db, customer)
    db.add(customer)
    db.flush()
    history_created(OpportunityHistory(), customer.id, "created",
                    f"Customer {payload.customer_name} created", current_user.username)
    db.commit()
    db.refresh(customer)

    link = payload.aws_calculator_link
    if link and link.strip():
        _sync_aws_calculator_background(customer.id, link.strip(), current_user.username)

    return customer


@router.get("/customers/stats")
def customers_stats(
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(Customer)
    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Customer.customer_name.ilike(like),
                Customer.account_name.ilike(like),
                Customer.email.ilike(like),
                Customer.city.ilike(like),
                Customer.opportunity_id.ilike(like),
            )
        )
    all_rows = q.all()
    total = len(all_rows)
    open_count = sum(1 for c in all_rows if c.deal_status not in (None, "Won", "Lost"))
    won_count = sum(1 for c in all_rows if c.deal_status == "Won")
    lost_count = sum(1 for c in all_rows if c.deal_status == "Lost")
    segments = {c.segment for c in all_rows if c.segment}
    clouds = {c.cloud for c in all_rows if c.cloud}
    return {
        "total": total,
        "open": open_count,
        "won": won_count,
        "lost": lost_count,
        "segments": len(segments),
        "clouds": len(clouds),
    }


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    prev_status = customer.deal_status
    prev_segment = customer.segment
    prev_link = customer.aws_calculator_link
    data = payload.model_dump(exclude_unset=True)
    changed = []
    for field, value in data.items():
        current = getattr(customer, field)
        if value != current:
            if field in ("email", "customer_name", "phone"):
                changed.append(f"{field}: {current or ''} -> {value or ''}")
    for field, value in data.items():
        setattr(customer, field, value)
    if prev_status != customer.deal_status:
        changed.append(f"deal_status: {prev_status or ''} -> {customer.deal_status or ''}")
    if prev_segment != customer.segment:
        changed.append(f"segment: {prev_segment or ''} -> {customer.segment or ''}")
    summary = "; ".join(changed) if changed else "No field changes"
    db.flush()
    history_created(OpportunityHistory(), customer.id, "updated", summary,
                    current_user.username, tag="update")
    db.commit()
    db.refresh(customer)

    new_link = (data.get("aws_calculator_link") or "").strip()
    if new_link and new_link != (prev_link or "").strip():
        _sync_aws_calculator_background(customer.id, new_link, current_user.username)

    return customer


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.query(EmailLog).filter(EmailLog.customer_id == customer_id).update(
        {EmailLog.customer_id: None}
    )
    db.query(Lead).filter(Lead.converted_customer_id == customer_id).update(
        {Lead.converted_customer_id: None}
    )
    db.query(PartnerReferenceContact).filter(
        PartnerReferenceContact.customer_id == customer_id
    ).update({PartnerReferenceContact.customer_id: None})

    # Cascade cleanup for related records
    from ..models.gathering import (
        GatheringRequest,
    )
    from ..models.meetings import MeetingAvailabilityRequest, MeetingInvite

    for model in (CustomerDiagram, CustomerDocument, CustomerSOW, OpportunityHistory):
        db.query(model).filter(model.customer_id == customer_id).delete(synchronize_session=False)

    db.query(GatheringRequest).filter(GatheringRequest.customer_id == customer_id).delete(synchronize_session=False)
    db.query(MeetingInvite).filter(MeetingInvite.customer_id == customer_id).delete(synchronize_session=False)
    db.query(MeetingAvailabilityRequest).filter(MeetingAvailabilityRequest.customer_id == customer_id).delete(synchronize_session=False)

    db.delete(customer)
    db.commit()


@router.delete("/customers", status_code=status.HTTP_200_OK)
def delete_all_customers(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from ..models.gathering import (
        GatheringBlockStorageDetail,
        GatheringFileNasDetail,
        GatheringRequest,
        GatheringServerDetail,
    )
    from ..models.meetings import MeetingAvailabilityRequest, MeetingInvite

    # Detach shared references so related rows survive the sweep
    db.query(EmailLog).filter(EmailLog.customer_id.isnot(None)).update(
        {EmailLog.customer_id: None}, synchronize_session=False
    )
    db.query(Lead).filter(Lead.converted_customer_id.isnot(None)).update(
        {Lead.converted_customer_id: None}, synchronize_session=False
    )
    db.query(PartnerReferenceContact).filter(
        PartnerReferenceContact.customer_id.isnot(None)
    ).update({PartnerReferenceContact.customer_id: None}, synchronize_session=False)
    db.query(OpportunityFinancial).filter(
        OpportunityFinancial.customer_id.isnot(None)
    ).delete(synchronize_session=False)

    # Cascade-cleanup all customer-owned records (children before parents)
    for model in (CustomerDiagram, CustomerDocument, CustomerSOW, OpportunityHistory):
        db.query(model).filter(model.customer_id.isnot(None)).delete(synchronize_session=False)
    for model in (GatheringServerDetail, GatheringBlockStorageDetail, GatheringFileNasDetail):
        db.query(model).delete(synchronize_session=False)
    db.query(GatheringRequest).filter(GatheringRequest.customer_id.isnot(None)).delete(synchronize_session=False)
    db.query(MeetingInvite).filter(MeetingInvite.customer_id.isnot(None)).delete(synchronize_session=False)
    db.query(MeetingAvailabilityRequest).filter(MeetingAvailabilityRequest.customer_id.isnot(None)).delete(synchronize_session=False)

    deleted = db.query(Customer).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


@router.get("/customers/{customer_id}/history", response_model=list[HistoryOut])
def get_customer_history(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")

    history = db.query(OpportunityHistory).filter(OpportunityHistory.customer_id == customer_id).all()
    email_logs = db.query(EmailLog).filter(EmailLog.customer_id == customer_id).all()

    merged: list[HistoryOut] = []
    for h in history:
        merged.append(HistoryOut.model_validate(h))
    for log in email_logs:
        status_label = getattr(log, "status", None) or "unknown"
        merged.append(HistoryOut(
            id=-(log.id or 0),
            customer_id=customer_id,
            changed_by=None,
            action=f"email-{log.email_type or 'general'}",
            tag_name="email",
            changes_summary=(
                f"{log.email_type or 'email'} to {log.recipient_email or '—'}:"
                f" {log.subject or ''} ({status_label})"
            ),
            remark=log.error_message,
            created_at=log.created_at,
        ))

    merged.sort(key=lambda x: x.created_at, reverse=True)
    return merged[:200]


@router.post("/customers/{customer_id}/history", response_model=HistoryOut,
             status_code=status.HTTP_201_CREATED)
def add_customer_history(
    customer_id: int,
    payload: HistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    h = OpportunityHistory()
    history_created(h, customer_id, payload.action, payload.changes_summary,
                    current_user.username, tag=payload.tag_name, remark=payload.remark)
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


@router.post("/customers/bulk/update", status_code=status.HTTP_200_OK)
def bulk_update_customers(
    payload: BulkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Customer)
    if any([payload.filter_search, payload.filter_segment, payload.filter_deal_status]):
        if payload.filter_search:
            like = f"%{payload.filter_search}%"
            q = q.filter(
                or_(
                    Customer.customer_name.ilike(like),
                    Customer.account_name.ilike(like),
                    Customer.email.ilike(like),
                    Customer.city.ilike(like),
                    Customer.opportunity_id.ilike(like),
                )
            )
        if payload.filter_segment:
            q = q.filter(Customer.segment == payload.filter_segment)
        if payload.filter_deal_status:
            q = q.filter(Customer.deal_status == payload.filter_deal_status)
    else:
        q = q.filter(Customer.id.in_(payload.customer_ids))
    customers = q.all()
    for c in customers:
        if payload.deal_status is not None and payload.deal_status != c.deal_status:
            history_created(OpportunityHistory(), c.id, "bulk_status",
                            f"Status set to {payload.deal_status}", current_user.username)
            c.deal_status = payload.deal_status
        if payload.segment is not None and payload.segment != c.segment:
            history_created(OpportunityHistory(), c.id, "bulk_segment",
                            f"Segment set to {payload.segment}", current_user.username)
            c.segment = payload.segment
        if payload.assign_to_user_id is not None:
            history_created(OpportunityHistory(), c.id, "bulk_assign",
                            f"Assigned to user {payload.assign_to_user_id}", current_user.username)
            c.assign_to_user_id = payload.assign_to_user_id
    db.commit()
    return {"updated": len(customers)}


@router.get("/customers/{customer_id}/financials", response_model=FinancialOut)
def get_financials(
    customer_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    financial = (
        db.query(OpportunityFinancial)
        .filter(OpportunityFinancial.customer_id == customer_id)
        .first()
    )
    if not financial:
        financial = OpportunityFinancial(customer_id=customer_id)
        db.add(financial)
        db.commit()
        db.refresh(financial)
    return financial


@router.put("/customers/{customer_id}/financials", response_model=FinancialOut)
def update_financials(
    customer_id: int,
    payload: FinancialUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    financial = (
        db.query(OpportunityFinancial)
        .filter(OpportunityFinancial.customer_id == customer_id)
        .first()
    )
    if not financial:
        financial = OpportunityFinancial(customer_id=customer_id)
        db.add(financial)
    data = payload.model_dump(exclude_unset=True)
    labels = {
        "expected_mrr": "Expected MRR",
        "expected_arr": "Expected ARR",
        "actual_mrr": "Actual MRR",
        "actual_arr": "Actual ARR",
        "expected_credit_customer": "Expected credit (customer)",
        "expected_credit_ambifo": "Expected credit (Ambifo)",
        "actual_credit_customer": "Actual credit (customer)",
        "actual_credit_ambifo": "Actual credit (Ambifo)",
        "credits_requested": "Credits requested",
        "credits_gets": "Credits gets",
        "phases_to_distribute": "Phases to distribute",
    }
    changed = []
    for field, value in data.items():
        current = getattr(financial, field)
        if value != current:
            changed.append(f"{labels.get(field, field)}: {current or ''} -> {value or ''}")
    for field, value in data.items():
        setattr(financial, field, value)
    if changed:
        h = OpportunityHistory()
        history_created(h, customer_id, "update", "; ".join(changed),
                        current_user.username, tag="financials")
        db.add(h)
    db.commit()
    db.refresh(financial)
    return financial