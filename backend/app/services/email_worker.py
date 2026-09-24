import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func

from ..database import SessionLocal
from ..models.crm import Lead
from ..models.email import EmailBulkCsvExecution, EmailLog
from .email_sender import send_html_email

logger = logging.getLogger(__name__)

PENDING_QUEUE_STATUSES = ("queued", "bulk", "bulk_retry")

QUEUED_STATUS = "queued"

MAX_RETRIES = 3


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_pending(db, session_factory=SessionLocal) -> int:
    """Migrate legacy fake-'accepted' rows into the real queued pipeline."""
    rows = db.query(EmailLog).filter(EmailLog.status == "accepted").all()
    for row in rows:
        row.status = QUEUED_STATUS
        if row.queue_status not in PENDING_QUEUE_STATUSES:
            row.queue_status = "queued"
    db.commit()
    return len(rows)


def _split_emails(value: str | None) -> list[str]:
    if not value:
        return []
    return [e.strip() for e in value.split(",") if e.strip()]


def process_one(db) -> EmailLog | None:
    log = (
        db.query(EmailLog)
        .filter(
            EmailLog.status == QUEUED_STATUS,
            EmailLog.queue_status.in_(PENDING_QUEUE_STATUSES),
        )
        .order_by(EmailLog.created_at.asc())
        .first()
    )
    if not log:
        return None

    log.status = "processing"
    db.commit()
    db.refresh(log)

    result = send_html_email(
        db,
        log.recipient_email,
        log.subject,
        log.body,
        cc_emails=_split_emails(log.cc_emails),
        bcc_emails=_split_emails(log.bcc_emails),
    )

    log.status = result.status
    log.error_message = None if result.success else (result.error or "send failed")
    db.commit()

    _post_touch(db, log)
    return log


def _post_touch(db, log: EmailLog) -> None:
    recipient = (log.recipient_email or "").strip().lower()
    if recipient:
        lead = (
            db.query(Lead)
            .filter(func.lower(Lead.email) == recipient)
            .order_by(Lead.id.desc())
            .first()
        )
        if lead:
            lead.last_emailed_at = now()
            lead.last_email_status = log.status

    if log.csv_execution_id:
        execution = db.get(EmailBulkCsvExecution, log.csv_execution_id)
        if execution:
            if log.status == "sent":
                execution.sent_rows += 1
            elif log.status == "failed":
                execution.failed_rows += 1
    db.commit()


SEND_GAP_SECONDS = 1.0


def worker_once(db, max_jobs: int = 100) -> int:
    normalize_pending(db)
    processed = 0
    while processed < max_jobs:
        log = process_one(db)
        if log is None:
            break
        processed += 1
        if processed < max_jobs:
            time.sleep(SEND_GAP_SECONDS)
    return processed


def run_worker_forever(poll_interval: float = 0.2) -> None:
    logger.info("[email-worker] started (poll %ss, send gap %ss)", poll_interval, SEND_GAP_SECONDS)
    while True:
        db = SessionLocal()
        try:
            processed = worker_once(db)
            if processed:
                logger.info("[email-worker] processed %d queued email(s)", processed)
        except KeyboardInterrupt:
            logger.info("[email-worker] stopped")
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("[email-worker] error: %s", exc)
        finally:
            db.close()
        time.sleep(poll_interval)


if __name__ == "__main__":
    run_worker_forever()