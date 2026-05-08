import html
import json

from flask import current_app

from app.models import Customer, EmailLog, OpportunityUpdateTag, SystemSetting, User, db
from app.services.email_service import EmailService


CORE_HISTORY_TAGS = {
    "assign",
    "email",
    "gathering",
    "important",
    "meeting",
    "segment",
    "status",
    "update",
    "document",
}


def load_admin_history_notification_subscriptions():
    raw = (SystemSetting.get_value("admin.history_notification_subscriptions", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    subscriptions = {}
    for user_id_raw, pref in payload.items():
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            continue
        pref_obj = pref if isinstance(pref, dict) else {}
        tags = []
        for tag in pref_obj.get("tags") or []:
            tag_text = str(tag or "").strip().lower()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
        subscriptions[user_id] = {
            "enabled": bool(pref_obj.get("enabled")),
            "tags": tags,
        }
    return subscriptions


def save_admin_history_notification_subscriptions(subscriptions):
    payload = {}
    for user_id, pref in (subscriptions or {}).items():
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            continue
        pref_obj = pref if isinstance(pref, dict) else {}
        tags = []
        for tag in pref_obj.get("tags") or []:
            tag_text = str(tag or "").strip().lower()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
        payload[str(uid)] = {
            "enabled": bool(pref_obj.get("enabled")),
            "tags": tags,
        }
    SystemSetting.set_value("admin.history_notification_subscriptions", json.dumps(payload))


def get_notification_tag_names():
    dynamic_tags = {
        (tag.name or "").strip().lower()
        for tag in OpportunityUpdateTag.query.order_by(OpportunityUpdateTag.created_at.asc()).all()
        if (tag.name or "").strip()
    }
    return sorted(dynamic_tags | CORE_HISTORY_TAGS)


def send_admin_history_notifications(customer_id, action, changes_summary, tag_name, changed_by="system"):
    subscriptions = load_admin_history_notification_subscriptions()
    if not subscriptions:
        return

    final_tag = (tag_name or "").strip().lower()
    if not final_tag:
        return

    recipient_user_ids = [
        user_id
        for user_id, pref in subscriptions.items()
        if pref.get("enabled") and final_tag in set(pref.get("tags") or [])
    ]
    if not recipient_user_ids:
        return

    recipients = (
        User.query
        .filter(User.id.in_(recipient_user_ids), User.is_active_user.is_(True))
        .order_by(User.username.asc())
        .all()
    )
    if not recipients:
        return

    customer = Customer.query.get(customer_id)
    customer_name = customer.customer_name if customer else f"ID {customer_id}"
    account_name = (customer.account_name or "").strip() if customer else ""

    subject = f"Opportunity Update [{final_tag}] - {customer_name}"
    body_parts = [
        "<p>An opportunity update was recorded.</p>",
        f"<p><strong>Tag:</strong> {html.escape(final_tag)}</p>",
        f"<p><strong>Action:</strong> {html.escape(action or '')}</p>",
        f"<p><strong>Opportunity:</strong> {html.escape(customer_name)}</p>",
    ]
    if account_name:
        body_parts.append(f"<p><strong>Account:</strong> {html.escape(account_name)}</p>")
    body_parts.append(f"<p><strong>Updated By:</strong> {html.escape(changed_by or 'system')}</p>")
    body_parts.append(f"<p><strong>Summary:</strong><br>{html.escape(changes_summary or '')}</p>")

    email_body = "".join(body_parts)
    email_service = EmailService(current_app)

    for user in recipients:
        target_email = (user.email or "").strip()
        if not target_email:
            continue
        try:
            result = email_service.send_html_email(target_email, subject, email_body)
            db.session.add(EmailLog(
                customer_id=customer_id,
                template_id=None,
                recipient_email=target_email,
                email_type="admin-history-notification",
                subject=subject,
                body=email_body,
                status=result.status,
                error_message=result.error,
            ))
        except Exception as exc:
            db.session.add(EmailLog(
                customer_id=customer_id,
                template_id=None,
                recipient_email=target_email,
                email_type="admin-history-notification",
                subject=subject,
                body=email_body,
                status="failed",
                error_message=str(exc),
            ))
