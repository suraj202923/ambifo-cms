import re
from datetime import datetime, timezone

from ..models.email import EmailLog

MACRO_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def render_macros(text: str, context: dict) -> str:
    """Replace {{key}} placeholders (like the legacy macro engine)."""

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        return str(context.get(key, "") or "")

    return MACRO_RE.sub(_replace, text)


def format_dt(value: datetime | None) -> str:
    if not value:
        return "—"
    return value.isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_email(
    recipient_email: str,
    subject: str,
    body: str,
    context: dict | None = None,
    email_type: str = "general",
    customer_id: int | None = None,
    template_id: int | None = None,
    cc_emails: list[str] | None = None,
) -> EmailLog:
    """Write a queued EmailLog row; the mail worker delivers it via SMTP."""
    from ..database import SessionLocal

    ctx = context or {}
    final_subject = render_macros(subject, ctx)
    final_body = render_macros(body, ctx)

    db = SessionLocal()
    try:
        log = EmailLog(
            customer_id=customer_id,
            template_id=template_id,
            recipient_email=recipient_email,
            cc_emails=", ".join(e for e in (cc_emails or []) if e) or None,
            email_type=email_type,
            subject=final_subject,
            body=final_body,
            status="queued",
            queue_status="queued",
            error_message=None,
            retry_count=0,
            created_at=now_utc(),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
    finally:
        db.close()


def send_email_via_engine(
    recipient_email: str,
    subject: str,
    body: str,
    context: dict | None = None,
    from_email: str | None = None,
    email_type: str = "general",
    customer_id: int | None = None,
) -> int:
    """Backward-compatible helper. Now enqueues a real (worker-delivered) email."""
    log = enqueue_email(recipient_email, subject, body, context, email_type=email_type, customer_id=customer_id)
    return log.id