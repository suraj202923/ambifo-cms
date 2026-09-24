import csv
import io
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import dns.resolver
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models.crm import Customer, Lead
from ..models.email import (
    EmailBulkCsvExecution,
    EmailLog,
    EmailTemplate,
    EmailUnsubscribe,
)
from ..models.user import User
from ..schemas.engine import (
    EmailBulkResultOut,
    EmailBulkSendIn,
    EmailCsvExecutionOut,
    EmailCsvResultOut,
    EmailLogOut,
    EmailLogPageOut,
    EmailSendIn,
    EmailSendOut,
    EmailSettingsOut,
    EmailSettingsUpdate,
    EmailTestIn,
    EmailTestResult,
    EmailTestTemplateIn,
    EmailTemplateCreate,
    EmailTemplateOut,
    EmailTemplateUpdate,
    EmailUnsubOut,
    EmailUnsubPageOut,
    EmailLogStatsOut,
)
from ..services.email_sender import (
    is_unsubscribed,
    resolve_unsubscribe_token,
    send_html_email,
)
from ..services.engine_client import engine_client
from ..services.messaging import render_macros
from ..services.settings import (
    get_app_base_url,
    get_smtp_settings,
    save_smtp_settings,
    set_setting,
)

router = APIRouter(prefix="/api/email", tags=["email"])
public_router = APIRouter(prefix="/api/public/email", tags=["public-email"])

CSV_DIR = Path(settings.email_csv_dir)
CSV_DIR.mkdir(parents=True, exist_ok=True)

_MX_CACHE: dict[str, bool] = {}


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ templates
SYSTEM_TEMPLATES = [
    {
        "name": "System - SMTP Test Email",
        "subject_template": "Ambifo CRM SMTP Test - {{today}}",
        "body_template": "Hi,\n\nThis is a test email from Ambifo CRM. If you received this, your SMTP settings are correctly configured.\n\nRegards,\nThe Ambifo Team",
    },
    {
        "name": "System - Welcome Email",
        "subject_template": "Welcome to Ambifo, {{customer_name}}!",
        "body_template": "Hi {{customer_name}},\n\nWelcome to Ambifo Cloud. We're excited to help you get the most out of your cloud investment.\n\nBest,\nThe Ambifo Team",
    },
    {
        "name": "System - Gathering Information Request",
        "subject_template": "Ambifo - Gathering Sheet & Information Request",
        "body_template": "Hi {{customer_name}},\n\nUse the link below to share your current infrastructure with us.\n{{gathering_form_link}}\n\n{{access_key_block}}{{note_block}}This link expires on {{expires_at}}.\n\nRegards,\nThe Ambifo Team",
    },
    {
        "name": "System - Meeting Availability Request",
        "subject_template": "Ambifo Meeting - Pick a time",
        "body_template": "Hi {{customer_name}},\n\nPlease pick a convenient time for our meeting:\n{{meeting_availability_link}}\n\nRegards,\nThe Ambifo Team",
    },
    {
        "name": "System - SOW Document Email",
        "subject_template": "Ambifo - Statement of Work (SOW)",
        "body_template": "Hi {{customer_name}},\n\nPlease find the Statement of Work attached for your review.\n\nRegards,\nThe Ambifo Team",
    },
    {
        "name": "System - Demo Follow Up",
        "subject_template": "Thanks for the demo, {{customer_name}}",
        "body_template": "Hi {{customer_name}},\n\nThanks for your time during the demo. Next steps are attached.\n\nRegards,\nThe Ambifo Team",
    },
]
PROTECTED_TEMPLATES = {t["name"] for t in SYSTEM_TEMPLATES}

DEFAULT_TEMPLATES = [
    {
        "name": "welcome",
        "subject_template": "Welcome to Ambifo, {{customer_name}}!",
        "body_template": "Hi {{customer_name}},\n\nWelcome to Ambifo Cloud. We're ready to help you optimize.\n\nBest,\nThe Ambifo Team",
    },
    {
        "name": "demo_followup",
        "subject_template": "Thanks for the demo, {{customer_name}}",
        "body_template": "Hi {{customer_name}},\n\nThanks for your time during the demo. Next steps are attached.\n\nRegards,\nAmbifo",
    },
]


