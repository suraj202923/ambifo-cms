from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer, OpportunityFinancial, OpportunityHistory, Lead, OpportunityStatus
from ..models.user import User
from ..schemas.dashboard import DashboardOut, AssigneeCount, DashboardKPIs, SegmentCount, StatusCount

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

OPEN_STATUSES = {"new", "qualified", "proposal", "negotiation"}


@router.get("", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total_customers = db.query(Customer).count()
    total_leads = db.query(Lead).filter(Lead.is_active.is_(True)).count()
    open_opps = (
        db.query(Customer)
        .filter(
            Customer.deal_status.isnot(None),
            func.lower(Customer.deal_status).in_(OPEN_STATUSES),
        )
        .count()
    )
    total_mrr = (
        db.query(func.coalesce(func.sum(OpportunityFinancial.actual_mrr), 0.0))
        .scalar()
        or 0.0
    )
    total_arr = (
        db.query(func.coalesce(func.sum(OpportunityFinancial.actual_arr), 0.0))
        .scalar()
        or 0.0
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    added_30d = db.query(Customer).filter(Customer.created_at >= cutoff).count()

    seeded = db.query(OpportunityStatus).all()
    status_map = {s.name: s.color for s in seeded}
    statuses = (
        db.query(Customer.deal_status, func.count(Customer.id))
        .group_by(Customer.deal_status)
        .all()
    )
    status_count_map = {name or "unset": count for name, count in statuses}
    by_status = [
        StatusCount(
            name=s.name,
            color=status_map.get(s.name, "#8a8f98"),
            count=status_count_map.get(s.name, 0),
        )
        for s in seeded
    ]

    by_segment = [
        SegmentCount(name=name or "unset", count=count)
        for name, count in (
            db.query(Customer.segment, func.count(Customer.id))
            .group_by(Customer.segment)
            .all()
        )
    ]

    by_assignee = [
        AssigneeCount(name=name or "unassigned", count=count)
        for name, count in (
            db.query(User.username, func.count(Customer.id))
            .join(Customer, Customer.assign_to_user_id == User.id)
            .group_by(User.username)
            .all()
        )
    ]

    recent = (
        db.query(OpportunityHistory)
        .order_by(OpportunityHistory.created_at.desc())
        .limit(10)
        .all()
    )
    recent_history = [
        {
            "id": h.id,
            "customer_id": h.customer_id,
            "changed_by": h.changed_by,
            "action": h.action,
            "tag_name": h.tag_name,
            "changes_summary": h.changes_summary,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in recent
    ]

    month_cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    month_rows = (
        db.query(
            func.to_char(func.date_trunc("month", Customer.created_at), "YYYY-MM").label("month"),
            func.count(Customer.id),
        )
        .filter(Customer.created_at >= month_cutoff)
        .group_by("month")
        .all()
    )
    month_count_map = {month: count for month, count in month_rows}
    opportunities_by_month: list[dict] = []
    year, month = month_cutoff.year, month_cutoff.month
    for _ in range(12):
        key = f"{year:04d}-{month:02d}"
        opportunities_by_month.append({"month": key, "count": month_count_map.get(key, 0)})
        month += 1
        if month > 12:
            month = 1
            year += 1

    return DashboardOut(
        kpis=DashboardKPIs(
            total_customers=total_customers,
            total_leads=total_leads,
            open_opportunities=open_opps,
            total_mrr=float(total_mrr),
            total_arr=float(total_arr),
            customers_added_30d=added_30d,
        ),
        by_status=by_status,
        by_segment=by_segment,
        by_assignee=by_assignee,
        recent_history=recent_history,
        opportunities_by_month=opportunities_by_month,
    )