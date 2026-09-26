"""Sequential "Sr. No." allocation for the opportunity (customer) list.

Numbers are handed out in creation order and are never reused, so the list can be
sorted descending (newest first) without depending on any other column. The
value is server-assigned only: it is not part of CustomerBase/CustomerUpdate and
so can never be set through the API.
"""

import logging

from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.crm import Customer

logger = logging.getLogger(__name__)

# Transaction-scoped advisory lock (distinct from the startup lock in app.main)
# so the read-then-increment below cannot hand the same number to two
# concurrent creates.
_ADVISORY_LOCK_KEY = 746202


def next_sr_no(db: Session) -> int:
    """Return the next unused Sr. No. (current max + 1)."""
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
    except SQLAlchemyError:
        # Non-Postgres backend: the lock is a nicety, fall back to max + 1 and
        # accept the small race between concurrent creates.
        logger.debug("advisory lock unavailable for sr_no allocation", exc_info=True)
    current = db.query(func.max(Customer.sr_no)).scalar()
    return (current or 0) + 1


def assign_sr_no(db: Session, customer: Customer) -> int:
    """Stamp a freshly built Customer with its Sr. No. (not yet flushed)."""
    customer.sr_no = next_sr_no(db)
    return customer.sr_no


def backfill_sr_no(db: Session) -> int:
    """Number any legacy customer that predates the column. Idempotent.

    Existing rows are numbered in id (creation) order, continuing from the
    highest number already present, so nothing is renumbered and the next
    create keeps going to the end of the sequence.
    """
    unnumbered = [
        row[0]
        for row in db.query(Customer.id)
        .filter(Customer.sr_no.is_(None))
        .order_by(Customer.id.asc())
        .all()
    ]
    if not unnumbered:
        return 0
    highest = db.query(func.max(Customer.sr_no)).scalar() or 0
    for offset, customer_id in enumerate(unnumbered, start=1):
        db.execute(
            Customer.__table__.update()
            .where(Customer.id == customer_id)
            .values(sr_no=highest + offset)
        )
    db.commit()
    logger.info("backfilled sr_no for %d existing customers", len(unnumbered))
    return len(unnumbered)