def get_system_template(db: Session, name: str) -> EmailTemplate | None:
    return db.query(EmailTemplate).filter(EmailTemplate.name == name).first()


def seed_default_templates(db: Session) -> None:
    for t in [*DEFAULT_TEMPLATES, *SYSTEM_TEMPLATES]:
        if not db.query(EmailTemplate).filter(EmailTemplate.name == t["name"]).first():
            db.add(EmailTemplate(
                name=t["name"],
                subject_template=t["subject_template"],
                body_template=t["body_template"],
                is_active=True,
                created_at=now(),
            ))
    db.commit()


def is_protected(name: str) -> bool:
    return name in PROTECTED_TEMPLATES


@router.get("/templates", response_model=list[EmailTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    seed_default_templates(db)
    rows = db.query(EmailTemplate).order_by(EmailTemplate.name).all()
    for row in rows:
        row.is_system = is_protected(row.name)
    return rows


@router.post("/templates", response_model=EmailTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: EmailTemplateCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    seed_default_templates(db)
    if is_protected(payload.name):
        raise HTTPException(status_code=400, detail="This is a system template name and cannot be reused")
    exists = db.query(EmailTemplate).filter(EmailTemplate.name == payload.name).first()
    if exists:
        raise HTTPException(status_code=409, detail="Template name already exists")
    template = EmailTemplate(**payload.model_dump(), created_at=now())
    db.add(template)
    db.commit()
    db.refresh(template)
    template.is_system = is_protected(template.name)
    return template


@router.put("/templates/{template_id}", response_model=EmailTemplateOut)
def update_template(
    template_id: int,
    payload: EmailTemplateUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    template.is_system = is_protected(template.name)
    return template


@router.delete("/templates", status_code=status.HTTP_200_OK)
def remove_all_templates(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    db.query(EmailLog).filter(EmailLog.template_id.isnot(None)).update(
        {EmailLog.template_id: None}, synchronize_session=False
    )
    db.query(EmailBulkCsvExecution).filter(EmailBulkCsvExecution.template_id.isnot(None)).update(
        {EmailBulkCsvExecution.template_id: None}, synchronize_session=False
    )
    count = db.query(EmailTemplate).delete()
    db.commit()
    return {"deleted": count}


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if is_protected(template.name):
        raise HTTPException(status_code=400, detail="System templates cannot be deleted")
    db.query(EmailLog).filter(EmailLog.template_id == template_id).update(
        {EmailLog.template_id: None}, synchronize_session=False
    )
    db.query(EmailBulkCsvExecution).filter(EmailBulkCsvExecution.template_id == template_id).update(
        {EmailBulkCsvExecution.template_id: None}, synchronize_session=False
    )
    db.delete(template)
    db.commit()


# ------------------------------------------------------------------ context helpers
CUSTOMER_MACRO_FIELDS = [
    "customer_name", "account_name", "designation", "email", "alternate_emails",
    "phone", "cloud", "main_page_address", "billing", "city", "aws_id",
    "aws_calculator_link", "opportunity_id", "segment", "deal_status", "comment",
    "next_action_planned",
]

LEAD_MACRO_FIELDS = ["lead_name", "email", "phone", "company", "city", "source", "lead_status"]


def _pick(obj, field: str) -> str:
    value = getattr(obj, field, None)
    if value is None:
        return ""
    return str(value)


def customer_context(customer: Customer | None) -> dict:
    ctx = {field: _pick(customer, field) for field in CUSTOMER_MACRO_FIELDS}
    ctx["today"] = now().strftime("%B %d, %Y")
    return ctx


def lead_context(lead: Lead | None) -> dict:
    ctx = {field: _pick(lead, field) for field in LEAD_MACRO_FIELDS}
    ctx["customer_name"] = _pick(lead, "lead_name")
    ctx["today"] = now().strftime("%B %d, %Y")
    return ctx


def render_template(text: str, context: dict) -> str:
    try:
        return engine_client.render_template(text, context)
    except Exception:  # noqa: BLE001 - fall back to local macro renderer
        return render_macros(text, context)


def _resolve_email_content(payload, db: Session) -> tuple[str, str]:
    subject = payload.subject
    body = payload.body
    if payload.template_id:
        template = db.get(EmailTemplate, payload.template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        subject = template.subject_template if not subject else subject
        body = template.body_template if not body else body
    if not subject or not body:
        raise HTTPException(status_code=422, detail="Provide subject+body or a template_id")
    return subject, body


def _alternate_emails(customer: Customer | None) -> list[str]:
    if not customer or not customer.alternate_emails:
        return []
    parts = re.split(r"[,\n;]+", customer.alternate_emails or "")
    return [p.strip() for p in parts if p.strip()]


def _record_history(db: Session, customer_id: int, subject: str, recipient: str, changed_by: str) -> None:
    from .customers import history_created
    from ..models.crm import OpportunityHistory
    hist = OpportunityHistory()
    history_created(hist, customer_id, "email", f"Sent '{subject}' to {recipient}", changed_by, tag="email")
    db.add(hist)
    db.commit()


# ------------------------------------------------------------- render
@router.post("/render")
def render_email(
    payload: EmailSendIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    subject, body = _resolve_email_content(payload, db)
    context = payload.context or {}
    if payload.customer_id:
        context = {**customer_context(db.get(Customer, payload.customer_id)), **context}
    subject = render_template(subject, context)
    body = render_template(body, context)
    return {"subject": subject, "body": body}


# ------------------------------------------------------------- single send
@router.post("/send", response_model=EmailSendOut, status_code=status.HTTP_201_CREATED)
def send_email(
    payload: EmailSendIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subject, body = _resolve_email_content(payload, db)
    context = payload.context or {}
    customer = db.get(Customer, payload.customer_id) if payload.customer_id else None
    if customer:
        context = {**customer_context(customer), **context}

    subject = render_template(subject, context)
    body = render_template(body, context)

    cc: list[str] = [str(e) for e in (payload.cc_emails or [])]
    if payload.include_alternate_cc and customer:
        cc.extend(_alternate_emails(customer))
    cc = list(dict.fromkeys(cc))

    log = EmailLog(
        customer_id=payload.customer_id,
        template_id=payload.template_id,
        recipient_email=str(payload.recipient_email),
        cc_emails=", ".join(cc) or None,
        email_type=payload.email_type,
        subject=subject,
        body=body,
        status="queued",
        queue_status="queued",
        error_message=None,
        retry_count=0,
        created_at=now(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    if payload.customer_id:
        _record_history(db, payload.customer_id, subject, str(payload.recipient_email), current_user.username)

    return log


# ------------------------------------------------------------- settings
@router.get("/settings", response_model=EmailSettingsOut)
def get_email_settings(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    smtp = get_smtp_settings(db)
    return EmailSettingsOut(
        smtp_host=smtp["smtp_host"],
        smtp_port=int(smtp["smtp_port"]),
        smtp_username=smtp["smtp_username"],
        smtp_use_tls=bool(smtp["smtp_use_tls"]),
        smtp_mail_from=smtp["smtp_mail_from"],
        smtp_password_set=bool(smtp["smtp_password"]),
        app_base_url=get_app_base_url(db),
    )


@router.put("/settings", response_model=EmailSettingsOut)
def update_email_settings(
    payload: EmailSettingsUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("smtp_password", None)
    app_base_url = data.pop("app_base_url", None)
    if data:
        save_smtp_settings(db, data)
    if password:
        set_setting(db, "smtp.password", password)
    if app_base_url is not None:
        set_setting(db, "app.base_url", app_base_url)
    return get_email_settings(db)


@router.post("/settings/test", response_model=EmailTestResult)
def test_smtp_settings(
    payload: EmailTestIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = get_system_template(db, "System - SMTP Test Email")
    context = {"today": now().strftime("%B %d, %Y")}
    subject = render_template(template.subject_template, context) if template else "Ambifo CRM SMTP Test"
    body = render_template(template.body_template, context) if template else (
        "This is a test email from Ambifo CRM. If you received this, your SMTP settings are correct."
    )
    result = send_html_email(db, str(payload.to_email), subject, body)
    log = EmailLog(
        customer_id=None,
        template_id=template.id if template else None,
        recipient_email=str(payload.to_email),
        email_type="smtp-test",
        subject=subject,
        body=body,
        status=result.status,
        queue_status="sync",
        error_message=result.error,
        retry_count=0,
        created_at=now(),
    )
    db.add(log)
    db.commit()
    return EmailTestResult(ok=result.success, status=result.status, error=result.error)


@router.post("/settings/test-template", response_model=EmailTestResult)
def test_template_email(
    payload: EmailTestTemplateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = db.get(EmailTemplate, payload.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    context = payload.context or {}
    if payload.customer_id:
        context = {**customer_context(db.get(Customer, payload.customer_id)), **context}
    subject = render_template(template.subject_template, context)
    body = render_template(template.body_template, context)
    result = send_html_email(db, str(payload.to_email), subject, body)
    log = EmailLog(
        customer_id=payload.customer_id,
        template_id=template.id,
        recipient_email=str(payload.to_email),
        email_type="template-test",
        subject=subject,
        body=body,
        status=result.status,
        queue_status="sync",
        error_message=result.error,
        retry_count=0,
        created_at=now(),
    )
    db.add(log)
    db.commit()
    return EmailTestResult(ok=result.success, status=result.status, error=result.error)


@router.get("/stats", response_model=EmailLogStatsOut)
def email_log_stats(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = (
        db.query(EmailLog.status, func.count(EmailLog.id))
        .group_by(EmailLog.status)
        .all()
    )
    counts = {status_: count_ for status_, count_ in rows}

    def c(key: str) -> int:
        return counts.get(key, 0)

    return EmailLogStatsOut(
        total=sum(counts.values()),
        sent=c("sent"),
        dev_mode=c("dev-mode"),
        failed=c("failed"),
        queued=c("queued"),
        processing=c("processing"),
    )


# ------------------------------------------------------------- logs
@router.get("/logs", response_model=EmailLogPageOut)
def list_email_logs(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: int | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = db.query(EmailLog)
    if status_filter:
        query = query.filter(EmailLog.status == status_filter)
    if customer_id:
        query = query.filter(EmailLog.customer_id == customer_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(EmailLog.recipient_email.ilike(like), EmailLog.subject.ilike(like)))
    total = query.count()
    items = (
        query.order_by(EmailLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return EmailLogPageOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/logs/{log_id}", response_model=EmailLogOut)
def get_email_log(
    log_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    log = db.get(EmailLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Email log not found")
    return log


@router.post("/logs/{log_id}/retry", response_model=EmailLogOut)
def retry_email_log(
    log_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    log = db.get(EmailLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Email log not found")
    if log.queue_status == "queued" and log.status == "queued":
        raise HTTPException(status_code=400, detail="Email is already queued")
    log.status = "queued"
    log.queue_status = "queued"
    log.retry_count = (log.retry_count or 0) + 1
    log.error_message = None
    db.commit()
    db.refresh(log)
    return log


@router.post("/logs/{log_id}/resend", response_model=EmailLogOut, status_code=status.HTTP_201_CREATED)
def resend_email_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.get(EmailLog, log_id)
    if not source:
        raise HTTPException(status_code=404, detail="Email log not found")
    log = EmailLog(
        customer_id=source.customer_id,
        template_id=source.template_id,
        recipient_email=source.recipient_email,
        cc_emails=source.cc_emails,
        email_type="resend",
        subject=source.subject,
        body=source.body,
        status="queued",
        queue_status="queued",
        error_message=None,
        retry_count=0,
        created_at=now(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    if source.customer_id:
        _record_history(db, source.customer_id, source.subject, str(source.recipient_email or ""), current_user.username)
    return log


# ------------------------------------------------------------- unsubscribe
@router.get("/unsubscribed", response_model=EmailUnsubPageOut)
def list_unsubscribed(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = db.query(EmailUnsubscribe)
    total = query.count()
    items = query.order_by(EmailUnsubscribe.unsubscribed_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return EmailUnsubPageOut(items=items, total=total, page=page, page_size=page_size)


_UNSUBSCRIBE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Unsubscribed - Ambifo</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}}
.card{{background:#fff;border:1px solid #e7ecf3;border-radius:12px;padding:40px 48px;max-width:440px;text-align:center;box-shadow:0 4px 16px rgba(15,47,95,.08);}}
h1{{font-size:20px;color:#0f2f5f;margin:0 0 8px;}}p{{color:#475569;font-size:14px;line-height:1.6;margin:0;}}
.badge{{display:inline-block;margin-bottom:16px;padding:6px 14px;border-radius:999px;background:#ecf4ff;color:#315b92;font-size:12px;font-weight:700;letter-spacing:.02em;}}
</style></head><body><div class="card">
<div class="badge">AMBIFO TECHNOLOGY PVT LTD</div>
<h1>{heading}</h1><p>{message}</p>
</div></body></html>"""


@public_router.get("/unsubscribe")
def public_unsubscribe(
    token: str = Query(),
    db: Session = Depends(get_db),
):
    email = resolve_unsubscribe_token(token)
    if not email:
        html = _UNSUBSCRIBE_PAGE.format(heading="Invalid unsubscribe link", message="This link is invalid or has expired.")
        return HTMLResponse(html, status_code=400)

    normalized = str(email).lower()
    existing = db.query(EmailUnsubscribe).filter(EmailUnsubscribe.email == normalized).first()
    if not existing:
        db.add(EmailUnsubscribe(email=normalized, source="footer-link", unsubscribed_at=now()))
        db.commit()
        message = f"<b>{escape(normalized)}</b> has been removed from our email list."
    else:
        message = f"<b>{escape(normalized)}</b> was already unsubscribed."
    html = _UNSUBSCRIBE_PAGE.format(heading="You're unsubscribed", message=message)
    return HTMLResponse(html)


# ------------------------------------------------------------- bulk send
def _resolve_recipients(payload: EmailBulkSendIn, db: Session) -> list[dict]:
    """Return [{customer_id, email, context}] tuples for the selected mode."""
    if payload.mode == "manual_emails":
        return [{"customer_id": None, "email": str(e), "context": {"customer_name": str(e)}} for e in payload.manual_emails]

    if payload.mode == "all_leads":
        q = db.query(Lead).filter(Lead.email.isnot(None), Lead.is_active == True)  # noqa: E712
        if payload.lead_send_state == "emailed":
            q = q.filter(Lead.last_email_status == "sent")
        elif payload.lead_send_state == "not_emailed":
            q = q.filter(or_(Lead.last_email_status.is_(None), Lead.last_email_status != "sent"))
        return [{"customer_id": None, "email": l.email, "context": lead_context(l)} for l in q]

    if payload.mode == "select_customers":
        if not payload.customer_ids:
            raise HTTPException(status_code=422, detail="customer_ids required for select_customers")
        q = db.query(Customer).filter(Customer.id.in_(payload.customer_ids), Customer.email.isnot(None))
        return [{"customer_id": c.id, "email": c.email, "context": customer_context(c)} for c in q]

    q = db.query(Customer).filter(Customer.email.isnot(None))
    if payload.mode == "customers_by_status":
        if not payload.filter_value:
            raise HTTPException(status_code=422, detail="filter_value required for customers_by_status")
        q = q.filter(Customer.deal_status == payload.filter_value)
    elif payload.mode == "customers_by_segment":
        if not payload.filter_value:
            raise HTTPException(status_code=422, detail="filter_value required for customers_by_segment")
        q = q.filter(Customer.segment == payload.filter_value)
    return [{"customer_id": c.id, "email": c.email, "context": customer_context(c)} for c in q]


@router.post("/bulk", response_model=EmailBulkResultOut, status_code=status.HTTP_201_CREATED)
def send_bulk_email(
    payload: EmailBulkSendIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subject, body = _resolve_email_content(payload, db)
    recipients = _resolve_recipients(payload, db)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients matched the selection")

    errors: list[str] = []
    logs: list[EmailLog] = []
    queued = 0
    for item in recipients:
        ctx = {**item["context"], **payload.context}
        try:
            subj = render_template(subject, ctx)
            rend_body = render_template(body, ctx)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{item['email']}: render failed ({exc})")
            continue

        cc: list[str] = []
        if payload.include_alternate_cc and item["customer_id"]:
            customer = db.get(Customer, item["customer_id"])
            cc = _alternate_emails(customer)

        log = EmailLog(
            customer_id=item["customer_id"],
            template_id=payload.template_id,
            recipient_email=item["email"],
            cc_emails=", ".join(cc) or None,
            email_type=payload.email_type,
            subject=subj,
            body=rend_body,
            status="queued",
            queue_status="bulk",
            error_message=None,
            retry_count=0,
            created_at=now(),
        )
        logs.append(log)
        queued += 1

    db.add_all(logs)
    db.commit()

    return EmailBulkResultOut(
        mode=payload.mode,
        attempted=len(recipients),
        queued=queued,
        failed=len(recipients) - queued,
        errors=errors[:25],
    )


@router.post("/bulk/retry-failed", response_model=EmailBulkResultOut)
def retry_failed_emails(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    failed: list[EmailLog] = (
        db.query(EmailLog)
        .filter(EmailLog.status == "failed")
        .order_by(EmailLog.created_at)
        .all()
    )
    if not failed:
        raise HTTPException(status_code=400, detail="No failed emails to retry")
    for log in failed:
        log.status = "queued"
        log.queue_status = "bulk_retry"
        log.retry_count = (log.retry_count or 0) + 1
        log.error_message = None
    db.commit()
    return EmailBulkResultOut(
        mode="retry_failed",
        attempted=len(failed),
        queued=len(failed),
        failed=0,
        errors=[],
    )


# ------------------------------------------------------------- bulk CSV
def _validate_email_reachable(email: str) -> tuple[str | None, str | None]:
    try:
        valid = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        return None, f"invalid email ({exc})"
    domain = valid.split("@")[1].lower()
    if _MX_CACHE.get(domain) is False:
        return None, f"no MX record for {domain}"
    if domain in _MX_CACHE:
        return valid, None
    try:
        dns.resolver.resolve(domain, "MX", lifetime=2.0)
        _MX_CACHE[domain] = True
        return valid, None
    except Exception:  # noqa: BLE001
        try:
            dns.resolver.resolve(domain, "A", lifetime=2.0)
            _MX_CACHE[domain] = True
            return valid, None
        except Exception:  # noqa: BLE001
            _MX_CACHE[domain] = False
            return None, f"no MX record for {domain}"


def _template_macros(template_text: str) -> list[str]:
    macros = []
    for match in re.finditer(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}", template_text or ""):
        if match.group(1) not in macros:
            macros.append(match.group(1))
    return macros


@router.get("/templates/{template_id}/csv-sample")
def email_csv_sample(
    template_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    macros = _template_macros(f"{template.subject_template}\n{template.body_template}")
    macros = [m for m in macros if m not in ("today",)]
    headers = ["email", *macros]
    row = ["name@example.com", *[f"{{{m}}}" for m in macros]]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerow(row)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="email_template_{template_id}_sample.csv"'},
    )


@router.post("/bulk/csv", response_model=EmailCsvResultOut, status_code=status.HTTP_201_CREATED)
async def send_bulk_csv(
    file: UploadFile = File(...),
    template_id: int = Form(...),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    template = db.get(EmailTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    email_col = next((h for h in headers if h.lower() == "email"), None)
    if not email_col:
        raise HTTPException(status_code=422, detail="CSV must contain an 'email' column")

    execution = EmailBulkCsvExecution(
        template_id=template_id,
        uploaded_filename=file.filename or "upload.csv",
        bad_log_filename=f"{CSV_DIR.name}",
        success_log_filename=f"{CSV_DIR.name}",
        total_rows=0,
        unsubscribed_rows=0,
        invalid_rows=0,
        sent_rows=0,
        failed_rows=0,
        created_at=now(),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    base_name = f"execution_{execution.id}"
    bad_path = CSV_DIR / f"{base_name}_bad.csv"
    success_path = CSV_DIR / f"{base_name}_success.csv"
    execution.bad_log_filename = f"{CSV_DIR.name}/{bad_path.name}"
    execution.success_log_filename = f"{CSV_DIR.name}/{success_path.name}"

    customer_by_email: dict[str, Customer] = {}
    for c in db.query(Customer).filter(Customer.email.isnot(None)).all():
        customer_by_email[(c.email or "").strip().lower()] = c
    try:
        dns.resolver.resolve("ambifo.com", "MX", lifetime=2.0)
    except Exception:  # noqa: BLE001 - warm cache only
        pass

    bad_rows: list[list[str]] = [["email", "reason"]]
    success_rows: list[list[str]] = [headers]
    total = 0
    invalid = 0
    unsubscribed = 0
    queued = 0
    errors: list[str] = []

    logs_to_add: list[EmailLog] = []
    for row in reader:
        total += 1
        email_raw = str(row.get(email_col) or "").strip()
        valid_email, reason = _validate_email_reachable(email_raw)
        if not valid_email:
            invalid += 1
            bad_rows.append([email_raw, reason or "invalid email"])
            errors.append(f"{email_raw}: {reason}")
            continue
        if is_unsubscribed(db, valid_email):
            unsubscribed += 1
            bad_rows.append([email_raw, "unsubscribed"])
            continue

        ctx: dict = {"today": now().strftime("%B %d, %Y")}
        for header in headers:
            if header.lower() == "email":
                continue
            ctx[header.strip()] = str(row.get(header) or "").strip()
        customer = customer_by_email.get(valid_email.strip().lower())
        if customer:
            ctx = {**customer_context(customer), **ctx}
        else:
            ctx.setdefault("customer_name", ctx.get("first_name") or ctx.get("name") or valid_email)

        try:
            subj = render_template(template.subject_template, ctx)
            rend_body = render_template(template.body_template, ctx)
        except Exception as exc:  # noqa: BLE001
            invalid += 1
            bad_rows.append([valid_email, f"render failed ({exc})"])
            continue

        success_rows.append([row[h.strip()] or "" for h in headers])
        logs_to_add.append(EmailLog(
            customer_id=customer.id if customer else None,
            template_id=template_id,
            recipient_email=valid_email,
            email_type="bulk-csv",
            subject=subj,
            body=rend_body,
            status="queued",
            queue_status="bulk",
            error_message=None,
            retry_count=0,
            csv_execution_id=execution.id,
            created_at=now(),
        ))
        queued += 1

    db.add_all(logs_to_add)
    execution.total_rows = total
    execution.invalid_rows = invalid
    execution.unsubscribed_rows = unsubscribed
    with bad_path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(bad_rows)
    with success_path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(success_rows)
    db.commit()

    return EmailCsvResultOut(
        execution_id=execution.id,
        total_rows=total,
        valid_rows=queued,
        invalid_rows=invalid,
        unsubscribed_rows=unsubscribed,
        queued=queued,
        errors=errors[:25],
    )


@router.get("/csv-executions", response_model=list[EmailCsvExecutionOut])
def list_csv_executions(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    executions = db.query(EmailBulkCsvExecution).order_by(EmailBulkCsvExecution.created_at.desc()).limit(100).all()
    return [_csv_execution_out(db, e) for e in executions]


@router.get("/csv-executions/{execution_id}", response_model=EmailCsvExecutionOut)
def get_csv_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    execution = db.get(EmailBulkCsvExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="CSV execution not found")
    return _csv_execution_out(db, execution)


def _csv_execution_out(db: Session, execution: EmailBulkCsvExecution) -> EmailCsvExecutionOut:
    pending = (
        db.query(EmailLog)
        .filter(EmailLog.csv_execution_id == execution.id, EmailLog.status.in_(("queued", "processing")))
        .count()
    )
    out = EmailCsvExecutionOut.model_validate(execution)
    out.pending = pending
    return out


@router.get("/csv-executions/{execution_id}/download/{kind}")
def download_csv_execution(
    execution_id: int,
    kind: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    execution = db.get(EmailBulkCsvExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="CSV execution not found")
    if kind == "bad":
        rel = execution.bad_log_filename
    elif kind == "success":
        rel = execution.success_log_filename
    else:
        raise HTTPException(status_code=422, detail="kind must be 'bad' or 'success'")
    path = CSV_DIR / Path(rel).name if rel else None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(path, filename=path.name, media_type="text/csv")