from datetime import datetime, timedelta
import csv
import html
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import threading
import uuid

try:
    import dns.resolver
except Exception:
    dns = None

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app.models import (
    Customer,
    CustomerDiagram,
    CustomerDocument,
    CustomerSOW,
    EmailBulkCsvExecution,
    EmailLog,
    EmailUnsubscribe,
    EmailTemplate,
    GatheringBlockStorageDetail,
    GatheringFileNasDetail,
    GatheringRequest,
    GatheringServerDetail,
    Lead,
    MeetingAvailabilityRequest,
    MeetingInvite,
    OpportunityHistory,
    OpportunityUpdateTag,
    OpportunityCloudOperator,
    OpportunitySegment,
    OpportunityStatus,
    PartnerReferenceActivity,
    PartnerReferenceContact,
    PartnerReferenceOpportunity,
    SOWMasterTemplate,
    SOWMasterTemplateSection,
    SystemSetting,
    User,
    db,
)
from app.services.email_service import EmailService
from app.services.ai_service import AIService
from app.services.macro_service import build_macro_values, render_macros
from app.services.storage_service import StorageService
from app.services.teams_service import TeamsService


crm_bp = Blueprint("crm", __name__)

DEFAULT_STATUSES = [
    ("In Pipeline", "#f4a259"),
    ("Qualified", "#2a9d8f"),
    ("Proposal", "#4d96ff"),
    ("Won", "#1a936f"),
    ("Lost", "#d1495b"),
]

DEFAULT_SEGMENTS = ["SUP", "SMB", "Enterprise", "Startup"]
DEFAULT_CLOUD_OPERATORS = ["Azure", "AWS", "GCP", "Other"]

SYSTEM_EMAIL_TEMPLATE_DEFAULTS = {
    "smtp_test": {
        "name": "System - SMTP Test Email",
        "subject": "SMTP Test Email - Ambifo CRM",
        "body": (
            "<p>This is a test email from Ambifo CRM SMTP Configuration.</p>"
            "<p>If you received this, SMTP is working correctly.</p>"
        ),
    },
    "gathering_request": {
        "name": "System - Gathering Information Request",
        "subject": "Ambifo - Gathering Sheet & Information Request",
        "body": (
            "<p>Hello {{customer_name}},</p>"
            "<p>Please share your required details using the secure form link below:</p>"
            "<p><a href='{{gathering_form_link}}'>Open Gathering Form</a></p>"
            "<p><strong>Access Key:</strong> {{gathering_access_key}}</p>"
            "<p><strong>Link Expiry:</strong> {{gathering_expires_at}}</p>"
            "<p>If needed, you can also upload your gathering sheet directly in this form.</p>"
            "<p>{{note}}</p>"
            "<p>Regards,<br>Ambifo Team</p>"
        ),
    },
    "meeting_link": {
        "name": "System - Meeting Invite",
        "subject": "{{meeting_subject}}",
        "body": (
            "<p>Hello {{customer_name}},</p>"
            "<p>Please find the meeting details below:</p>"
            "<p><strong>Subject:</strong> {{meeting_subject}}</p>"
            "<p><strong>When:</strong> {{meeting_when}}</p>"
            "<p><strong>Agenda:</strong><br>{{meeting_agenda_html}}</p>"
            "<p><strong>Required Data:</strong><br>{{meeting_required_data_html}}</p>"
            "<p><strong>Join Microsoft Teams:</strong><br><a href='{{meeting_link}}'>{{meeting_link_html}}</a></p>"
            "<p>Regards,<br>Ambifo Team</p>"
        ),
    },
    "meeting_availability": {
        "name": "System - Meeting Availability Request",
        "subject": "{{meeting_subject}}",
        "body": (
            "<p>Hello {{customer_name}},</p>"
            "<p>Please select your preferred meeting time by clicking one option below:</p>"
            "<p><a href='{{option_1_link}}' style='display:inline-block;padding:10px 16px;background:#1565c0;color:#fff;text-decoration:none;border-radius:8px;'>Option 1: {{option_1_text}}</a></p>"
            "<p><a href='{{option_2_link}}' style='display:inline-block;padding:10px 16px;background:#2e7d32;color:#fff;text-decoration:none;border-radius:8px;'>Option 2: {{option_2_text}}</a></p>"
            "<p><a href='{{option_3_link}}' style='display:inline-block;padding:10px 16px;background:#ef6c00;color:#fff;text-decoration:none;border-radius:8px;'>Option 3: {{option_3_text}}</a></p>"
            "<p>If these times don't work, share your own 3 preferred slots here: <a href='{{meeting_availability_form_link}}'>Open Availability Form</a></p>"
            "<p><small>This link expires on {{meeting_availability_expires_at}}.</small></p>"
            "<p>Regards,<br>Ambifo Team</p>"
        ),
    },
    "sow_document_email": {
        "name": "System - SOW Document Email",
        "subject": "{{sow_email_subject}}",
        "body": (
            "<p>{{sow_email_body_html}}</p>"
            "<p style='margin-top:16px;font-size:12px;color:#666;'>"
            "Please find the Statement of Work (DOCX) attached.</p>"
        ),
    },
}


def _system_template_name_set():
    return {cfg.get("name") for cfg in SYSTEM_EMAIL_TEMPLATE_DEFAULTS.values() if cfg.get("name")}


def _is_system_template_name(name):
    return (name or "") in _system_template_name_set()


def _ensure_default_statuses():
    if OpportunityStatus.query.count() > 0:
        return

    for name, color in DEFAULT_STATUSES:
        db.session.add(OpportunityStatus(name=name, color=color, is_active=True))
    db.session.commit()


def _ensure_default_segments():
    if OpportunitySegment.query.count() > 0:
        return

    for name in DEFAULT_SEGMENTS:
        db.session.add(OpportunitySegment(name=name, is_active=True))
    db.session.commit()


def _ensure_default_cloud_operators():
    if OpportunityCloudOperator.query.count() > 0:
        return

    for name in DEFAULT_CLOUD_OPERATORS:
        db.session.add(OpportunityCloudOperator(name=name, is_active=True))
    db.session.commit()


def _status_color_map(statuses):
    return {status.name: status.color for status in statuses}


def _user_color_map(users):
    palette = [
        "#3b82f6",
        "#0f766e",
        "#a16207",
        "#7c3aed",
        "#be123c",
        "#0891b2",
        "#6d28d9",
        "#1d4ed8",
    ]
    mapped = {}
    for idx, user in enumerate(users):
        mapped[user.id] = palette[idx % len(palette)]
    return mapped


def _get_smtp_settings():
    return {
        "host": SystemSetting.get_value("smtp.host", current_app.config.get("SMTP_HOST") or ""),
        "port": SystemSetting.get_value("smtp.port", str(current_app.config.get("SMTP_PORT") or "587")),
        "username": SystemSetting.get_value("smtp.username", current_app.config.get("SMTP_USERNAME") or ""),
        "password": SystemSetting.get_value("smtp.password", current_app.config.get("SMTP_PASSWORD") or ""),
        "use_tls": str(
            SystemSetting.get_value("smtp.use_tls", str(current_app.config.get("SMTP_USE_TLS", True)))
        ).lower()
        in ("true", "1", "yes", "on"),
        "mail_from": SystemSetting.get_value("smtp.mail_from", current_app.config.get("MAIL_FROM") or ""),
    }


def _get_teams_settings():
    return {
        "tenant_id": SystemSetting.get_value("teams.tenant_id", current_app.config.get("TEAMS_TENANT_ID") or ""),
        "client_id": SystemSetting.get_value("teams.client_id", current_app.config.get("TEAMS_CLIENT_ID") or ""),
        "client_secret": SystemSetting.get_value("teams.client_secret", current_app.config.get("TEAMS_CLIENT_SECRET") or ""),
        "organizer_id": SystemSetting.get_value("teams.organizer_id", current_app.config.get("TEAMS_ORGANIZER_ID") or ""),
        "default_duration_minutes": SystemSetting.get_value(
            "teams.default_duration_minutes",
            str(current_app.config.get("TEAMS_DEFAULT_DURATION_MINUTES") or "60"),
        ),
    }


def _get_meeting_settings():
    raw_days = (SystemSetting.get_value("meeting.availability_link_expiry_days", "7") or "7").strip()
    try:
        expiry_days = int(raw_days)
    except ValueError:
        expiry_days = 7
    expiry_days = max(1, min(90, expiry_days))
    return {
        "availability_link_expiry_days": str(expiry_days),
    }


def _get_effective_app_base_url():
    configured = (SystemSetting.get_value("app.base_url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    return (current_app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")


def _ensure_system_email_template(template_key):
    cfg = SYSTEM_EMAIL_TEMPLATE_DEFAULTS.get(template_key)
    if not cfg:
        return None
    tpl = EmailTemplate.query.filter_by(name=cfg["name"]).first()
    if tpl:
        return tpl
    tpl = EmailTemplate(
        name=cfg["name"],
        subject_template=cfg["subject"],
        body_template=cfg["body"],
    )
    db.session.add(tpl)
    db.session.flush()
    return tpl


def _render_system_email_template(template_key, macro_values):
    tpl = _ensure_system_email_template(template_key)
    if not tpl:
        return None, "", ""
    rendered_subject = render_macros(tpl.subject_template or "", macro_values).strip()
    rendered_body = render_macros(tpl.body_template or "", macro_values).strip()
    return tpl, rendered_subject, rendered_body


def ensure_default_system_email_templates():
    ensured_any = False
    for template_key in SYSTEM_EMAIL_TEMPLATE_DEFAULTS.keys():
        tpl = _ensure_system_email_template(template_key)
        if tpl is not None and tpl.id is not None:
            ensured_any = True
    return ensured_any


def _get_ai_settings():
    active_provider = (
        SystemSetting.get_value("ai.active_provider", None)
        or SystemSetting.get_value("ai.provider", "openai")
        or "openai"
    ).strip().lower()

    return {
        "active_provider": active_provider,
        "openai_api_key": (
            SystemSetting.get_value("ai.openai.api_key", None)
            or SystemSetting.get_value("ai.api_key", "")
            or ""
        ).strip(),
        "openai_model": (SystemSetting.get_value("ai.openai.model", "gpt-4o-mini") or "gpt-4o-mini").strip(),
        "openai_base_url": (SystemSetting.get_value("ai.openai.base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1").strip(),
        "gemini_api_key": (SystemSetting.get_value("ai.gemini.api_key", "") or "").strip(),
        "gemini_model": (SystemSetting.get_value("ai.gemini.model", "gemini-1.5-flash") or "gemini-1.5-flash").strip(),
        "gemini_base_url": (SystemSetting.get_value("ai.gemini.base_url", "https://generativelanguage.googleapis.com/v1beta") or "https://generativelanguage.googleapis.com/v1beta").strip(),
    }


def _build_ai_customer_context(customer):
    server_rows = GatheringServerDetail.query.filter_by(customer_id=customer.id).order_by(GatheringServerDetail.created_at.desc()).limit(12).all()
    file_rows = GatheringFileNasDetail.query.filter_by(customer_id=customer.id).order_by(GatheringFileNasDetail.created_at.desc()).limit(12).all()
    block_rows = GatheringBlockStorageDetail.query.filter_by(customer_id=customer.id).order_by(GatheringBlockStorageDetail.created_at.desc()).limit(12).all()

    lines = [
        f"Customer Name: {customer.customer_name or ''}",
        f"Account Name: {customer.account_name or ''}",
        f"Cloud: {customer.cloud or ''}",
        f"Segment: {customer.segment or ''}",
        f"Status: {customer.deal_status or ''}",
        f"Comment: {customer.comment or ''}",
        f"Next Action: {customer.next_action_planned or ''}",
        "",
        "Server Data:",
    ]
    for row in server_rows:
        lines.append(
            f"- {row.server_name or 'server'} | CPU:{row.cpu_cores or ''} | MemoryMB:{row.memory_mb or ''} | "
            f"StorageGB:{row.provisioned_storage_gb or ''} | OS:{row.operating_system or ''} | App:{row.application or ''}"
        )

    lines.append("")
    lines.append("File/NAS Data:")
    for row in file_rows:
        lines.append(
            f"- {row.file_server_share_name or 'share'} | UsedGB:{row.total_used_capacity_gb or ''} | "
            f"ProvisionedGB:{row.total_provisioned_capacity_gb or ''} | Protocol:{row.access_protocol or ''} | App:{row.application or ''}"
        )

    lines.append("")
    lines.append("Block Storage Data:")
    for row in block_rows:
        lines.append(
            f"- {row.volume_name or 'volume'} | UsedGB:{row.total_used_capacity_gb or ''} | "
            f"ProvisionedGB:{row.total_provisioned_capacity_gb or ''} | Array:{row.array_name or ''} | App:{row.application or ''}"
        )

    return "\n".join(lines)


def _actor_name():
    if current_user and current_user.is_authenticated:
        return current_user.username
    return "system"


def _tag_color_map():
    tags = OpportunityUpdateTag.query.filter_by(is_active=True).all()
    return {t.name.lower(): t.color for t in tags}


def _derive_tag_from_action(action):
    action_text = (action or "").lower()
    if "meeting" in action_text:
        return "meeting"
    if action_text.startswith("email"):
        return "email"
    if "gathering" in action_text:
        return "gathering"
    if "status" in action_text:
        return "status"
    if "segment" in action_text:
        return "segment"
    if "assign" in action_text:
        return "assign"
    return "update"


def _log_opportunity_history(customer_id, action, changes_summary, remark=None, tag_name=None):
    final_tag = (tag_name or "").strip().lower() or _derive_tag_from_action(action)
    db.session.add(
        OpportunityHistory(
            customer_id=customer_id,
            changed_by=_actor_name(),
            action=action,
            tag_name=final_tag,
            changes_summary=changes_summary,
            remark=remark,
        )
    )


def _to_int(value):
    raw = (value or "").strip()
    if not raw:
        return None
    return int(raw)


def _to_float(value):
    raw = (value or "").strip()
    if not raw:
        return None
    return float(raw)


def _generate_access_key(length=8):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _is_gathering_request_expired(request_record):
    return bool(request_record.expires_at and datetime.utcnow() > request_record.expires_at)


def _request_process_restart(delay_seconds=1.0):
    """Restart the full service process (Gunicorn master on Render)."""
    master_pid = os.getppid()
    target_pid = master_pid if master_pid and master_pid > 1 else os.getpid()
    threading.Timer(delay_seconds, lambda: os.kill(target_pid, signal.SIGTERM)).start()


@crm_bp.before_app_request
def require_login_for_crm_routes():
    endpoint = request.endpoint or ""
    g.user = current_user

    allowed_endpoints = {
        "crm.login",
        "crm.email_unsubscribe",
        "crm.gathering_form",
        "crm.gathering_form_sample_xlsx",
        "crm.gathering_form_sample_server_csv",
        "crm.gathering_form_sample_file_nas_csv",
        "crm.gathering_form_sample_block_storage_csv",
        "crm.meeting_availability_select",
        "crm.meeting_availability_form",
        "static",
    }

    if endpoint in allowed_endpoints:
        return

    if endpoint.startswith("crm.") and not current_user.is_authenticated:
        return redirect(url_for("crm.login", next=request.path))


@crm_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("crm.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active_user:
            login_user(user)
            next_url = request.args.get("next") or url_for("crm.dashboard")
            flash("Login successful.", "success")
            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@crm_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for("crm.login"))


@crm_bp.route("/email/unsubscribe", methods=["GET"])
def email_unsubscribe():
    token = (request.args.get("token") or "").strip()
    svc = EmailService(current_app)
    email = svc.resolve_unsubscribe_token(token)

    if not email:
        return render_template(
            "email_unsubscribe.html",
            success=False,
            already=False,
            email="",
            message="Invalid or expired unsubscribe link.",
        )

    existing = EmailUnsubscribe.query.filter_by(email=email).first()
    if existing:
        return render_template(
            "email_unsubscribe.html",
            success=True,
            already=True,
            email=email,
            message="This email is already unsubscribed.",
        )

    db.session.add(EmailUnsubscribe(email=email, source="footer-link"))
    db.session.commit()
    return render_template(
        "email_unsubscribe.html",
        success=True,
        already=False,
        email=email,
        message="You have been unsubscribed successfully.",
    )


@crm_bp.route("/")
def index():
    return redirect(url_for("crm.dashboard"))


def _dashboard_period_bounds(period, start_raw=None, end_raw=None):
    now = datetime.utcnow()
    period = (period or "monthly").strip().lower()

    if period == "weekly":
        start = now - timedelta(days=7)
        end = now
    elif period == "quarterly":
        start = now - timedelta(days=90)
        end = now
    elif period == "yearly":
        start = now - timedelta(days=365)
        end = now
    elif period == "custom":
        try:
            start = datetime.strptime((start_raw or "").strip(), "%Y-%m-%d")
            end = datetime.strptime((end_raw or "").strip(), "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            start = now - timedelta(days=30)
            end = now
    else:
        start = now - timedelta(days=30)
        end = now
    return start, end


def _split_city_country(city_value):
    raw = (city_value or "").strip()
    if not raw:
        return "Unknown", "Unknown"
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[-1]
    if "-" in raw:
        parts = [p.strip() for p in raw.split("-") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[-1]
    return raw, "Unknown"


def _build_dashboard_graph_payload(start_dt, end_dt):
    customers = Customer.query.filter(Customer.created_at >= start_dt, Customer.created_at < end_dt).all()

    assign_counts = {}
    segment_counts = {}
    status_counts = {}
    country_counts = {}
    city_counts = {}

    for c in customers:
        assignee = c.assigned_to.username if c.assigned_to else "Unassigned"
        segment = (c.segment or "Not Set").strip() or "Not Set"
        status = (c.deal_status or "Not Set").strip() or "Not Set"
        city, country = _split_city_country(c.city)

        assign_counts[assignee] = assign_counts.get(assignee, 0) + 1
        segment_counts[segment] = segment_counts.get(segment, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        country_counts[country] = country_counts.get(country, 0) + 1
        city_counts[city] = city_counts.get(city, 0) + 1

    top_cities = sorted(city_counts.items(), key=lambda kv: kv[1], reverse=True)[:12]

    return {
        "summary": {
            "total_opportunities": len(customers),
            "from": start_dt.strftime("%Y-%m-%d"),
            "to": (end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        "assign": {
            "labels": list(assign_counts.keys()),
            "values": list(assign_counts.values()),
        },
        "segment": {
            "labels": list(segment_counts.keys()),
            "values": list(segment_counts.values()),
        },
        "status": {
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        },
        "country": {
            "labels": list(country_counts.keys()),
            "values": list(country_counts.values()),
        },
        "city": {
            "labels": [c for c, _ in top_cities],
            "values": [v for _, v in top_cities],
        },
    }


@crm_bp.route("/dashboard")
@login_required
def dashboard():
    tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
    return render_template(
        "dashboard.html",
        update_tags=tags,
    )


@crm_bp.route("/dashboard/graph-data", methods=["GET"])
@login_required
def dashboard_graph_data():
    period = (request.args.get("period") or "monthly").strip().lower()
    start_raw = request.args.get("start")
    end_raw = request.args.get("end")
    start_dt, end_dt = _dashboard_period_bounds(period, start_raw, end_raw)
    payload = _build_dashboard_graph_payload(start_dt, end_dt)
    payload["period"] = period
    return jsonify(success=True, data=payload)


@crm_bp.route("/dashboard/history-data", methods=["GET"])
@login_required
def dashboard_history_data():
    tag_filter = (request.args.get("tag") or "important").strip().lower()
    limit = request.args.get("limit", 25, type=int)
    if limit < 1:
        limit = 25
    if limit > 200:
        limit = 200

    query = OpportunityHistory.query.order_by(OpportunityHistory.created_at.desc())
    if tag_filter != "all":
        query = query.filter(OpportunityHistory.tag_name == tag_filter)
    rows = query.limit(limit).all()

    tag_colors = _tag_color_map()
    items = []
    for h in rows:
        tag = (h.tag_name or _derive_tag_from_action(h.action)).lower()
        items.append(
            {
                "created_at": h.created_at.strftime("%Y-%m-%d %H:%M"),
                "customer_id": h.customer_id,
                "customer_name": h.customer.customer_name if h.customer else "Unknown",
                "changed_by": h.changed_by or "system",
                "action": h.action,
                "tag": tag,
                "tag_color": tag_colors.get(tag, "#6b7280"),
                "changes_summary": h.changes_summary,
                "remark": h.remark or "",
            }
        )

    tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
    return jsonify(
        success=True,
        applied_tag=tag_filter,
        available_tags=[{"name": "all", "color": "#4b5563"}] + [{"name": t.name, "color": t.color} for t in tags],
        items=items,
    )


@crm_bp.route("/dashboard/upcoming-meetings-data", methods=["GET"])
@login_required
def dashboard_upcoming_meetings_data():
    tag_filter = (request.args.get("tag") or "all").strip().lower()
    limit = request.args.get("limit", 20, type=int)
    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    if tag_filter not in {"all", "meeting"}:
        return jsonify(success=True, items=[])

    now = datetime.utcnow()
    rows = (
        MeetingInvite.query
        .filter(MeetingInvite.scheduled_at.isnot(None), MeetingInvite.scheduled_at >= now)
        .order_by(MeetingInvite.scheduled_at.asc())
        .limit(limit)
        .all()
    )

    items = []
    for m in rows:
        items.append(
            {
                "id": m.id,
                "customer_id": m.customer_id,
                "customer_name": m.customer.customer_name if m.customer else "Unknown",
                "recipient_email": m.recipient_email,
                "subject": m.subject,
                "meeting_link": m.meeting_link,
                "scheduled_at": m.scheduled_at.strftime("%Y-%m-%d %H:%M") if m.scheduled_at else "TBD",
                "created_by": m.created_by or "system",
            }
        )

    return jsonify(success=True, items=items)


@crm_bp.route("/opportunities/<int:customer_id>/gathering-status")
@login_required
def opportunity_gathering_status(customer_id):
    """Return JSON info about existing gathering links for this customer."""
    customer = Customer.query.get_or_404(customer_id)
    links = (
        GatheringRequest.query
        .filter_by(customer_id=customer_id)
        .order_by(GatheringRequest.created_at.desc())
        .all()
    )
    base = _get_effective_app_base_url()
    items = [
        {
            "id": gr.id,
            "status": ("locked" if gr.is_locked else gr.status),
            "is_locked": gr.is_locked,
            "created_at": gr.created_at.strftime("%Y-%m-%d %H:%M"),
            "expires_at": gr.expires_at.strftime("%Y-%m-%d %H:%M") if gr.expires_at else "—",
            "key_hint": ("••••" + gr.access_key_hint) if gr.access_key_hint else "—",
            "form_url": f"{base}/gathering/form/{gr.token}",
        }
        for gr in links
    ]
    return jsonify({"success": True, "customer_name": customer.customer_name, "email": customer.email, "links": items})


@crm_bp.route("/opportunities/<int:customer_id>/send-gathering-link", methods=["POST"])
@login_required
def opportunity_send_gathering_link(customer_id):
    """JSON endpoint: create + email a new gathering link from the opportunity list page."""
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}
    expiry_days = int(data.get("expiry_days") or 7)
    note = (data.get("note") or "").strip()

    if expiry_days < 1 or expiry_days > 90:
        return jsonify({"success": False, "message": "Expiry must be between 1 and 90 days."})

    token = secrets.token_urlsafe(24)
    access_key = _generate_access_key()
    new_gr = GatheringRequest(
        token=token,
        customer_id=customer.id,
        note=note,
        expires_at=datetime.utcnow() + timedelta(days=expiry_days),
        access_key_hash=generate_password_hash(access_key),
        access_key_hint=access_key[-4:],
        status="sent",
    )
    db.session.add(new_gr)
    db.session.flush()

    form_link = f"{_get_effective_app_base_url()}/gathering/form/{token}"
    expires_at_text = new_gr.expires_at.strftime("%Y-%m-%d %H:%M UTC")
    macro_values = build_macro_values(
        customer,
        {
            "gathering_form_link": form_link,
            "gathering_access_key": access_key,
            "gathering_expires_at": expires_at_text,
            "note": note,
        },
    )
    tpl, rendered_subject, rendered_body = _render_system_email_template("gathering_request", macro_values)
    email_service = EmailService(current_app)
    result = email_service.send_html_email(
        customer.email, rendered_subject, rendered_body
    )
    db.session.add(
        EmailLog(
            customer_id=customer.id,
            template_id=tpl.id if tpl else None,
            recipient_email=customer.email,
            email_type="gathering",
            subject=rendered_subject,
            body=rendered_body,
            status=result.status,
            error_message=result.error,
        )
    )
    _log_opportunity_history(
        customer.id,
        action="gathering-link-sent",
        changes_summary=(
            f"Gathering link sent to {customer.email} by {_actor_name()} "
            f"(from opportunity list). Expiry: {expires_at_text}. Token: …{token[-6:]}."
        ),
        remark=note or None,
    )
    db.session.commit()

    if result.success:
        return jsonify({
            "success": True,
            "message": f"Gathering link sent to {customer.email}.",
            "access_key": access_key,
            "expires_at": expires_at_text,
            "form_url": form_link,
        })
    return jsonify({
        "success": False,
        "message": f"Email delivery failed: {result.error}. Link created — access key: {access_key}",
        "access_key": access_key,
        "expires_at": expires_at_text,
        "form_url": form_link,
    })


@crm_bp.route("/opportunities/<int:customer_id>/meeting-link/send", methods=["POST"])
@login_required
def opportunity_send_meeting_link(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    recipient_email_raw = (request.form.get("recipient_email") or customer.email or "").strip()
    recipient_emails = [e.strip() for e in recipient_email_raw.replace(";", ",").split(",") if e.strip()]
    subject = (request.form.get("subject") or "").strip()
    meeting_link = (request.form.get("meeting_link") or "").strip()
    agenda = (request.form.get("agenda") or "").strip()
    required_data = (request.form.get("required_data") or "").strip()
    meeting_datetime = (request.form.get("meeting_datetime") or "").strip()
    remark = (request.form.get("remark") or "").strip()
    teams_service = TeamsService(current_app)
    teams_is_configured = teams_service.is_configured()

    if not recipient_emails or not subject or not agenda or not required_data:
        flash("At least one recipient email, subject, agenda, and required data are mandatory.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    invalid_emails = [e for e in recipient_emails if "@" not in e]
    if invalid_emails:
        flash("Please enter valid recipient emails separated by comma.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    meeting_start = None
    if meeting_datetime:
        try:
            meeting_start = datetime.fromisoformat(meeting_datetime)
        except ValueError:
            flash("Invalid meeting date/time. Please select a valid value.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    link_source = "manual"
    if not meeting_link:
        if not teams_is_configured:
            flash("Teams is not configured. Please enter a meeting link manually.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

        meeting_result = teams_service.create_online_meeting(subject=subject, start_at=meeting_start)
        if not meeting_result.success:
            flash(f"Teams link generation failed: {meeting_result.error_message}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

        meeting_link = meeting_result.join_url
        link_source = "auto-generated"
        if not meeting_start and meeting_result.start_utc:
            meeting_datetime = meeting_result.start_utc

    scheduled_at = meeting_start
    if meeting_datetime and not scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(meeting_datetime.replace("Z", "+00:00"))
        except ValueError:
            scheduled_at = None

    if not (meeting_link.startswith("http://") or meeting_link.startswith("https://")):
        flash("Please provide a valid Teams meeting URL.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    agenda_html = html.escape(agenda).replace("\n", "<br>")
    required_data_html = html.escape(required_data).replace("\n", "<br>")
    meeting_when = meeting_datetime or "To be confirmed"
    meeting_when_html = html.escape(meeting_when)
    meeting_link_html = html.escape(meeting_link)

    template_macro_values = build_macro_values(
        customer,
        {
            "meeting_subject": html.escape(subject),
            "meeting_when": meeting_when_html,
            "meeting_agenda_html": agenda_html,
            "meeting_required_data_html": required_data_html,
            "meeting_link": meeting_link_html,
            "meeting_link_html": meeting_link_html,
        },
    )
    tpl, rendered_subject, rendered_body = _render_system_email_template("meeting_link", template_macro_values)

    email_service = EmailService(current_app)
    sent_count = 0
    failed_count = 0

    for recipient_email in recipient_emails:
        result = email_service.send_html_email(recipient_email, rendered_subject, rendered_body)
        db.session.add(
            EmailLog(
                customer_id=customer.id,
                template_id=tpl.id if tpl else None,
                recipient_email=recipient_email,
                email_type="meeting-link",
                subject=rendered_subject,
                body=rendered_body,
                status=result.status,
                error_message=result.error,
            )
        )

        if result.success or result.status == "dev-mode":
            sent_count += 1
            db.session.add(
                MeetingInvite(
                    customer_id=customer.id,
                    recipient_email=recipient_email,
                    subject=subject,
                    meeting_link=meeting_link,
                    agenda=agenda,
                    required_data=required_data,
                    scheduled_at=scheduled_at,
                    created_by=_actor_name(),
                )
            )
        else:
            failed_count += 1

    history_summary = (
        f"Teams meeting invite processed for {len(recipient_emails)} recipient(s).\n"
        f"Sent: {sent_count}, Failed: {failed_count}\n"
        f"Recipients: {', '.join(recipient_emails)}\n"
        f"Link Source: {link_source}\n"
        f"Subject: {subject}\n"
        f"When: {meeting_when}\n"
        f"Meeting Link: {meeting_link}"
    )
    _log_opportunity_history(
        customer.id,
        action="teams-meeting-link-sent",
        changes_summary=history_summary,
        remark=remark or None,
        tag_name="meeting",
    )
    db.session.commit()

    if failed_count == 0:
        flash(f"Teams meeting invite sent to {sent_count} recipient(s).", "success")
    elif sent_count > 0:
        flash(f"Meeting invite partial success. Sent: {sent_count}, Failed: {failed_count}.", "error")
    else:
        flash("Meeting invite failed for all recipients.", "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))


def _format_option_dt(value):
    return value.strftime("%d %b %Y, %I:%M %p UTC")


def _build_template_macro_values_for_customer(customer, template, recipient_email=None):
    macro_values = build_macro_values(customer)

    active_diagrams = (
        CustomerDiagram.query
        .filter_by(customer_id=customer.id, is_active=True)
        .order_by(CustomerDiagram.created_at.asc())
        .all()
    )
    if active_diagrams:
        diagram_html_blocks = []
        for diagram in active_diagrams:
            safe_name = html.escape(diagram.diagram_name or "Diagram")
            diagram_html_blocks.append(f"<h4>{safe_name}</h4>{diagram.diagram_content or ''}")
            diagram_macro = (diagram.macro_key or "").strip()
            if diagram_macro:
                macro_values[diagram_macro] = diagram.diagram_content or ""
        macro_values["selected_diagrams_html"] = "\n".join(diagram_html_blocks)
    else:
        macro_values["selected_diagrams_html"] = ""

    if not template:
        return macro_values

    template_text = f"{template.subject_template or ''}\n{template.body_template or ''}"
    requires_link = (
        "{{meeting_availability_form_link}}" in template_text
        or "{{meeting_availability_expires_at}}" in template_text
    )
    if not requires_link:
        return macro_values

    meeting_settings = _get_meeting_settings()
    expiry_days = int(meeting_settings["availability_link_expiry_days"])
    expires_at = datetime.utcnow() + timedelta(days=expiry_days)
    token = secrets.token_urlsafe(24)

    base_slot = datetime.utcnow() + timedelta(days=1)
    req = MeetingAvailabilityRequest(
        token=token,
        customer_id=customer.id,
        recipient_email=(recipient_email or customer.email or "").strip() or (customer.email or "unknown@local"),
        subject=(template.subject_template or "Select Your Preferred Meeting Time"),
        option_1_at=base_slot,
        option_2_at=base_slot + timedelta(hours=1),
        option_3_at=base_slot + timedelta(hours=2),
        expires_at=expires_at,
        status="sent",
        created_by=_actor_name(),
    )
    db.session.add(req)

    expires_text = expires_at.strftime("%d %b %Y, %I:%M %p UTC")
    _log_opportunity_history(
        customer.id,
        action="meeting-availability-link-generated",
        changes_summary=(
            "Meeting availability token link generated from template send.\n"
            f"Template: {template.name if getattr(template, 'name', None) else 'N/A'}\n"
            f"Recipient: {(recipient_email or customer.email or 'N/A')}\n"
            f"Token: ...{token[-6:]}\n"
            f"Expires: {expires_text}"
        ),
        remark=None,
        tag_name="meeting",
    )

    base_url = _get_effective_app_base_url()
    macro_values["meeting_availability_form_link"] = f"{base_url}/meeting/availability/form/{token}"
    macro_values["meeting_availability_expires_at"] = expires_text
    return macro_values


def _email_template_macro_catalog():
    # Canonical macro keys supported by email template rendering paths.
    keys = [
        "customer_name",
        "account_name",
        "email",
        "phone",
        "city",
        "segment",
        "deal_status",
        "today",
        "gathering_form_link",
        "gathering_access_key",
        "gathering_expires_at",
        "meeting_availability_form_link",
        "meeting_availability_expires_at",
        "selected_diagrams_html",
    ]
    return [f"{{{{{k}}}}}" for k in keys]


def _sanitize_email_template_body(body_html):
    text = (body_html or "").strip()
    if not text:
        return ""

    # If a full Ambifo wrapper was pasted, keep only the editable content cell.
    if (
        "support@ambifo.com" in text
        and "ambifo.com" in text
        and "www.linkedin.com/company/ambifo-technology" in text
    ):
        match = re.search(
            r'<td[^>]*padding:20px;line-height:1\.6;font-size:14px;[^>]*>([\s\S]*?)</td>',
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return (match.group(1) or "").strip()

    # Remove explicit footer tags if users paste them.
    text = re.sub(r"<footer[\s\S]*?</footer>", "", text, flags=re.IGNORECASE)

    # Remove lines/blocks containing locked branding footer contact details.
    footer_tokens = [
        "support@ambifo.com",
        "https://ambifo.com",
        "www.linkedin.com/company/ambifo-technology",
        "+91 9148419502",
        "Building No 674",
    ]
    for token in footer_tokens:
        text = re.sub(
            rf"<(p|div|span|li)[^>]*>[\s\S]*?{re.escape(token)}[\s\S]*?</\1>",
            "",
            text,
            flags=re.IGNORECASE,
        )

    return text.strip()


def _is_valid_email(value):
    if not value:
        return False
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return re.match(pattern, value) is not None


def _normalize_macro_key(value):
    key = re.sub(r"[^a-zA-Z0-9_]", "_", (value or "").strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return key


@crm_bp.route("/opportunities/<int:customer_id>/meeting-availability/send", methods=["POST"])
@login_required
def opportunity_send_meeting_availability(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    recipient_email = (request.form.get("recipient_email") or customer.email or "").strip()
    subject = (request.form.get("subject") or "Select Your Preferred Meeting Time").strip()
    option_1_raw = (request.form.get("option_1") or "").strip()
    option_2_raw = (request.form.get("option_2") or "").strip()
    option_3_raw = (request.form.get("option_3") or "").strip()
    remark = (request.form.get("remark") or "").strip()

    if not recipient_email or "@" not in recipient_email:
        flash("Please enter a valid recipient email.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    try:
        option_1_at = datetime.fromisoformat(option_1_raw)
        option_2_at = datetime.fromisoformat(option_2_raw)
        option_3_at = datetime.fromisoformat(option_3_raw)
    except ValueError:
        flash("Please provide all three valid date/time options.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    unique_slots = {option_1_at.isoformat(), option_2_at.isoformat(), option_3_at.isoformat()}
    if len(unique_slots) < 3:
        flash("Meeting options must be three different date/time values.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

    token = secrets.token_urlsafe(24)
    meeting_settings = _get_meeting_settings()
    expiry_days = int(meeting_settings["availability_link_expiry_days"])
    expires_at = datetime.utcnow() + timedelta(days=expiry_days)
    req = MeetingAvailabilityRequest(
        token=token,
        customer_id=customer.id,
        recipient_email=recipient_email,
        subject=subject,
        option_1_at=option_1_at,
        option_2_at=option_2_at,
        option_3_at=option_3_at,
        expires_at=expires_at,
        status="sent",
        created_by=_actor_name(),
    )
    db.session.add(req)
    db.session.flush()

    base = _get_effective_app_base_url()
    option_1_link = f"{base}/meeting/availability/{token}/1"
    option_2_link = f"{base}/meeting/availability/{token}/2"
    option_3_link = f"{base}/meeting/availability/{token}/3"
    form_link = f"{base}/meeting/availability/form/{token}"

    expires_at_text = html.escape(expires_at.strftime('%d %b %Y, %I:%M %p UTC'))
    template_macro_values = build_macro_values(
        customer,
        {
            "meeting_subject": html.escape(subject),
            "option_1_link": html.escape(option_1_link),
            "option_2_link": html.escape(option_2_link),
            "option_3_link": html.escape(option_3_link),
            "option_1_text": html.escape(_format_option_dt(option_1_at)),
            "option_2_text": html.escape(_format_option_dt(option_2_at)),
            "option_3_text": html.escape(_format_option_dt(option_3_at)),
            "meeting_availability_form_link": html.escape(form_link),
            "meeting_availability_expires_at": expires_at_text,
        },
    )
    tpl, rendered_subject, rendered_body = _render_system_email_template("meeting_availability", template_macro_values)

    result = EmailService(current_app).send_html_email(recipient_email, rendered_subject, rendered_body)
    db.session.add(
        EmailLog(
            customer_id=customer.id,
            template_id=tpl.id if tpl else None,
            recipient_email=recipient_email,
            email_type="meeting-availability",
            subject=rendered_subject,
            body=rendered_body,
            status=result.status,
            error_message=result.error,
        )
    )

    history_summary = (
        "Meeting availability request sent with 3 one-click options.\n"
        f"To: {recipient_email}\n"
        f"Option 1: {_format_option_dt(option_1_at)}\n"
        f"Option 2: {_format_option_dt(option_2_at)}\n"
        f"Option 3: {_format_option_dt(option_3_at)}\n"
        f"Token: ...{token[-6:]}"
    )
    _log_opportunity_history(
        customer.id,
        action="meeting-availability-request-sent",
        changes_summary=history_summary,
        remark=remark or None,
        tag_name="meeting",
    )
    db.session.commit()

    if result.success or result.status == "dev-mode":
        flash("Availability options email sent successfully.", "success")
    else:
        flash(f"Availability email failed: {result.error}", "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))


@crm_bp.route("/meeting/availability/<token>/<int:option_no>", methods=["GET"])
def meeting_availability_select(token, option_no):
    req = MeetingAvailabilityRequest.query.filter_by(token=token).first_or_404()
    customer = req.customer

    if option_no not in {1, 2, 3}:
        return render_template("error_500.html"), 400

    if req.expires_at and datetime.utcnow() > req.expires_at:
        return "This meeting availability link has expired.", 410

    if req.selected_option:
        return "Thanks. Your response is already recorded.", 200

    selected_dt = req.option_1_at if option_no == 1 else req.option_2_at if option_no == 2 else req.option_3_at
    req.selected_option = option_no
    req.selected_at = datetime.utcnow()
    req.status = "selected"

    selected_text = _format_option_dt(selected_dt)
    comment_line = f"Customer selected meeting option {option_no}: {selected_text}"
    existing_comment = (customer.comment or "").strip()
    customer.comment = f"{existing_comment}\n{comment_line}".strip() if existing_comment else comment_line

    _log_opportunity_history(
        customer.id,
        action="meeting-availability-selected",
        changes_summary=f"Customer selected Option {option_no} from one-click email: {selected_text}",
        remark=f"Response captured from token ...{token[-6:]}",
        tag_name="meeting",
    )

    db.session.commit()
    return "Thank you. Your preferred meeting time has been submitted.", 200


@crm_bp.route("/meeting/availability/form/<token>", methods=["GET", "POST"])
def meeting_availability_form(token):
    req = MeetingAvailabilityRequest.query.filter_by(token=token).first_or_404()
    customer = req.customer

    if req.expires_at and datetime.utcnow() > req.expires_at:
        return "This meeting availability link has expired.", 410

    if request.method == "POST":
        option_1_raw = (request.form.get("option_1") or "").strip()
        option_2_raw = (request.form.get("option_2") or "").strip()
        option_3_raw = (request.form.get("option_3") or "").strip()
        extra_recipients = (request.form.get("extra_recipients") or "").strip()
        customer_note = (request.form.get("customer_note") or "").strip()
        form_values = {
            "option_1": option_1_raw,
            "option_2": option_2_raw,
            "option_3": option_3_raw,
            "extra_recipients": extra_recipients,
            "customer_note": customer_note,
        }

        try:
            c1 = datetime.fromisoformat(option_1_raw)
            c2 = datetime.fromisoformat(option_2_raw)
            c3 = datetime.fromisoformat(option_3_raw)
        except ValueError:
            return render_template(
                "meeting_availability_form.html",
                request_record=req,
                customer=customer,
                form_error="Please enter all 3 valid date/time values.",
                form_values=form_values,
            ), 400

        unique_slots = {c1.isoformat(), c2.isoformat(), c3.isoformat()}
        if len(unique_slots) < 3:
            return render_template(
                "meeting_availability_form.html",
                request_record=req,
                customer=customer,
                form_error="Please provide 3 different date/time options.",
                form_values=form_values,
            ), 400

        if extra_recipients:
            recipient_list = [item.strip() for item in extra_recipients.replace(";", ",").split(",") if item.strip()]
            invalid_emails = [email for email in recipient_list if not _is_valid_email(email)]
            if invalid_emails:
                return render_template(
                    "meeting_availability_form.html",
                    request_record=req,
                    customer=customer,
                    form_error="Please enter valid extra recipient emails separated by comma.",
                    form_values=form_values,
                ), 400
            extra_recipients = ", ".join(recipient_list)

        req.customer_option_1_at = c1
        req.customer_option_2_at = c2
        req.customer_option_3_at = c3
        req.extra_recipients = extra_recipients or None
        req.customer_note = customer_note or None
        req.customer_submitted_at = datetime.utcnow()
        req.status = "submitted-form"

        summary_lines = [
            "Customer submitted preferred meeting slots via token form.",
            f"Option 1: {_format_option_dt(c1)}",
            f"Option 2: {_format_option_dt(c2)}",
            f"Option 3: {_format_option_dt(c3)}",
        ]
        if extra_recipients:
            summary_lines.append(f"Extra recipients: {extra_recipients}")
        if customer_note:
            summary_lines.append(f"Customer note: {customer_note}")

        existing_comment = (customer.comment or "").strip()
        append_comment = "Customer shared 3 preferred meeting slots."
        customer.comment = f"{existing_comment}\n{append_comment}".strip() if existing_comment else append_comment

        _log_opportunity_history(
            customer.id,
            action="meeting-availability-form-submitted",
            changes_summary="\n".join(summary_lines),
            remark=f"Response captured from token ...{token[-6:]}",
            tag_name="meeting",
        )
        db.session.commit()
        return "Thank you. Your availability details have been submitted.", 200

    return render_template(
        "meeting_availability_form.html",
        request_record=req,
        customer=customer,
        form_error=None,
        form_values={
            "option_1": "",
            "option_2": "",
            "option_3": "",
            "extra_recipients": "",
            "customer_note": "",
        },
    )


@crm_bp.route("/customers")
@crm_bp.route("/opportunities")
def opportunity_list():
    _ensure_default_statuses()
    _ensure_default_segments()
    _ensure_default_cloud_operators()
    query = (request.args.get("q") or "").strip()
    selected_assigned_to = request.args.get("assigned_to", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = 5

    customers_query = Customer.query
    if query:
        like = f"%{query}%"
        customers_query = customers_query.filter(
            db.or_(
                Customer.customer_name.ilike(like),
                Customer.account_name.ilike(like),
                Customer.email.ilike(like),
                Customer.city.ilike(like),
            )
        )

    if selected_assigned_to:
        customers_query = customers_query.filter(Customer.assign_to_user_id == selected_assigned_to)

    pagination = customers_query.order_by(Customer.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    statuses = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
    segments = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
    cloud_operators = OpportunityCloudOperator.query.filter_by(is_active=True).order_by(OpportunityCloudOperator.name.asc()).all()
    admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
    email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
    total_count = Customer.query.count()
    return render_template(
        "customers_list.html",
        customers=pagination.items,
        query=query,
        selected_assigned_to=selected_assigned_to,
        pagination=pagination,
        statuses=statuses,
        segments=segments,
        cloud_operators=cloud_operators,
        admin_users=admin_users,
        assign_colors=_user_color_map(admin_users),
        status_colors=_status_color_map(statuses),
        email_templates=email_templates,
        total_count=total_count,
    )


@crm_bp.route("/customers")
def customer_list():
    return redirect(url_for("crm.opportunity_list", **request.args))


@crm_bp.route("/references")
def reference_list():
    query = (request.args.get("q") or "").strip()
    partner_filter = (request.args.get("partner") or "").strip()
    sort_by = (request.args.get("sort") or "latest_activity_desc").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    last_activity_subq = (
        db.session.query(
            PartnerReferenceActivity.reference_contact_id.label("ref_id"),
            db.func.max(
                db.func.coalesce(
                    PartnerReferenceActivity.activity_date,
                    PartnerReferenceActivity.created_at,
                )
            ).label("last_activity_at"),
        )
        .group_by(PartnerReferenceActivity.reference_contact_id)
        .subquery()
    )

    contacts_query = (
        db.session.query(PartnerReferenceContact, last_activity_subq.c.last_activity_at)
        .outerjoin(last_activity_subq, PartnerReferenceContact.id == last_activity_subq.c.ref_id)
    )

    if query:
        like = f"%{query}%"
        contacts_query = contacts_query.filter(
            db.or_(
                PartnerReferenceContact.contact_name.ilike(like),
                PartnerReferenceContact.email.ilike(like),
                PartnerReferenceContact.phone.ilike(like),
                PartnerReferenceContact.city.ilike(like),
            )
        )
    if partner_filter:
        contacts_query = contacts_query.filter(PartnerReferenceContact.partner_name.ilike(partner_filter))

    if sort_by == "latest_activity_desc":
        contacts_query = contacts_query.order_by(
            last_activity_subq.c.last_activity_at.is_(None),
            last_activity_subq.c.last_activity_at.desc(),
            PartnerReferenceContact.created_at.desc(),
        )
    elif sort_by == "newest_contact":
        contacts_query = contacts_query.order_by(PartnerReferenceContact.created_at.desc())
    elif sort_by == "partner_asc":
        contacts_query = contacts_query.order_by(
            PartnerReferenceContact.partner_name.asc(),
            PartnerReferenceContact.contact_name.asc(),
        )
    elif sort_by == "contact_asc":
        contacts_query = contacts_query.order_by(PartnerReferenceContact.contact_name.asc())
    elif sort_by == "active_first":
        contacts_query = contacts_query.order_by(
            PartnerReferenceContact.is_active.desc(),
            PartnerReferenceContact.contact_name.asc(),
        )
    else:
        sort_by = "latest_activity_desc"
        contacts_query = contacts_query.order_by(
            last_activity_subq.c.last_activity_at.is_(None),
            last_activity_subq.c.last_activity_at.desc(),
            PartnerReferenceContact.created_at.desc(),
        )

    pagination = contacts_query.paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )

    rows = []
    for contact, last_activity_at in pagination.items:
        activity_count = PartnerReferenceActivity.query.filter_by(reference_contact_id=contact.id).count()
        rows.append(
            {
                "contact": contact,
                "activity_count": activity_count,
                "last_activity_at": last_activity_at,
            }
        )

    partner_values = (
        db.session.query(PartnerReferenceContact.partner_name)
        .filter(PartnerReferenceContact.partner_name.isnot(None), PartnerReferenceContact.partner_name != "")
        .distinct()
        .order_by(PartnerReferenceContact.partner_name.asc())
        .all()
    )
    partners = [p[0] for p in partner_values if p and p[0]]
    customers = Customer.query.order_by(Customer.customer_name.asc()).all()

    return render_template(
        "references_list.html",
        rows=rows,
        pagination=pagination,
        query=query,
        partner_filter=partner_filter,
        sort_by=sort_by,
        partners=partners,
        customers=customers,
        total_count=PartnerReferenceContact.query.count(),
    )


@crm_bp.route("/leads", methods=["GET", "POST"])
def lead_list():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "upload_leads_csv":
            csv_file = request.files.get("leads_csv_file")
            if not csv_file or not csv_file.filename:
                flash("Please choose a CSV file for leads upload.", "error")
                return redirect(url_for("crm.lead_list"))

            try:
                file_name = secure_filename(csv_file.filename or "leads.csv")
                content = csv_file.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(content))
                rows = list(reader)
                headers = [h.strip() for h in (reader.fieldnames or [])]
            except Exception as e:
                flash(f"Failed to read leads CSV: {e}", "error")
                return redirect(url_for("crm.lead_list"))

            if "email" not in headers:
                flash("Leads CSV must include 'email' column.", "error")
                return redirect(url_for("crm.lead_list"))

            imported = skipped = 0
            for row in rows:
                if _upsert_lead_from_row(row, uploaded_from=file_name):
                    imported += 1
                else:
                    skipped += 1
            db.session.commit()
            flash(f"Leads upload done: {imported} imported/updated, {skipped} skipped.", "success")
            return redirect(url_for("crm.lead_list"))

        if action == "add_lead":
            lead_email = (request.form.get("lead_email") or "").strip().lower()
            if not _is_valid_email(lead_email):
                flash("Valid lead email is required.", "error")
                return redirect(url_for("crm.lead_list"))
            if Lead.query.filter_by(email=lead_email).first():
                flash("Lead with this email already exists.", "error")
                return redirect(url_for("crm.lead_list"))

            lead = Lead(
                lead_name=(request.form.get("lead_name") or "").strip() or None,
                email=lead_email,
                phone=(request.form.get("lead_phone") or "").strip() or None,
                company=(request.form.get("lead_company") or "").strip() or None,
                city=(request.form.get("lead_city") or "").strip() or None,
                source=(request.form.get("lead_source") or "").strip() or None,
                tags=(request.form.get("lead_tags") or "").strip() or None,
                notes=(request.form.get("lead_notes") or "").strip() or None,
                is_active=bool(request.form.get("lead_is_active")),
                lead_status="new",
            )
            db.session.add(lead)
            db.session.commit()
            flash("Lead added.", "success")
            return redirect(url_for("crm.lead_list"))

        if action == "edit_lead":
            lead_id = request.form.get("lead_id", type=int)
            lead = Lead.query.get(lead_id) if lead_id else None
            if not lead:
                flash("Lead not found.", "error")
                return redirect(url_for("crm.lead_list"))
            lead_email = (request.form.get("lead_email") or "").strip().lower()
            if not _is_valid_email(lead_email):
                flash("Valid lead email is required.", "error")
                return redirect(url_for("crm.lead_list"))
            dup = Lead.query.filter(Lead.email == lead_email, Lead.id != lead.id).first()
            if dup:
                flash("Another lead already uses this email.", "error")
                return redirect(url_for("crm.lead_list"))

            lead.lead_name = (request.form.get("lead_name") or "").strip() or None
            lead.email = lead_email
            lead.phone = (request.form.get("lead_phone") or "").strip() or None
            lead.company = (request.form.get("lead_company") or "").strip() or None
            lead.city = (request.form.get("lead_city") or "").strip() or None
            lead.source = (request.form.get("lead_source") or "").strip() or None
            lead.tags = (request.form.get("lead_tags") or "").strip() or None
            lead.notes = (request.form.get("lead_notes") or "").strip() or None
            lead.is_active = bool(request.form.get("lead_is_active"))
            db.session.commit()
            flash("Lead updated.", "success")
            return redirect(url_for("crm.lead_list"))

        if action == "delete_lead":
            lead_id = request.form.get("lead_id", type=int)
            lead = Lead.query.get(lead_id) if lead_id else None
            if not lead:
                flash("Lead not found.", "error")
                return redirect(url_for("crm.lead_list"))
            db.session.delete(lead)
            db.session.commit()
            flash("Lead deleted.", "success")
            return redirect(url_for("crm.lead_list"))

        if action == "convert_lead_to_opportunity":
            lead_id = request.form.get("lead_id", type=int)
            lead = Lead.query.get(lead_id) if lead_id else None
            if not lead:
                flash("Lead not found.", "error")
                return redirect(url_for("crm.lead_list"))
            if not _is_valid_email(lead.email or ""):
                flash("Lead email is invalid. Please edit and fix email before conversion.", "error")
                return redirect(url_for("crm.lead_list"))

            existing_customer = Customer.query.filter_by(email=(lead.email or "").strip()).first()
            if existing_customer:
                lead.converted_customer_id = existing_customer.id
                lead.converted_at = datetime.utcnow()
                lead.lead_status = "converted"
                lead.is_active = False
                _log_opportunity_history(
                    existing_customer.id,
                    action="lead-converted",
                    changes_summary=(
                        f"Lead converted and linked to existing opportunity. "
                        f"Lead: {lead.lead_name or '-'} | Email: {lead.email or '-'} | Source: {lead.source or '-'}"
                    ),
                    tag_name="important",
                )
                db.session.commit()
                flash("Lead linked to existing opportunity (same email).", "success")
                return redirect(url_for("crm.opportunity_edit", customer_id=existing_customer.id))

            customer_name = (lead.lead_name or lead.company or (lead.email or "").split("@")[0] or "New Lead").strip()
            customer = Customer(
                account_name=lead.company,
                customer_name=customer_name,
                email=(lead.email or "").strip(),
                phone=lead.phone,
                city=lead.city,
                comment=lead.notes,
            )
            db.session.add(customer)
            db.session.commit()

            _log_opportunity_history(
                customer.id,
                action="lead-converted",
                changes_summary=(
                    f"Opportunity created from lead. Lead: {lead.lead_name or '-'} | Email: {lead.email or '-'} | "
                    f"Lead source: {lead.source or '-'} | "
                    f"Lead email status: {lead.last_email_status or '-'}"
                ),
                tag_name="important",
            )

            lead.converted_customer_id = customer.id
            lead.converted_at = datetime.utcnow()
            lead.lead_status = "converted"
            lead.is_active = False
            db.session.commit()
            flash("Lead converted to opportunity.", "success")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id))

    lead_q = (request.args.get("q") or "").strip()
    lead_state = (request.args.get("lead_state") or "all").strip()
    lead_email_state = (request.args.get("lead_email_state") or "all").strip()
    page = request.args.get("page", 1, type=int)

    leads_query = Lead.query
    if lead_q:
        like = f"%{lead_q}%"
        leads_query = leads_query.filter(
            db.or_(
                Lead.lead_name.ilike(like),
                Lead.email.ilike(like),
                Lead.company.ilike(like),
                Lead.phone.ilike(like),
                Lead.city.ilike(like),
                Lead.source.ilike(like),
            )
        )
    if lead_state == "converted":
        leads_query = leads_query.filter(Lead.lead_status == "converted")
    elif lead_state == "open":
        leads_query = leads_query.filter(Lead.lead_status != "converted")

    if lead_email_state == "emailed":
        leads_query = leads_query.filter(Lead.last_emailed_at.isnot(None))
    elif lead_email_state == "not_emailed":
        leads_query = leads_query.filter(Lead.last_emailed_at.is_(None))

    pagination = leads_query.order_by(Lead.created_at.desc()).paginate(page=page, per_page=10, error_out=False)
    return render_template(
        "leads_list.html",
        leads=pagination.items,
        pagination=pagination,
        lead_q=lead_q,
        lead_state=lead_state,
        lead_email_state=lead_email_state,
        leads_total_count=Lead.query.count(),
    )


@crm_bp.route("/references/add", methods=["POST"])
def reference_add_from_list():
    partner_name = (request.form.get("partner_name") or "").strip()
    contact_name = (request.form.get("contact_name") or "").strip()
    if not partner_name or not contact_name:
        flash("Partner name and contact name are required.", "error")
        return redirect(url_for("crm.reference_list"))

    customer_id = request.form.get("customer_id", type=int)
    assigned_customer = Customer.query.get(customer_id) if customer_id else None

    contact = PartnerReferenceContact(
        customer_id=assigned_customer.id if assigned_customer else None,
        partner_name=partner_name,
        contact_name=contact_name,
        designation=(request.form.get("designation") or "").strip(),
        email=(request.form.get("email") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        city=(request.form.get("city") or "").strip(),
        notes=(request.form.get("notes") or "").strip(),
        is_active=True,
    )
    db.session.add(contact)
    db.session.commit()

    if assigned_customer:
        if not PartnerReferenceOpportunity.query.filter_by(
            reference_contact_id=contact.id,
            customer_id=assigned_customer.id,
        ).first():
            db.session.add(PartnerReferenceOpportunity(reference_contact_id=contact.id, customer_id=assigned_customer.id))
            db.session.commit()
        _log_opportunity_history(
            assigned_customer.id,
            action="reference-contact-added",
            changes_summary=f"Reference contact added from References page: {contact.contact_name} ({contact.partner_name}).",
            tag_name="important",
        )
        db.session.commit()

    flash("Reference created successfully.", "success")
    return redirect(url_for("crm.reference_list"))


@crm_bp.route("/references/<int:reference_id>/assign", methods=["POST"])
def reference_assign_from_list(reference_id):
    contact = PartnerReferenceContact.query.get_or_404(reference_id)
    old_customer_id = contact.customer_id

    customer_id = request.form.get("customer_id", type=int)
    new_customer = Customer.query.get(customer_id) if customer_id else None
    contact.customer_id = new_customer.id if new_customer else None
    if new_customer and not PartnerReferenceOpportunity.query.filter_by(
        reference_contact_id=contact.id,
        customer_id=new_customer.id,
    ).first():
        db.session.add(PartnerReferenceOpportunity(reference_contact_id=contact.id, customer_id=new_customer.id))
    db.session.commit()

    if old_customer_id and old_customer_id != contact.customer_id:
        old_customer = Customer.query.get(old_customer_id)
        if old_customer:
            _log_opportunity_history(
                old_customer.id,
                action="reference-unassigned",
                changes_summary=f"Reference contact unassigned: {contact.contact_name} ({contact.partner_name}).",
                tag_name="assign",
            )

    if contact.customer_id:
        _log_opportunity_history(
            contact.customer_id,
            action="reference-assigned",
            changes_summary=f"Reference contact assigned: {contact.contact_name} ({contact.partner_name}).",
            tag_name="assign",
        )
    db.session.commit()

    q = (request.form.get("q") or "").strip()
    partner = (request.form.get("partner") or "").strip()
    sort = (request.form.get("sort") or "latest_activity_desc").strip()
    page = request.form.get("page", type=int) or 1
    flash("Reference assignment updated.", "success")
    return redirect(url_for("crm.reference_list", q=q, partner=partner, sort=sort, page=page))


@crm_bp.route("/customers/new", methods=["GET", "POST"])
@crm_bp.route("/opportunities/new", methods=["GET", "POST"])
def opportunity_new():
    _ensure_default_statuses()
    _ensure_default_segments()
    _ensure_default_cloud_operators()
    status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
    segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
    cloud_options = OpportunityCloudOperator.query.filter_by(is_active=True).order_by(OpportunityCloudOperator.name.asc()).all()
    admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
    email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        customer_name = (request.form.get("customer_name") or "").strip()
        if not email or not customer_name:
            flash("Opportunity name and email are required.", "error")
            return render_template(
                "customer_form.html",
                customer=None,
                is_edit=False,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
            )

        if Customer.query.filter_by(email=email).first():
            flash("Opportunity with this email already exists.", "error")
            return render_template(
                "customer_form.html",
                customer=None,
                is_edit=False,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
            )

        selected_status = (request.form.get("deal_status") or "").strip()
        selected_segment = (request.form.get("segment") or "").strip()
        selected_cloud = (request.form.get("cloud") or "").strip()
        assigned_user_id = request.form.get("assign_to_user_id", type=int)
        send_welcome_email = bool(request.form.get("send_welcome_email"))
        welcome_template_id = request.form.get("welcome_template_id", type=int)
        assigned_user = None

        if selected_cloud and not OpportunityCloudOperator.query.filter_by(name=selected_cloud, is_active=True).first():
            flash("Please select a valid cloud operator.", "error")
            return render_template(
                "customer_form.html",
                customer=None,
                is_edit=False,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
            )

        if assigned_user_id:
            assigned_user = User.query.filter_by(id=assigned_user_id, is_active_user=True).first()
            if not assigned_user:
                flash("Please select a valid admin user.", "error")
                return render_template(
                    "customer_form.html",
                    customer=None,
                    is_edit=False,
                    status_options=status_options,
                    segment_options=segment_options,
                    admin_users=admin_users,
                    email_templates=email_templates,
                )

        if send_welcome_email and not welcome_template_id:
            flash("Please select a welcome email template.", "error")
            return render_template(
                "customer_form.html",
                customer=None,
                is_edit=False,
                status_options=status_options,
                segment_options=segment_options,
                admin_users=admin_users,
                email_templates=email_templates,
            )

        customer = Customer(
            account_name=(request.form.get("account_name") or "").strip(),
            customer_name=customer_name,
            email=email,
            phone=(request.form.get("phone") or "").strip(),
            cloud=selected_cloud,
            billing=(request.form.get("billing") or "").strip(),
            city=(request.form.get("city") or "").strip(),
            aws_id=(request.form.get("aws_id") or "").strip(),
            opportunity_id=(request.form.get("opportunity_id") or "").strip(),
            segment=selected_segment,
            deal_status=selected_status,
            comment=(request.form.get("comment") or "").strip(),
            next_action_planned=(request.form.get("next_action_planned") or "").strip(),
            assign_to_user_id=assigned_user_id,
        )

        db.session.add(customer)
        db.session.commit()

        _log_opportunity_history(
            customer.id,
            action="created",
            changes_summary="Opportunity created.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()

        if send_welcome_email:
            template = EmailTemplate.query.get(welcome_template_id)
            if template:
                macro_values = _build_template_macro_values_for_customer(
                    customer,
                    template,
                    recipient_email=customer.email,
                )
                rendered_subject = render_macros(template.subject_template, macro_values)
                rendered_body = render_macros(template.body_template, macro_values)

                email_service = EmailService(current_app)
                result = email_service.send_html_email(customer.email, rendered_subject, rendered_body)

                db.session.add(EmailLog(
                    customer_id=customer.id,
                    template_id=template.id,
                    recipient_email=customer.email,
                    email_type="welcome",
                    subject=rendered_subject,
                    body=rendered_body,
                    status=result.status,
                    error_message=result.error,
                ))
                _log_opportunity_history(
                    customer.id,
                    action="welcome-email-sent",
                    changes_summary=(
                        f"Welcome email processed to {customer.email}. "
                        f"Template: {template.name}. Subject: {rendered_subject}. Status: {result.status}."
                    ),
                    tag_name="email",
                )
                db.session.commit()

                if result.success or result.status == "dev-mode":
                    flash(f"Welcome email sent (status: {result.status}).", "success")
                else:
                    flash(f"Welcome email failed: {result.error}", "error")

                if assigned_user and assigned_user.email:
                    assign_result = email_service.send_html_email(assigned_user.email, rendered_subject, rendered_body)
                    db.session.add(EmailLog(
                        customer_id=customer.id,
                        template_id=template.id,
                        recipient_email=assigned_user.email,
                        email_type="welcome-assigned",
                        subject=rendered_subject,
                        body=rendered_body,
                        status=assign_result.status,
                        error_message=assign_result.error,
                    ))
                    _log_opportunity_history(
                        customer.id,
                        action="welcome-email-assigned-sent",
                        changes_summary=(
                            f"Welcome email processed to assigned user {assigned_user.email}. "
                            f"Template: {template.name}. Subject: {rendered_subject}. Status: {assign_result.status}."
                        ),
                        tag_name="email",
                    )
                    db.session.commit()

                    if assign_result.success or assign_result.status == "dev-mode":
                        flash(f"Welcome email also sent to assigned user ({assigned_user.email}).", "success")
                    else:
                        flash(f"Assigned user welcome email failed: {assign_result.error}", "error")
                elif assigned_user and not assigned_user.email:
                    flash("Assigned user has no email. Welcome email sent only to customer.", "error")

        flash("Opportunity added successfully.", "success")
        return redirect(url_for("crm.opportunity_list"))

    return render_template(
        "customer_form.html",
        customer=None,
        is_edit=False,
        status_options=status_options,
        segment_options=segment_options,
        cloud_options=cloud_options,
        admin_users=admin_users,
        email_templates=email_templates,
        history_entries=[],
    )


@crm_bp.route("/customers/new", methods=["GET", "POST"])
def customer_new():
    return opportunity_new()


@crm_bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@crm_bp.route("/opportunities/<int:customer_id>/edit", methods=["GET", "POST"])
def opportunity_edit(customer_id):
    _ensure_default_statuses()
    _ensure_default_segments()
    _ensure_default_cloud_operators()
    customer = Customer.query.get_or_404(customer_id)
    status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
    segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
    cloud_options = OpportunityCloudOperator.query.filter_by(is_active=True).order_by(OpportunityCloudOperator.name.asc()).all()
    admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
    email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
    history_entries = OpportunityHistory.query.filter_by(customer_id=customer.id).order_by(OpportunityHistory.created_at.desc()).all()
    history_tag_colors = _tag_color_map()
    update_tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
    gathering_entries = GatheringServerDetail.query.filter_by(customer_id=customer.id).order_by(GatheringServerDetail.created_at.desc()).all()
    file_nas_entries = GatheringFileNasDetail.query.filter_by(customer_id=customer.id).order_by(GatheringFileNasDetail.created_at.desc()).all()
    block_storage_entries = GatheringBlockStorageDetail.query.filter_by(customer_id=customer.id).order_by(GatheringBlockStorageDetail.created_at.desc()).all()
    documents = CustomerDocument.query.filter_by(customer_id=customer.id).order_by(CustomerDocument.created_at.desc()).all()
    customer_diagrams = CustomerDiagram.query.filter_by(customer_id=customer.id).order_by(CustomerDiagram.created_at.desc()).all()
    gathering_requests = GatheringRequest.query.filter_by(customer_id=customer.id).order_by(GatheringRequest.created_at.desc()).all()
    mapped_ref_ids = [
        row.reference_contact_id
        for row in PartnerReferenceOpportunity.query.filter_by(customer_id=customer.id).all()
    ]
    if mapped_ref_ids:
        reference_contacts = (
            PartnerReferenceContact.query
            .filter(
                db.or_(
                    PartnerReferenceContact.customer_id == customer.id,
                    PartnerReferenceContact.id.in_(mapped_ref_ids),
                )
            )
            .order_by(PartnerReferenceContact.created_at.desc())
            .all()
        )
    else:
        reference_contacts = PartnerReferenceContact.query.filter_by(customer_id=customer.id).order_by(PartnerReferenceContact.created_at.desc()).all()
    all_reference_contacts = PartnerReferenceContact.query.order_by(
        PartnerReferenceContact.partner_name.asc(),
        PartnerReferenceContact.contact_name.asc(),
    ).all()
    assigned_reference_ids = {r.id for r in reference_contacts}
    ref_activity_map = {}
    if reference_contacts:
        ref_ids = [r.id for r in reference_contacts]
        ref_activities = (
            PartnerReferenceActivity.query
            .filter(PartnerReferenceActivity.reference_contact_id.in_(ref_ids))
            .order_by(PartnerReferenceActivity.created_at.desc())
            .all()
        )
        for activity in ref_activities:
            ref_activity_map.setdefault(activity.reference_contact_id, []).append(activity)

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        customer_name = (request.form.get("customer_name") or "").strip()
        if not email or not customer_name:
            flash("Opportunity name and email are required.", "error")
            return render_template(
                "customer_form.html",
                customer=customer,
                is_edit=True,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
                history_entries=history_entries,
                history_tag_colors=history_tag_colors,
                update_tags=update_tags,
                gathering_entries=gathering_entries,
                file_nas_entries=file_nas_entries,
                block_storage_entries=block_storage_entries,
                documents=documents,
                gathering_requests=gathering_requests,
                reference_contacts=reference_contacts,
                ref_activity_map=ref_activity_map,
                all_reference_contacts=all_reference_contacts,
                assigned_reference_ids=assigned_reference_ids,
                active_tab='info',
                base_url=current_app.config.get('APP_BASE_URL', 'http://127.0.0.1:5000'),
            )

        duplicate = Customer.query.filter(Customer.email == email, Customer.id != customer.id).first()
        if duplicate:
            flash("Another opportunity already uses this email.", "error")
            return render_template(
                "customer_form.html",
                customer=customer,
                is_edit=True,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
                history_entries=history_entries,
                history_tag_colors=history_tag_colors,
                update_tags=update_tags,
                gathering_entries=gathering_entries,
                file_nas_entries=file_nas_entries,
                block_storage_entries=block_storage_entries,
                documents=documents,
                gathering_requests=gathering_requests,
                reference_contacts=reference_contacts,
                ref_activity_map=ref_activity_map,
                all_reference_contacts=all_reference_contacts,
                assigned_reference_ids=assigned_reference_ids,
                active_tab='info',
                base_url=current_app.config.get('APP_BASE_URL', 'http://127.0.0.1:5000'),
            )

        new_values = {
            "account_name": (request.form.get("account_name") or "").strip(),
            "customer_name": customer_name,
            "email": email,
            "phone": (request.form.get("phone") or "").strip(),
            "cloud": (request.form.get("cloud") or "").strip(),
            "billing": (request.form.get("billing") or "").strip(),
            "city": (request.form.get("city") or "").strip(),
            "aws_id": (request.form.get("aws_id") or "").strip(),
            "opportunity_id": (request.form.get("opportunity_id") or "").strip(),
            "segment": (request.form.get("segment") or "").strip(),
            "deal_status": (request.form.get("deal_status") or "").strip(),
            "comment": (request.form.get("comment") or "").strip(),
            "next_action_planned": (request.form.get("next_action_planned") or "").strip(),
            "assign_to_user_id": request.form.get("assign_to_user_id", type=int),
        }

        field_labels = {
            "account_name": "Account Name",
            "customer_name": "Customer Name",
            "email": "Email",
            "phone": "Phone",
            "cloud": "Cloud",
            "billing": "Billing Address",
            "city": "City",
            "aws_id": "Cloud ID",
            "opportunity_id": "Opportunity ID",
            "segment": "Segment",
            "deal_status": "Status",
            "comment": "Comment",
            "next_action_planned": "Next Action Planned",
            "assign_to_user_id": "Assign To",
        }

        changed_lines = []
        for field, new_val in new_values.items():
            old_val = getattr(customer, field)
            if (old_val or "") != (new_val or ""):
                changed_lines.append(f"{field_labels[field]}: '{old_val or ''}' -> '{new_val or ''}'")

        if not changed_lines:
            flash("No changes detected.", "error")
            return render_template(
                "customer_form.html",
                customer=customer,
                is_edit=True,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
                history_entries=history_entries,
                history_tag_colors=history_tag_colors,
                update_tags=update_tags,
                gathering_entries=gathering_entries,
                file_nas_entries=file_nas_entries,
                block_storage_entries=block_storage_entries,
                documents=documents,
                gathering_requests=gathering_requests,
                reference_contacts=reference_contacts,
                ref_activity_map=ref_activity_map,
                all_reference_contacts=all_reference_contacts,
                assigned_reference_ids=assigned_reference_ids,
                active_tab='info',
                base_url=current_app.config.get('APP_BASE_URL', 'http://127.0.0.1:5000'),
            )

        change_remark = (request.form.get("change_remark") or "").strip()
        if not change_remark:
            flash("Remark is required when making changes.", "error")
            return render_template(
                "customer_form.html",
                customer=customer,
                is_edit=True,
                status_options=status_options,
                segment_options=segment_options,
                cloud_options=cloud_options,
                admin_users=admin_users,
                email_templates=email_templates,
                history_entries=history_entries,
                history_tag_colors=history_tag_colors,
                update_tags=update_tags,
                gathering_entries=gathering_entries,
                file_nas_entries=file_nas_entries,
                block_storage_entries=block_storage_entries,
                documents=documents,
                gathering_requests=gathering_requests,
                reference_contacts=reference_contacts,
                ref_activity_map=ref_activity_map,
                all_reference_contacts=all_reference_contacts,
                assigned_reference_ids=assigned_reference_ids,
                active_tab='info',
                base_url=current_app.config.get('APP_BASE_URL', 'http://127.0.0.1:5000'),
            )

        for field, new_val in new_values.items():
            setattr(customer, field, new_val)

        db.session.commit()

        _log_opportunity_history(
            customer.id,
            action="edited",
            changes_summary="\n".join(changed_lines),
            remark=change_remark,
        )
        db.session.commit()

        flash("Opportunity updated successfully.", "success")
        return redirect(url_for("crm.opportunity_list"))

    return render_template(
        "customer_form.html",
        customer=customer,
        is_edit=True,
        status_options=status_options,
        segment_options=segment_options,
        cloud_options=cloud_options,
        admin_users=admin_users,
        email_templates=email_templates,
        history_entries=history_entries,
        history_tag_colors=history_tag_colors,
        update_tags=update_tags,
        gathering_entries=gathering_entries,
        file_nas_entries=file_nas_entries,
        block_storage_entries=block_storage_entries,
        documents=documents,
        customer_diagrams=customer_diagrams,
        gathering_requests=gathering_requests,
        reference_contacts=reference_contacts,
        ref_activity_map=ref_activity_map,
        all_reference_contacts=all_reference_contacts,
        assigned_reference_ids=assigned_reference_ids,
        teams_auto_available=TeamsService(current_app).is_configured(),
        active_tab=request.args.get("tab", "info"),
        base_url=current_app.config.get("APP_BASE_URL", "http://127.0.0.1:5000"),
    )


@crm_bp.route("/opportunities/<int:customer_id>/reference-contacts/add", methods=["POST"])
def reference_contact_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    partner_name = (request.form.get("partner_name") or "").strip()
    contact_name = (request.form.get("contact_name") or "").strip()
    if not partner_name or not contact_name:
        flash("Partner name and contact name are required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    contact = PartnerReferenceContact(
        customer_id=customer.id,
        partner_name=partner_name,
        contact_name=contact_name,
        designation=(request.form.get("designation") or "").strip(),
        email=(request.form.get("email") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        city=(request.form.get("city") or "").strip(),
        notes=(request.form.get("notes") or "").strip(),
        is_active=True,
    )
    db.session.add(contact)
    db.session.commit()
    if not PartnerReferenceOpportunity.query.filter_by(
        reference_contact_id=contact.id,
        customer_id=customer.id,
    ).first():
        db.session.add(PartnerReferenceOpportunity(reference_contact_id=contact.id, customer_id=customer.id))
        db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="reference-contact-added",
        changes_summary=f"Reference contact added: {contact.contact_name} ({contact.partner_name}).",
        tag_name="important",
    )
    db.session.commit()
    flash("Reference contact added.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/edit", methods=["POST"])
def reference_contact_edit(customer_id, contact_id):
    customer = Customer.query.get_or_404(customer_id)
    contact = PartnerReferenceContact.query.filter_by(id=contact_id, customer_id=customer.id).first_or_404()

    partner_name = (request.form.get("partner_name") or "").strip()
    contact_name = (request.form.get("contact_name") or "").strip()
    if not partner_name or not contact_name:
        flash("Partner name and contact name are required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    contact.partner_name = partner_name
    contact.contact_name = contact_name
    contact.designation = (request.form.get("designation") or "").strip()
    contact.email = (request.form.get("email") or "").strip()
    contact.phone = (request.form.get("phone") or "").strip()
    contact.city = (request.form.get("city") or "").strip()
    contact.notes = (request.form.get("notes") or "").strip()
    contact.is_active = bool(request.form.get("is_active"))
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="reference-contact-updated",
        changes_summary=f"Reference contact updated: {contact.contact_name} ({contact.partner_name}).",
        tag_name="update",
    )
    db.session.commit()
    flash("Reference contact updated.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/delete", methods=["POST"])
def reference_contact_delete(customer_id, contact_id):
    customer = Customer.query.get_or_404(customer_id)
    contact = PartnerReferenceContact.query.filter_by(id=contact_id, customer_id=customer.id).first_or_404()
    contact_name = contact.contact_name
    partner_name = contact.partner_name
    PartnerReferenceActivity.query.filter_by(reference_contact_id=contact.id).delete(synchronize_session=False)
    PartnerReferenceOpportunity.query.filter_by(reference_contact_id=contact.id).delete(synchronize_session=False)
    db.session.delete(contact)
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="reference-contact-deleted",
        changes_summary=f"Reference contact deleted: {contact_name} ({partner_name}).",
        tag_name="update",
    )
    db.session.commit()
    flash("Reference contact deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/activities/add", methods=["POST"])
def reference_contact_activity_add(customer_id, contact_id):
    customer = Customer.query.get_or_404(customer_id)
    contact = PartnerReferenceContact.query.filter_by(id=contact_id, customer_id=customer.id).first_or_404()

    summary = (request.form.get("summary") or "").strip()
    if not summary:
        flash("Activity summary is required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    activity_type = (request.form.get("activity_type") or "note").strip().lower()
    if activity_type not in {"call", "meeting", "email", "whatsapp", "note"}:
        activity_type = "note"

    activity_date = None
    activity_date_raw = (request.form.get("activity_date") or "").strip()
    if activity_date_raw:
        try:
            activity_date = datetime.strptime(activity_date_raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            activity_date = None

    activity = PartnerReferenceActivity(
        reference_contact_id=contact.id,
        customer_id=customer.id,
        activity_type=activity_type,
        activity_date=activity_date,
        summary=summary,
        details=(request.form.get("details") or "").strip(),
        next_action=(request.form.get("next_action") or "").strip(),
        created_by=(current_user.username if getattr(current_user, "is_authenticated", False) else "system"),
    )
    db.session.add(activity)
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="reference-activity-added",
        changes_summary=f"Reference activity ({activity_type}) added for {contact.contact_name}: {summary}",
        tag_name="meeting" if activity_type in {"call", "meeting"} else "update",
    )
    db.session.commit()
    flash("Reference activity added.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/references/assign", methods=["POST"])
def opportunity_reference_assign(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    reference_contact_id = request.form.get("reference_contact_id", type=int)
    reference = PartnerReferenceContact.query.get(reference_contact_id) if reference_contact_id else None
    if not reference:
        flash("Please select a valid reference contact.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    existing = PartnerReferenceOpportunity.query.filter_by(
        reference_contact_id=reference.id,
        customer_id=customer.id,
    ).first()
    if existing:
        flash("Reference is already assigned to this opportunity.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    db.session.add(PartnerReferenceOpportunity(reference_contact_id=reference.id, customer_id=customer.id))
    db.session.commit()
    _log_opportunity_history(
        customer.id,
        action="reference-assigned",
        changes_summary=f"Reference assigned to opportunity: {reference.contact_name} ({reference.partner_name}).",
        tag_name="assign",
    )
    db.session.commit()
    flash("Reference assigned to opportunity.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/references/<int:reference_id>/unassign", methods=["POST"])
def opportunity_reference_unassign(customer_id, reference_id):
    customer = Customer.query.get_or_404(customer_id)
    reference = PartnerReferenceContact.query.get_or_404(reference_id)

    link = PartnerReferenceOpportunity.query.filter_by(
        reference_contact_id=reference.id,
        customer_id=customer.id,
    ).first()

    changed = False
    if link:
        db.session.delete(link)
        changed = True
    elif reference.customer_id == customer.id:
        reference.customer_id = None
        changed = True

    if not changed:
        flash("Reference is not assigned to this opportunity.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    db.session.commit()
    _log_opportunity_history(
        customer.id,
        action="reference-unassigned",
        changes_summary=f"Reference unassigned from opportunity: {reference.contact_name} ({reference.partner_name}).",
        tag_name="assign",
    )
    db.session.commit()
    flash("Reference unassigned from opportunity.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/reference-activities/<int:activity_id>/delete", methods=["POST"])
def reference_contact_activity_delete(customer_id, activity_id):
    customer = Customer.query.get_or_404(customer_id)
    activity = PartnerReferenceActivity.query.filter_by(id=activity_id, customer_id=customer.id).first_or_404()
    activity_text = activity.summary
    db.session.delete(activity)
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="reference-activity-deleted",
        changes_summary=f"Reference activity deleted: {activity_text}",
        tag_name="update",
    )
    db.session.commit()
    flash("Reference activity deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))


@crm_bp.route("/opportunities/<int:customer_id>/status", methods=["POST"])
def opportunity_update_status(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    status_name = (request.form.get("deal_status") or "").strip()
    change_remark = (request.form.get("change_remark") or "").strip()
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    assigned_to = request.args.get("assigned_to", type=int)

    valid_status = OpportunityStatus.query.filter_by(name=status_name, is_active=True).first()
    if not valid_status:
        flash("Please select a valid status.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    if not change_remark:
        flash("Remark is required for status change.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    old_status = customer.deal_status or ""
    if old_status == status_name:
        flash("No status change detected.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    customer.deal_status = status_name
    db.session.commit()
    _log_opportunity_history(
        customer.id,
        action="status-updated",
        changes_summary=f"Status: '{old_status}' -> '{status_name}'",
        remark=change_remark,
    )
    db.session.commit()
    flash("Opportunity status updated.", "success")
    return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))


@crm_bp.route("/opportunities/<int:customer_id>/segment", methods=["POST"])
def opportunity_update_segment(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    segment_name = (request.form.get("segment") or "").strip()
    change_remark = (request.form.get("change_remark") or "").strip()
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    assigned_to = request.args.get("assigned_to", type=int)

    valid_segment = OpportunitySegment.query.filter_by(name=segment_name, is_active=True).first()
    if not valid_segment:
        flash("Please select a valid segment.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    if not change_remark:
        flash("Remark is required for segment change.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    old_segment = customer.segment or ""
    if old_segment == segment_name:
        flash("No segment change detected.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    customer.segment = segment_name
    db.session.commit()
    _log_opportunity_history(
        customer.id,
        action="segment-updated",
        changes_summary=f"Segment: '{old_segment}' -> '{segment_name}'",
        remark=change_remark,
    )
    db.session.commit()
    flash("Opportunity segment updated.", "success")
    return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))


@crm_bp.route("/opportunities/<int:customer_id>/assign", methods=["POST"])
def opportunity_update_assign(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    new_user_id = request.form.get("assign_to_user_id", type=int)
    change_remark = (request.form.get("change_remark") or "").strip()
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    assigned_to = request.args.get("assigned_to", type=int)

    if not change_remark:
        flash("Remark is required for assignee change.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    if new_user_id:
        user = User.query.filter_by(id=new_user_id, is_active_user=True).first()
        if not user:
            flash("Please select a valid admin user.", "error")
            return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    old_user_id = customer.assign_to_user_id
    if (old_user_id or None) == (new_user_id or None):
        flash("No assignee change detected.", "error")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    old_user = User.query.get(old_user_id) if old_user_id else None
    new_user = User.query.get(new_user_id) if new_user_id else None
    old_name = old_user.username if old_user else ""
    new_name = new_user.username if new_user else ""

    customer.assign_to_user_id = new_user_id
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="assign-updated",
        changes_summary=f"Assign To: '{old_name}' -> '{new_name}'",
        remark=change_remark,
    )
    db.session.commit()

    flash("Opportunity assignee updated.", "success")
    return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))


@crm_bp.route("/opportunities/<int:customer_id>/history", methods=["GET"])
def opportunity_history(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    change_entries = OpportunityHistory.query.filter_by(customer_id=customer.id).all()
    email_entries = EmailLog.query.filter_by(customer_id=customer.id).all()
    tag_colors = _tag_color_map()

    timeline = []

    for h in change_entries:
        timeline.append(
            {
                "_dt": h.created_at,
                "created_at": h.created_at.strftime("%Y-%m-%d %H:%M"),
                "changed_by": h.changed_by or "system",
                "action": h.action,
                "tag": (h.tag_name or _derive_tag_from_action(h.action)).lower(),
                "tag_color": tag_colors.get((h.tag_name or _derive_tag_from_action(h.action)).lower(), "#6b7280"),
                "changes_summary": h.changes_summary,
                "remark": h.remark or "",
            }
        )

    for e in email_entries:
        template_name = e.template.name if e.template else "Custom Email"
        recipient = e.recipient_email or (e.customer.email if e.customer else "")
        summary = (
            f"Email to {recipient} | Template: {template_name} | "
            f"Status: {e.status} | Subject: {e.subject}"
        )
        timeline.append(
            {
                "_dt": e.created_at,
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "changed_by": "system",
                "action": f"email-{e.email_type}",
                "tag": "email",
                "tag_color": tag_colors.get("email", "#1d4ed8"),
                "changes_summary": summary,
                "remark": e.error_message or "",
            }
        )

    timeline.sort(key=lambda x: x["_dt"], reverse=True)

    for item in timeline:
        item.pop("_dt", None)

    return jsonify(
        success=True,
        customer_name=customer.customer_name,
        available_tags=[
            {"name": t.name, "color": t.color}
            for t in OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
        ],
        items=timeline,
    )


@crm_bp.route("/opportunities/<int:customer_id>/history/add", methods=["POST"])
@login_required
def opportunity_history_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}
    update_text = (data.get("update_text") or "").strip()
    tag_name = (data.get("tag_name") or "").strip().lower()
    remark = (data.get("remark") or "").strip()

    if not update_text:
        return jsonify(success=False, message="Update text is required."), 400

    valid_tag = OpportunityUpdateTag.query.filter_by(name=tag_name, is_active=True).first() if tag_name else None
    selected_tag = valid_tag.name.lower() if valid_tag else "update"

    _log_opportunity_history(
        customer.id,
        action="manual-update",
        changes_summary=update_text,
        remark=remark or None,
        tag_name=selected_tag,
    )
    db.session.commit()
    return jsonify(success=True, message="Update added successfully.")


@crm_bp.route("/opportunities/<int:customer_id>/history/add-form", methods=["POST"])
@login_required
def opportunity_history_add_form(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    update_text = (request.form.get("update_text") or "").strip()
    tag_name = (request.form.get("tag_name") or "").strip().lower()
    remark = (request.form.get("remark") or "").strip()

    if not update_text:
        flash("Update/comment text is required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="history"))

    valid_tag = OpportunityUpdateTag.query.filter_by(name=tag_name, is_active=True).first() if tag_name else None
    selected_tag = valid_tag.name.lower() if valid_tag else "update"

    _log_opportunity_history(
        customer.id,
        action="manual-update",
        changes_summary=update_text,
        remark=remark or None,
        tag_name=selected_tag,
    )
    db.session.commit()
    flash("Manual update added.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="history"))


# ══════════════════════════════════════════════════════════════
#  SOW — Statement of Work
# ══════════════════════════════════════════════════════════════

SOW_DEFAULT_SECTIONS = [
        (
                "Proposal Information",
                """
<h2>Proposal Information</h2>
<div><strong>Proposal For</strong></div>
<div>{{customer_name}}</div>
<div>{{company_name}}</div>
<div style='margin-top:8px;'><strong>Submitted By</strong></div>
<div>{{ambifo_company_name}}</div>
<div>{{ambifo_locations}}</div>
<div style='margin-top:8px;'><strong>SOW Title</strong></div>
<div>{{sow_title}}</div>
<div style='margin-top:4px;'><strong>Date</strong></div>
<div>{{sow_date}}</div>
<div style='margin-top:4px;'><strong>Version</strong></div>
<div>{{sow_version}}</div>
<table style='width:100%;border-collapse:collapse;margin-top:12px;border:1px solid #e2e8f0;'>
    <thead>
        <tr>
            <th style='text-align:left;padding:8px;border-bottom:1px solid #e2e8f0;background:#f8fafc;'>Field</th>
            <th style='text-align:left;padding:8px;border-bottom:1px solid #e2e8f0;background:#f8fafc;'>Details</th>
        </tr>
    </thead>
    <tbody>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Signed Between</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{ambifo_company_name}} &amp; {{company_name}}</td></tr>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Customer Name</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{customer_name}}</td></tr>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Customer Email</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{customer_email}}</td></tr>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Customer Phone</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{customer_phone}}</td></tr>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Cloud Platform</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{cloud_platform}}</td></tr>
        <tr><td style='padding:8px;border-top:1px solid #e2e8f0;'>Ambifo Contact</td><td style='padding:8px;border-top:1px solid #e2e8f0;'>{{ambifo_support_email}} | {{ambifo_website}}</td></tr>
    </tbody>
</table>
                """.strip(),
        ),
    ("About Ambifo", "<p>Ambifo Technology Pvt Ltd is an AWS &amp; Azure Premier Consulting Partner, providing cloud consulting, implementation, and managed services.</p>"),
    ("Offerings", "<p>Cloud migration, managed services, DevOps, security, AI/ML and analytics services.</p>"),
    ("Business Background", "<p><strong>{{company_name}}</strong> is evaluating cloud transformation to improve scalability and resilience on <strong>{{cloud_platform}}</strong>.</p>"),
    ("Project Overview", "<p>This engagement covers migration/deployment for <strong>{{customer_name}}</strong> with implementation and support.</p>"),
    ("Problem Statement", "<p><strong>{{company_name}}</strong> currently faces scalability, cost, and operational challenges.</p>"),
    ("Document Objective", "<p>This SOW defines scope, deliverables, timelines and responsibilities.</p>"),
    ("Success Criteria", "<ul><li>Successful infrastructure provisioning</li><li>Testing and validation complete</li><li>Go-live sign-off</li></ul>"),
    ("Proposed Solution", "<p>Solution architecture, implementation approach, assumptions and out-of-scope items.</p>"),
    ("Scope & Schedule", "<p>Phased plan: discovery, provisioning, migration, testing and handover.</p>"),
    ("Project Governance", "<p>Steering, PM ownership, reporting model and escalation matrix.</p>"),
    ("Commercials / Terms / Sign-off", "<p>Pricing, terms &amp; conditions, and acceptance signatories.</p>"),
]

LEGACY_SOW_SECTION_FIELDS = [
    "section_about",
    "section_offerings",
    "section_business_background",
    "section_project_overview",
    "section_problem_statement",
    "section_document_objective",
    "section_success_criteria",
    "section_proposed_solution",
    "section_scope_schedule",
    "section_project_governance",
    "section_commercials_signoff",
]


def _get_template_sections(master_template):
    return (
        SOWMasterTemplateSection.query
        .filter_by(template_id=master_template.id)
        .order_by(SOWMasterTemplateSection.sequence_no.asc(), SOWMasterTemplateSection.id.asc())
        .all()
    )


def _ensure_template_sections(master_template):
    existing = _get_template_sections(master_template)
    existing_by_name = {(s.section_name or "").strip().lower(): s for s in existing}
    created_sections = []

    if not existing:
        for idx, (section_name, default_html) in enumerate(SOW_DEFAULT_SECTIONS, start=1):
            legacy_html = getattr(master_template, LEGACY_SOW_SECTION_FIELDS[idx - 1], None) if idx - 1 < len(LEGACY_SOW_SECTION_FIELDS) else None
            content = (legacy_html or "").strip() or default_html
            section = SOWMasterTemplateSection(
                template_id=master_template.id,
                section_name=section_name,
                sequence_no=idx,
                content_html=content,
            )
            db.session.add(section)
            created_sections.append(section)
        db.session.commit()
        return created_sections

    for idx, (section_name, default_html) in enumerate(SOW_DEFAULT_SECTIONS, start=1):
        key = (section_name or "").strip().lower()
        if key in existing_by_name:
            continue

        # Insert missing defaults at their canonical position instead of appending.
        for current in existing:
            if (current.sequence_no or 0) >= idx:
                current.sequence_no = (current.sequence_no or 0) + 1

        section = SOWMasterTemplateSection(
            template_id=master_template.id,
            section_name=section_name,
            sequence_no=idx,
            content_html=default_html,
        )
        db.session.add(section)
        created_sections.append(section)
        existing.append(section)
        existing_by_name[key] = section

    if created_sections:
        _normalize_template_section_sequence(master_template.id)
        db.session.commit()
        return _get_template_sections(master_template)

    return existing


def _normalize_template_section_sequence(template_id):
    sections = (
        SOWMasterTemplateSection.query
        .filter_by(template_id=template_id)
        .order_by(SOWMasterTemplateSection.sequence_no.asc(), SOWMasterTemplateSection.id.asc())
        .all()
    )
    for idx, section in enumerate(sections, start=1):
        section.sequence_no = idx


def _move_template_section_to_position(template_id, section_id, target_position):
    sections = (
        SOWMasterTemplateSection.query
        .filter_by(template_id=template_id)
        .order_by(SOWMasterTemplateSection.sequence_no.asc(), SOWMasterTemplateSection.id.asc())
        .all()
    )
    if not sections:
        return

    moving = next((s for s in sections if s.id == section_id), None)
    if not moving:
        return

    remaining = [s for s in sections if s.id != section_id]
    bounded_position = max(1, min(int(target_position or 1), len(sections)))
    insert_at = bounded_position - 1
    remaining.insert(insert_at, moving)

    for idx, section in enumerate(remaining, start=1):
        section.sequence_no = idx


def _get_sow_document_title_label(template_id):
    key = f"sow.template.{int(template_id)}.document_title"
    value = (SystemSetting.get_value(key, "") or "").strip()
    return value or "Statement of Work (SOW)"


def _set_sow_document_title_label(template_id, value):
    key = f"sow.template.{int(template_id)}.document_title"
    label = (value or "").strip() or "Statement of Work (SOW)"
    SystemSetting.set_value(key, label)


def _format_doc_ref_no(value=None, sow_id=None, ref_date=None):
    raw = (value or "").strip()
    if re.match(r"^AMBIFO-\d{6}-\d{3}$", raw, flags=re.IGNORECASE):
        return raw.upper()

    date_part = (ref_date or datetime.utcnow()).strftime("%d%m%y")

    if raw:
        m = re.search(r"(\d+)$", raw)
        if m:
            return f"AMBIFO-{date_part}-{int(m.group(1)):03d}"
        return raw
    if sow_id:
        try:
            return f"AMBIFO-{date_part}-{int(sow_id):03d}"
        except (TypeError, ValueError):
            pass
    return f"AMBIFO-{date_part}-000"


def _create_master_template(template_name, template_key):
    master = SOWMasterTemplate(
        template_name=template_name,
        template_key=template_key,
        updated_by=_actor_name(),
    )
    for idx, legacy_field in enumerate(LEGACY_SOW_SECTION_FIELDS):
        setattr(master, legacy_field, SOW_DEFAULT_SECTIONS[idx][1])
    master.content_html = ""
    return master


def _generate_unique_sow_template_key(base_text):
    base_key = re.sub(r"[^a-z0-9]+", "-", (base_text or "").lower()).strip("-") or "template"
    key = base_key
    seq = 2
    while SOWMasterTemplate.query.filter_by(template_key=key).first():
        key = f"{base_key}-{seq}"
        seq += 1
    return key


def _ensure_default_sow_master_template():
    existing = SOWMasterTemplate.query.order_by(SOWMasterTemplate.id.asc()).all()
    if not existing:
        master = _create_master_template("Default Template", "default")
        db.session.add(master)
        db.session.commit()
        return master

    changed = False
    for idx, master in enumerate(existing, start=1):
        if not (master.template_name or "").strip():
            master.template_name = "Default Template" if idx == 1 else f"Template {idx}"
            changed = True
        for i, legacy_field in enumerate(LEGACY_SOW_SECTION_FIELDS):
            if not getattr(master, legacy_field, None):
                setattr(master, legacy_field, SOW_DEFAULT_SECTIONS[i][1])
                changed = True
        _ensure_template_sections(master)
    if changed:
        db.session.commit()
    return existing[0]


def _normalize_selected_diagram_ids(customer_id, raw_ids):
    if raw_ids is None:
        return []

    parsed = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            try:
                parsed.append(int(item))
            except (TypeError, ValueError):
                continue
    elif isinstance(raw_ids, str):
        for token in raw_ids.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                parsed.append(int(token))
            except (TypeError, ValueError):
                continue
    else:
        try:
            parsed.append(int(raw_ids))
        except (TypeError, ValueError):
            pass

    if not parsed:
        return []

    valid_ids = {
        d.id for d in CustomerDiagram.query.filter(
            CustomerDiagram.customer_id == customer_id,
            CustomerDiagram.is_active == True,
            CustomerDiagram.id.in_(parsed),
        ).all()
    }
    return [item for item in parsed if item in valid_ids]


def _selected_diagrams_for_customer(customer_id, selected_diagram_ids):
    if not selected_diagram_ids:
        return (
            CustomerDiagram.query
            .filter_by(customer_id=customer_id, is_active=True)
            .order_by(CustomerDiagram.created_at.asc())
            .all()
        )

    return (
        CustomerDiagram.query
        .filter(
            CustomerDiagram.customer_id == customer_id,
            CustomerDiagram.is_active == True,
            CustomerDiagram.id.in_(selected_diagram_ids),
        )
        .order_by(CustomerDiagram.created_at.asc())
        .all()
    )


def _render_sow_template_for_customer(template_html, customer, selected_diagrams=None, sow=None):
    safe_customer_name = html.escape(customer.customer_name or "")
    safe_company_name = html.escape(customer.account_name or customer.customer_name or "")
    safe_cloud = html.escape(customer.cloud or "AWS / Azure")
    safe_email = html.escape(customer.email or "")
    safe_phone = html.escape(customer.phone or "-")
    safe_today = datetime.utcnow().strftime("%d %B, %Y")
    safe_sow_title = html.escape((getattr(sow, "sow_title", None) or f"Cloud Migration SOW — {customer.customer_name}").strip())
    safe_sow_date = html.escape((getattr(sow, "sow_date", None) or safe_today).strip())
    safe_sow_version = html.escape((getattr(sow, "version", None) or "1.0").strip())
    safe_doc_ref_no = html.escape(
        _format_doc_ref_no(
            sow_id=getattr(sow, "id", None),
            ref_date=getattr(sow, "created_at", None),
        )
    )
    template_id = getattr(sow, "master_template_id", None)
    safe_document_title_label = html.escape(
        _get_sow_document_title_label(template_id) if template_id else "Statement of Work (SOW)"
    )

    rendered = template_html or ""
    replacements = {
        "{{customer_name}}": safe_customer_name,
        "{{company_name}}": safe_company_name,
        "{{cloud_platform}}": safe_cloud,
        "{{customer_email}}": safe_email,
        "{{customer_phone}}": safe_phone,
        "{{today}}": safe_today,
        "{{sow_title}}": safe_sow_title,
        "{{sow_date}}": safe_sow_date,
        "{{sow_version}}": safe_sow_version,
        "{{doc_ref_no}}": safe_doc_ref_no,
        "{{document_title_label}}": safe_document_title_label,
        "{{ambifo_company_name}}": "Ambifo Technology Pvt Ltd",
        "{{ambifo_locations}}": "Bangalore | Mumbai | Delhi",
        "{{ambifo_website}}": "www.ambifo.com",
        "{{ambifo_support_email}}": "support@ambifo.com",
        "{{ambifo_support_phone}}": "+91 9148419502",
        "{{ambifo_address}}": "Building No 674, 18th Main, 3rd Phase, Front of New Land ISRO Quarter, Domlur, Bangalore - 560071",
        "{{ambifo_linkedin}}": "https://www.linkedin.com/company/ambifo-technology",
    }

    selected_diagrams = selected_diagrams or []
    diagram_html_blocks = []
    for diagram in selected_diagrams:
        macro_key = (diagram.macro_key or "").strip()
        if not macro_key:
            continue
        replacements[f"{{{{{macro_key}}}}}"] = diagram.diagram_content or ""
        safe_name = html.escape(diagram.diagram_name or "Diagram")
        diagram_html_blocks.append(f"<h4>{safe_name}</h4>{diagram.diagram_content or ''}")

    replacements["{{selected_diagrams_html}}"] = "\n".join(diagram_html_blocks)

    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _build_rendered_sow_sections(master_template, customer, selected_diagrams=None, sow=None):
    sections = _ensure_template_sections(master_template)
    rendered_parts = []
    for idx, section in enumerate(sections, start=1):
        title = html.escape((section.section_name or "Section").strip())
        body = _render_sow_template_for_customer(
            section.content_html or "",
            customer,
            selected_diagrams=selected_diagrams,
            sow=sow,
        )
        rendered_parts.append(f"<h1>{idx}. {title}</h1>{body}")
    return "\n".join(rendered_parts)


def _append_missing_rendered_sow_sections(existing_html, master_template, customer, selected_diagrams=None, sow=None):
    sections = _ensure_template_sections(master_template)
    source_html = existing_html or ""
    missing_parts = []

    for idx, section in enumerate(sections, start=1):
        title = (section.section_name or "Section").strip()
        if not title:
            continue

        # Detect section by heading text (sequence number may vary over time).
        heading_re = re.compile(
            rf"<h1[^>]*>\s*\d+\.\s*{re.escape(title)}\s*</h1>",
            flags=re.IGNORECASE,
        )
        if heading_re.search(source_html):
            continue

        rendered_body = _render_sow_template_for_customer(
            section.content_html or "",
            customer,
            selected_diagrams=selected_diagrams,
            sow=sow,
        )
        safe_title = html.escape(title)
        missing_parts.append(f"<h1>{idx}. {safe_title}</h1>{rendered_body}")

    if not missing_parts:
        return source_html, False

    separator = "\n" if source_html.strip() else ""
    return f"{source_html}{separator}{'\n'.join(missing_parts)}", True


def _html_to_docx_body(doc, html_content):
    """Convert basic Quill HTML to python-docx paragraph elements."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content or "", "html.parser")

    def _add_inline(para, elem):
        for node in elem.children:
            if isinstance(node, str):
                if node:
                    para.add_run(node)
            elif node.name in ("strong", "b"):
                run = para.add_run(node.get_text())
                run.bold = True
            elif node.name in ("em", "i"):
                run = para.add_run(node.get_text())
                run.italic = True
            elif node.name == "u":
                run = para.add_run(node.get_text())
                run.underline = True
            elif node.name == "br":
                para.add_run("\n")
            elif node.name:
                para.add_run(node.get_text())

    for el in soup.children:
        if not hasattr(el, "name") or not el.name:
            if isinstance(el, str) and el.strip():
                doc.add_paragraph(el.strip())
            continue
        tag = el.name
        if tag in ("h1", "h2", "h3", "h4"):
            doc.add_heading(el.get_text(), level=int(tag[1]))
        elif tag == "p":
            text = el.get_text()
            if text.strip():
                p = doc.add_paragraph()
                _add_inline(p, el)
        elif tag in ("ul", "ol"):
            style = "List Bullet" if tag == "ul" else "List Number"
            for li in el.find_all("li", recursive=False):
                p = doc.add_paragraph(style=style)
                _add_inline(p, li)
        elif tag == "blockquote":
            from docx.shared import Pt
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(36)
            _add_inline(p, el)
        elif tag in ("div", "section"):
            _html_to_docx_body(doc, str(el.decode_contents()))


def _generate_sow_docx(customer, sow_title, sow_date, sow_version, content_html, document_title_label="Statement of Work (SOW)", doc_ref_no=""):
    """Build and return a DOCX file as bytes."""
    from io import BytesIO
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = Inches(1)
    sec.right_margin = Inches(1)
    sec.top_margin = Inches(1)
    sec.bottom_margin = Inches(1)

    BRAND_BLUE = RGBColor(0x0A, 0x1F, 0x5C)

    def _heading_run(para, text, size, color=None, bold=True):
        run = para.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = color

    # ── Cover Page / Header Branding ────────────────────────
    logo_path = os.path.join(current_app.root_path, "static", "ambifologo.png")
    if os.path.exists(logo_path):
        try:
            logo_para = doc.add_paragraph()
            logo_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            logo_para.add_run().add_picture(logo_path, width=Inches(2.2))
        except Exception:
            # Keep DOCX export resilient even if image embedding fails.
            pass

    comp_para = doc.add_paragraph()
    comp_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _heading_run(comp_para, "AMBIFO TECHNOLOGY PVT LTD", 12, BRAND_BLUE)

    caps_para = doc.add_paragraph()
    caps_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caps_para.add_run("Cloud Strategy | Migration & Modernization | DevOps | AI/ML").italic = True

    doc.add_paragraph()

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _heading_run(title_para, (document_title_label or "Statement of Work (SOW)").upper(), 22, BRAND_BLUE)

    doc.add_paragraph()

    info_lines = [
        ("Proposal For:", f"{customer.customer_name} — {customer.account_name or ''}"),
        ("Submitted By:", "Ambifo Technology Pvt Ltd"),
        ("Title:", sow_title or f"Cloud Migration SOW — {customer.customer_name}"),
        ("Doc Ref #:", _format_doc_ref_no(doc_ref_no)),
        ("Date:", sow_date or ""),
        ("Version:", sow_version or "1.0"),
        ("Customer Email:", customer.email or ""),
        ("Customer Phone:", customer.phone or "—"),
        ("Cloud Platform:", customer.cloud or "AWS / Azure"),
        ("Website:", "www.ambifo.com"),
        ("Support Email:", "support@ambifo.com"),
        ("Support Phone:", "+91 9148419502"),
        ("Address:", "Building No 674, 18th Main, 3rd Phase, Front of New Land ISRO Quarter, Domlur, Bangalore - 560071"),
        ("LinkedIn:", "https://www.linkedin.com/company/ambifo-technology"),
    ]
    for label, value in info_lines:
        p = doc.add_paragraph()
        run_l = p.add_run(f"{label} ")
        run_l.bold = True
        p.add_run(value)

    doc.add_page_break()

    # ── Body content (already sequence-assembled from template sections) ──
    _html_to_docx_body(doc, content_html)

    # ── Confidentiality footer ───────────────────────────────
    doc.add_paragraph()
    footer_p = doc.add_paragraph()
    footer_run = footer_p.add_run(
        "CONFIDENTIAL — This document and any attachments are confidential and intended solely "
        "for the use of the individual or entity to which it is addressed. "
        "Ambifo Technology Pvt Ltd | support@ambifo.com | www.ambifo.com | +91 9148419502"
    )
    footer_run.italic = True
    footer_run.font.size = Pt(8)

    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output.getvalue()


def _generate_sow_pdf(customer, sow_title, sow_date, sow_version, content_html, document_title_label="Statement of Work (SOW)", doc_ref_no=""):
    """Build and return a PDF file as bytes."""
    from io import BytesIO
    from bs4 import BeautifulSoup
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    def _normalize_text(value):
        return re.sub(r"\s+", " ", (value or "").strip())

    def _html_to_lines(raw_html):
        soup = BeautifulSoup(raw_html or "", "html.parser")
        lines = []
        for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
            txt = _normalize_text(el.get_text(" ", strip=True))
            if not txt:
                continue
            if el.name == "li":
                txt = f"- {txt}"
            lines.append(txt)
        if not lines:
            fallback = _normalize_text(soup.get_text(" ", strip=True))
            if fallback:
                lines.append(fallback)
        return lines

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    page_w, page_h = A4
    left = 46
    right = 46
    top = page_h - 48
    bottom = 52
    y = top
    max_w = page_w - left - right

    def _new_page():
        nonlocal y
        pdf.showPage()
        y = top

    def _draw_wrapped(text, font_name="Helvetica", font_size=11, leading=15):
        nonlocal y
        chunks = simpleSplit(text, font_name, font_size, max_w) or [""]
        for chunk in chunks:
            if y < bottom:
                _new_page()
            pdf.setFont(font_name, font_size)
            pdf.drawString(left, y, chunk)
            y -= leading

    pdf.setTitle(_normalize_text(sow_title) or "SOW")

    _draw_wrapped("AMBIFO TECHNOLOGY PVT LTD", "Helvetica-Bold", 12, 16)
    _draw_wrapped("Cloud Strategy | Migration & Modernization | DevOps | AI/ML", "Helvetica-Oblique", 10, 14)
    y -= 6
    _draw_wrapped((document_title_label or "Statement of Work (SOW)").upper(), "Helvetica-Bold", 16, 20)
    y -= 4

    info_lines = [
        f"Proposal For: {_normalize_text(customer.customer_name)} - {_normalize_text(customer.account_name)}",
        "Submitted By: Ambifo Technology Pvt Ltd",
        f"Title: {_normalize_text(sow_title) or f'Cloud Migration SOW - {_normalize_text(customer.customer_name)}'}",
        f"Doc Ref #: {_format_doc_ref_no(doc_ref_no)}",
        f"Date: {_normalize_text(sow_date)}",
        f"Version: {_normalize_text(sow_version) or '1.0'}",
        f"Customer Email: {_normalize_text(customer.email)}",
        f"Customer Phone: {_normalize_text(customer.phone) or '-'}",
        f"Cloud Platform: {_normalize_text(customer.cloud) or 'AWS / Azure'}",
        "Website: www.ambifo.com",
        "Support Email: support@ambifo.com",
        "Support Phone: +91 9148419502",
    ]
    for ln in info_lines:
        _draw_wrapped(ln, "Helvetica", 10, 14)

    y -= 10
    _draw_wrapped("Document Content", "Helvetica-Bold", 12, 16)
    y -= 2
    for line in _html_to_lines(content_html):
        _draw_wrapped(line, "Helvetica", 10, 14)

    y -= 8
    _draw_wrapped(
        "CONFIDENTIAL - This document and any attachments are confidential and intended solely for the use of the individual or entity to which it is addressed.",
        "Helvetica-Oblique",
        8,
        11,
    )

    pdf.save()
    output.seek(0)
    return output.getvalue()


def _sanitize_sow_export_html(content_html):
    """Remove editor-only UI artifacts from HTML before DOCX/email export."""
    text = (content_html or "").strip()
    if not text:
        return ""

    # Remove known editor UI fragments if they were accidentally persisted in HTML content.
    cleanup_patterns = [
        r"<[^>]*id=[\"']selectedDiagramIds[\"'][^>]*>[\s\S]*?</[^>]+>",
        r"<[^>]*id=[\"']macroWarning[\"'][^>]*>[\s\S]*?</[^>]+>",
        r"<[^>]*id=[\"']aiDocObjective[\"'][^>]*>",
        r"<[^>]*class=[\"'][^\"']*editor-label[^\"']*[\"'][^>]*>[\s\S]*?</[^>]+>",
        r"<label[^>]*for=[\"']selectedDiagramIds[\"'][^>]*>[\s\S]*?</label>",
    ]
    for pattern in cleanup_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Remove any plain-text remnants of the UI helper lines.
    text = re.sub(r"Document\s*Content\s*✏️\s*Editable", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"AI\s*objective\s*\(optional\)\s*:\s*e\.g\.\s*Build migration SOW with phases, risks, and landing-zone architecture",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


@crm_bp.route("/opportunities/<int:customer_id>/sow", methods=["GET"])
@login_required
def opportunity_sow(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    customer_diagrams = (
        CustomerDiagram.query
        .filter_by(customer_id=customer.id, is_active=True)
        .order_by(CustomerDiagram.created_at.asc())
        .all()
    )
    _ensure_default_sow_master_template()
    master_templates = SOWMasterTemplate.query.order_by(SOWMasterTemplate.created_at.asc()).all()
    sow_documents = (
        CustomerSOW.query
        .filter_by(customer_id=customer_id)
        .order_by(CustomerSOW.updated_at.desc())
        .all()
    )

    selected_sow_id = request.args.get("sow_id", type=int)
    new_doc = (request.args.get("new_doc") or "").strip() == "1"
    requested_title = (request.args.get("sow_title") or "").strip()
    selected_template_id = request.args.get("template_id", type=int)
    apply_template = (request.args.get("apply_template") or "").strip() == "1"
    requested_diagram_ids = _normalize_selected_diagram_ids(customer.id, request.args.get("diagram_ids") or "")

    sow = None
    if selected_sow_id:
        sow = CustomerSOW.query.filter_by(id=selected_sow_id, customer_id=customer_id).first()
    if not sow and sow_documents:
        sow = sow_documents[0]

    selected_template = None
    if selected_template_id:
        selected_template = next((t for t in master_templates if t.id == selected_template_id), None)
    if not selected_template and sow and sow.master_template_id:
        selected_template = next((t for t in master_templates if t.id == sow.master_template_id), None)
    if not selected_template and master_templates:
        selected_template = master_templates[0]

    if new_doc:
        new_title = requested_title or f"SOW {len(sow_documents) + 1} - {customer.customer_name}"
        initial_selected_ids = requested_diagram_ids or [d.id for d in customer_diagrams]
        selected_diagrams = _selected_diagrams_for_customer(customer.id, initial_selected_ids)
        sow = CustomerSOW(
            customer_id=customer_id,
            master_template_id=selected_template.id if selected_template else None,
            selected_diagram_ids=",".join(str(item) for item in initial_selected_ids),
            sow_title=new_title,
            version="1.0",
            status="draft",
            created_by=_actor_name(),
        )
        if selected_template:
            sow.content_html = _build_rendered_sow_sections(selected_template, customer, selected_diagrams=selected_diagrams, sow=sow)
        db.session.add(sow)
        db.session.commit()
        sow_documents = (
            CustomerSOW.query
            .filter_by(customer_id=customer_id)
            .order_by(CustomerSOW.updated_at.desc())
            .all()
        )
    elif not sow:
        initial_selected_ids = requested_diagram_ids or [d.id for d in customer_diagrams]
        selected_diagrams = _selected_diagrams_for_customer(customer.id, initial_selected_ids)
        sow = CustomerSOW(
            customer_id=customer_id,
            master_template_id=selected_template.id if selected_template else None,
            selected_diagram_ids=",".join(str(item) for item in initial_selected_ids),
            sow_title=f"Cloud Migration SOW — {customer.customer_name}",
            version="1.0",
            status="draft",
            created_by=_actor_name(),
        )
        if selected_template:
            sow.content_html = _build_rendered_sow_sections(selected_template, customer, selected_diagrams=selected_diagrams, sow=sow)
        db.session.add(sow)
        db.session.commit()
        sow_documents = (
            CustomerSOW.query
            .filter_by(customer_id=customer_id)
            .order_by(CustomerSOW.updated_at.desc())
            .all()
        )
    elif selected_template and apply_template:
        if requested_diagram_ids:
            sow.selected_diagram_ids = ",".join(str(item) for item in requested_diagram_ids)
        selected_ids = _normalize_selected_diagram_ids(customer.id, sow.selected_diagram_ids or "")
        selected_diagrams = _selected_diagrams_for_customer(customer.id, selected_ids)
        sow.master_template_id = selected_template.id
        sow.content_html = _build_rendered_sow_sections(selected_template, customer, selected_diagrams=selected_diagrams, sow=sow)
        sow.updated_at = datetime.utcnow()
        db.session.commit()
    elif selected_template and not sow.master_template_id:
        sow.master_template_id = selected_template.id
        db.session.commit()

    selected_diagram_ids = _normalize_selected_diagram_ids(customer.id, sow.selected_diagram_ids or "")
    if not selected_diagram_ids and customer_diagrams:
        selected_diagram_ids = [d.id for d in customer_diagrams]
    selected_diagrams = _selected_diagrams_for_customer(customer.id, selected_diagram_ids)

    if selected_template and sow and sow.master_template_id == selected_template.id:
        merged_content, changed = _append_missing_rendered_sow_sections(
            sow.content_html or "",
            selected_template,
            customer,
            selected_diagrams=selected_diagrams,
            sow=sow,
        )
        if changed:
            sow.content_html = merged_content
            sow.updated_at = datetime.utcnow()
            db.session.commit()

    default_content = _build_rendered_sow_sections(selected_template, customer, selected_diagrams=selected_diagrams, sow=sow) if selected_template else ""

    today = datetime.utcnow().strftime("%d %B, %Y")
    document_title_label = _get_sow_document_title_label(selected_template.id) if selected_template else "Statement of Work (SOW)"
    return render_template(
        "sow_editor.html",
        customer=customer,
        sow=sow,
        doc_ref_no=_format_doc_ref_no(
            sow_id=sow.id if sow else None,
            ref_date=sow.created_at if sow else None,
        ),
        default_content=default_content,
        customer_diagrams=customer_diagrams,
        selected_diagram_ids=selected_diagram_ids,
        sow_documents=sow_documents,
        master_templates=master_templates,
        selected_master_template=selected_template,
        document_title_label=document_title_label,
        today=today,
    )


@crm_bp.route("/opportunities/<int:customer_id>/sow/save", methods=["POST"])
@login_required
def opportunity_sow_save(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}

    sow_id = data.get("sow_id")
    sow = CustomerSOW.query.filter_by(id=sow_id, customer_id=customer_id).first() if sow_id else None
    if not sow:
        sow = CustomerSOW(customer_id=customer_id, created_by=_actor_name())
        db.session.add(sow)

    sow.sow_title = (data.get("sow_title") or "").strip() or f"Cloud Migration SOW — {customer.customer_name}"
    posted_sow_date = (data.get("sow_date") or "").strip()
    sow.sow_date = posted_sow_date or sow.sow_date or datetime.utcnow().strftime("%d %B, %Y")
    sow.version = (data.get("version") or "1.0").strip()
    raw_template_id = data.get("master_template_id")
    selected_diagram_ids = _normalize_selected_diagram_ids(customer.id, data.get("selected_diagram_ids") or [])
    try:
        sow.master_template_id = int(raw_template_id) if raw_template_id else None
    except (TypeError, ValueError):
        sow.master_template_id = None
    sow.selected_diagram_ids = ",".join(str(item) for item in selected_diagram_ids)
    sow.content_html = data.get("content_html") or ""
    sow.status = "draft"
    sow.updated_at = datetime.utcnow()
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="sow-draft-saved",
        changes_summary=(
            f"SOW draft saved. Title: {sow.sow_title or 'N/A'} | Version: {sow.version or 'N/A'} | "
            f"Doc Ref: {_format_doc_ref_no(sow_id=sow.id, ref_date=sow.created_at)}"
        ),
        tag_name="update",
    )
    db.session.commit()

    return jsonify(success=True, sow_id=sow.id, message="Draft saved.")


@crm_bp.route("/opportunities/<int:customer_id>/sow/download-docx", methods=["POST"])
@login_required
def opportunity_sow_download_docx(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}

    sow_title = (data.get("sow_title") or f"SOW_{customer.customer_name}").strip()
    sow_id = data.get("sow_id")
    try:
        sow_id = int(sow_id) if sow_id is not None else None
    except (TypeError, ValueError):
        sow_id = None
    sow_record = CustomerSOW.query.filter_by(id=sow_id, customer_id=customer_id).first() if sow_id else None
    doc_ref_no = _format_doc_ref_no(
        (data.get("doc_ref_no") or "").strip(),
        sow_id,
        sow_record.created_at if sow_record else None,
    )
    sow_date = (data.get("sow_date") or "").strip()
    sow_version = (data.get("version") or "1.0").strip()
    master_template_id = data.get("master_template_id")
    content_html = _sanitize_sow_export_html(data.get("content_html") or "")

    master_template = None
    if master_template_id:
        try:
            master_template = SOWMasterTemplate.query.get(int(master_template_id))
        except (TypeError, ValueError):
            master_template = None
    if not master_template:
        master_template = _ensure_default_sow_master_template()

    document_title_label = _get_sow_document_title_label(master_template.id)

    try:
        docx_bytes = _generate_sow_docx(
            customer,
            sow_title,
            sow_date,
            sow_version,
            content_html,
            document_title_label=document_title_label,
            doc_ref_no=doc_ref_no,
        )
    except Exception as exc:
        return str(exc), 500

    safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", sow_title)[:60]
    filename = f"{safe_title}_v{sow_version}.docx"

    _log_opportunity_history(
        customer.id,
        action="sow-docx-downloaded",
        changes_summary=(
            f"SOW DOCX generated/downloaded. File: {filename} | "
            f"Doc Ref: {doc_ref_no or 'N/A'} | Version: {sow_version or 'N/A'}"
        ),
        tag_name="update",
    )
    db.session.commit()

    return send_file(
        io.BytesIO(docx_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@crm_bp.route("/opportunities/<int:customer_id>/sow/download-pdf", methods=["POST"])
@login_required
def opportunity_sow_download_pdf(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}

    sow_title = (data.get("sow_title") or f"SOW_{customer.customer_name}").strip()
    sow_id = data.get("sow_id")
    try:
        sow_id = int(sow_id) if sow_id is not None else None
    except (TypeError, ValueError):
        sow_id = None
    sow_record = CustomerSOW.query.filter_by(id=sow_id, customer_id=customer_id).first() if sow_id else None
    doc_ref_no = _format_doc_ref_no(
        (data.get("doc_ref_no") or "").strip(),
        sow_id,
        sow_record.created_at if sow_record else None,
    )
    sow_date = (data.get("sow_date") or "").strip()
    sow_version = (data.get("version") or "1.0").strip()
    master_template_id = data.get("master_template_id")
    content_html = _sanitize_sow_export_html(data.get("content_html") or "")

    master_template = None
    if master_template_id:
        try:
            master_template = SOWMasterTemplate.query.get(int(master_template_id))
        except (TypeError, ValueError):
            master_template = None
    if not master_template:
        master_template = _ensure_default_sow_master_template()

    document_title_label = _get_sow_document_title_label(master_template.id)

    try:
        pdf_bytes = _generate_sow_pdf(
            customer,
            sow_title,
            sow_date,
            sow_version,
            content_html,
            document_title_label=document_title_label,
            doc_ref_no=doc_ref_no,
        )
    except Exception as exc:
        return str(exc), 500

    safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", sow_title)[:60]
    filename = f"{safe_title}_v{sow_version}.pdf"

    _log_opportunity_history(
        customer.id,
        action="sow-pdf-downloaded",
        changes_summary=(
            f"SOW PDF generated/downloaded. File: {filename} | "
            f"Doc Ref: {doc_ref_no or 'N/A'} | Version: {sow_version or 'N/A'}"
        ),
        tag_name="update",
    )
    db.session.commit()

    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@crm_bp.route("/opportunities/<int:customer_id>/sow/send-email", methods=["POST"])
@login_required
def opportunity_sow_send_email(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}

    to_email = (data.get("to_email") or "").strip()
    subject = (data.get("subject") or f"Statement of Work — {customer.customer_name}").strip()
    body_text = (data.get("body") or "").strip()
    sow_title = (data.get("sow_title") or f"SOW_{customer.customer_name}").strip()
    sow_id = data.get("sow_id")
    try:
        sow_id = int(sow_id) if sow_id is not None else None
    except (TypeError, ValueError):
        sow_id = None
    sow_record = CustomerSOW.query.filter_by(id=sow_id, customer_id=customer_id).first() if sow_id else None
    doc_ref_no = _format_doc_ref_no(
        (data.get("doc_ref_no") or "").strip(),
        sow_id,
        sow_record.created_at if sow_record else None,
    )
    sow_date = (data.get("sow_date") or "").strip()
    sow_version = (data.get("version") or "1.0").strip()
    attachment_format = (data.get("attachment_format") or "docx").strip().lower()
    if attachment_format not in ("docx", "pdf"):
        attachment_format = "docx"
    master_template_id = data.get("master_template_id")
    content_html = _sanitize_sow_export_html(data.get("content_html") or "")

    if not to_email or "@" not in to_email:
        return jsonify(success=False, message="Please enter a valid recipient email.")

    master_template = None
    if master_template_id:
        try:
            master_template = SOWMasterTemplate.query.get(int(master_template_id))
        except (TypeError, ValueError):
            master_template = None
    if not master_template:
        master_template = _ensure_default_sow_master_template()

    document_title_label = _get_sow_document_title_label(master_template.id)

    generation_name = attachment_format.upper()
    try:
        if attachment_format == "pdf":
            attachment_bytes = _generate_sow_pdf(
                customer,
                sow_title,
                sow_date,
                sow_version,
                content_html,
                document_title_label=document_title_label,
                doc_ref_no=doc_ref_no,
            )
            attachment_mime = "application/pdf"
            extension = "pdf"
            generation_name = "PDF"
        else:
            attachment_bytes = _generate_sow_docx(
                customer,
                sow_title,
                sow_date,
                sow_version,
                content_html,
                document_title_label=document_title_label,
                doc_ref_no=doc_ref_no,
            )
            attachment_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            extension = "docx"
            generation_name = "DOCX"
    except Exception as exc:
        return jsonify(success=False, message=f"{generation_name} generation failed: {exc}")

    safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", sow_title)[:60]
    filename = f"{safe_title}_v{sow_version}.{extension}"

    template_macro_values = build_macro_values(
        customer,
        {
            "sow_email_subject": html.escape(subject),
            "sow_email_body_html": html.escape(body_text).replace(chr(10), "<br>"),
        },
    )
    tpl, rendered_subject, html_body = _render_system_email_template("sow_document_email", template_macro_values)

    email_service = EmailService(current_app)
    result = email_service.send_html_email_with_attachment(
        to_email, rendered_subject, html_body, attachment_bytes, filename,
        attachment_mime,
    )

    db.session.add(EmailLog(
        customer_id=customer.id,
        template_id=tpl.id if tpl else None,
        recipient_email=to_email,
        email_type="sow",
        subject=rendered_subject,
        body=html_body,
        status=result.status,
        error_message=result.error,
    ))
    _log_opportunity_history(
        customer.id,
        action="sow-email-sent",
        changes_summary=f"SOW {extension.upper()} emailed to {to_email}. Subject: {rendered_subject}",
        tag_name="update",
    )
    db.session.commit()

    if result.success or result.status == "dev-mode":
        return jsonify(success=True, message=f"SOW sent to {to_email} (status: {result.status}).")
    return jsonify(success=False, message=f"Email failed: {result.error}")


@crm_bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
@crm_bp.route("/opportunities/<int:customer_id>/delete", methods=["POST"])
def opportunity_delete(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    # Remove dependent rows explicitly to avoid FK nulling issues on non-null child columns.
    OpportunityHistory.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    MeetingInvite.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    MeetingAvailabilityRequest.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    GatheringServerDetail.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    GatheringFileNasDetail.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    GatheringBlockStorageDetail.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    GatheringRequest.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    CustomerDocument.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    CustomerDiagram.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    CustomerSOW.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
    EmailLog.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)

    db.session.delete(customer)
    db.session.commit()
    flash("Opportunity deleted.", "success")
    return redirect(url_for("crm.opportunity_list"))


@crm_bp.route("/opportunities/quick-add", methods=["POST"])
@login_required
def opportunity_quick_add():
    _ensure_default_cloud_operators()

    customer_name = (request.form.get("customer_name") or "").strip()
    account_name = (request.form.get("account_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    cloud = (request.form.get("cloud") or "").strip()

    if not customer_name or not account_name or not email or not phone or not cloud:
        flash("Quick Add requires Customer Name, Company, Email, Phone Number, and Cloud.", "error")
        return redirect(url_for("crm.opportunity_list"))

    if not _is_valid_email(email):
        flash("Please enter a valid email for Quick Add.", "error")
        return redirect(url_for("crm.opportunity_list"))

    if Customer.query.filter_by(email=email).first():
        flash("Opportunity with this email already exists.", "error")
        return redirect(url_for("crm.opportunity_list"))

    if not OpportunityCloudOperator.query.filter_by(name=cloud, is_active=True).first():
        flash("Please select a valid cloud operator.", "error")
        return redirect(url_for("crm.opportunity_list"))

    customer = Customer(
        customer_name=customer_name,
        account_name=account_name,
        email=email,
        phone=phone,
        cloud=cloud,
    )
    db.session.add(customer)
    db.session.commit()

    _log_opportunity_history(
        customer.id,
        action="quick-created",
        changes_summary="Opportunity created from Quick Add form.",
        remark=(request.form.get("change_remark") or "").strip() or None,
    )
    db.session.commit()

    flash("Opportunity added successfully via Quick Add.", "success")
    return redirect(url_for("crm.opportunity_list"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/send-link", methods=["POST"])
@login_required
def opportunity_gathering_data_send_link(customer_id):
    """Removed standalone page — redirect to edit tab."""
    return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-data", methods=["GET", "POST"])
def opportunity_gathering_data(customer_id):
    """Old standalone page — now consolidated into the edit tab."""
    return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/<int:entry_id>/delete", methods=["POST"])
def opportunity_gathering_data_delete(customer_id, entry_id):
    """Old delete route — now handled by the edit tab."""
    return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))


def _extract_template_macros(template):
    """Return sorted list of macro keys used in template subject + body (excluding auto-computed ones)."""
    auto_keys = {"today", "gathering_form_link", "gathering_access_key", "gathering_expires_at",
                 "meeting_availability_form_link", "meeting_availability_expires_at", "selected_diagrams_html"}
    combined = f"{template.subject_template or ''} {template.body_template or ''}"
    found = re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", combined)
    return sorted({k for k in found if k not in auto_keys})


def _lead_sample_columns():
    return ["lead_name", "email", "phone", "company", "city", "source", "tags", "notes"]


def _upsert_lead_from_row(row, uploaded_from=None):
    email = (row.get("email") or "").strip().lower()
    if not email or not _is_valid_email(email):
        return False

    lead = Lead.query.filter_by(email=email).first()
    if not lead:
        lead = Lead(email=email)
        db.session.add(lead)

    lead.lead_name = (row.get("lead_name") or lead.lead_name or "").strip() or None
    lead.phone = (row.get("phone") or lead.phone or "").strip() or None
    lead.company = (row.get("company") or lead.company or "").strip() or None
    lead.city = (row.get("city") or lead.city or "").strip() or None
    lead.source = (row.get("source") or lead.source or uploaded_from or "").strip() or None
    lead.tags = (row.get("tags") or lead.tags or "").strip() or None
    lead.notes = (row.get("notes") or lead.notes or "").strip() or None
    try:
        lead.raw_payload = json.dumps(row, ensure_ascii=True)
    except Exception:
        lead.raw_payload = None
    return True


def _lead_macro_values(lead):
    return {
        "today": datetime.utcnow().date().isoformat(),
        "lead_name": lead.lead_name or "",
        "customer_name": lead.lead_name or "",
        "account_name": lead.company or "",
        "company": lead.company or "",
        "email": lead.email or "",
        "phone": lead.phone or "",
        "city": lead.city or "",
        "source": lead.source or "",
        "tags": lead.tags or "",
    }


def _bulk_csv_log_dir():
    root = Path(current_app.root_path).parent
    log_dir = root / "uploads" / "bulk_csv_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _safe_log_path(filename):
    base = _bulk_csv_log_dir().resolve()
    target = (base / filename).resolve()
    if base not in target.parents and target != base:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


def _email_has_mx(email_addr, cache):
    if dns is None:
        return False, "dnspython-not-installed"
    domain = (email_addr.split("@", 1)[1] if "@" in email_addr else "").strip().lower()
    if not domain:
        return False, "invalid-domain"
    if domain in cache:
        return cache[domain]
    try:
        answers = dns.resolver.resolve(domain, "MX")
        ok = bool(answers)
        result = (ok, "ok" if ok else "no-mx")
    except Exception:
        result = (False, "mx-lookup-failed")
    cache[domain] = result
    return result


@crm_bp.route("/templates/csv-sample")
@login_required
def template_csv_sample():
    template_id = request.args.get("template_id", type=int)
    if not template_id:
        return jsonify({"error": "template_id required"}), 400
    template = EmailTemplate.query.get(template_id)
    if not template:
        return jsonify({"error": "Template not found"}), 404

    macro_keys = _extract_template_macros(template)
    columns = ["email"] + macro_keys

    # ?info=1 → return JSON column list for AJAX
    if request.args.get("info"):
        return jsonify({"columns": columns, "template_name": template.name})

    # Return downloadable sample CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    sample_row = ["recipient@example.com"] + [f"sample_{k}" for k in macro_keys]
    writer.writerow(sample_row)
    csv_bytes = output.getvalue().encode("utf-8")
    buf = io.BytesIO(csv_bytes)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", template.name)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name=f"sample_{safe_name}.csv")


@crm_bp.route("/templates/csv-executions/<int:execution_id>/download/<string:kind>")
@login_required
def template_csv_execution_download(execution_id, kind):
    execution = EmailBulkCsvExecution.query.get(execution_id)
    if not execution:
        flash("Bulk CSV execution record not found.", "error")
        return redirect(url_for("crm.template_list") + "#bulk-csv-history")

    if kind == "bad":
        filename = execution.bad_log_filename
    elif kind == "success":
        filename = execution.success_log_filename
    else:
        flash("Invalid log file type requested.", "error")
        return redirect(url_for("crm.template_list") + "#bulk-csv-history")

    file_path = _safe_log_path(filename)
    if not file_path:
        flash("Requested log file is missing.", "error")
        return redirect(url_for("crm.template_list") + "#bulk-csv-history")

    return send_file(file_path, as_attachment=True, download_name=file_path.name, mimetype="text/plain")


@crm_bp.route("/leads/csv-sample")
@login_required
def leads_csv_sample():
    columns = _lead_sample_columns()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow([
        "John Doe",
        "john.doe@example.com",
        "+91 9999999999",
        "Example Corp",
        "Bangalore",
        "Website Campaign",
        "promo,priority",
        "Interested in cloud modernization",
    ])
    buf = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="leads_sample.csv")


@crm_bp.route("/templates", methods=["GET", "POST"])
def template_list():
    def _render(anchor=None):
        system_template_names = _system_template_name_set()
        tpl_page = request.args.get("tpl_page", 1, type=int)
        tpl_pagination = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).paginate(
            page=tpl_page, per_page=5, error_out=False
        )
        all_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
        system_templates = [t for t in all_templates if t.name in system_template_names]
        customers = Customer.query.order_by(Customer.customer_name.asc()).all()
        active_diagrams = (
            CustomerDiagram.query
            .filter_by(is_active=True)
            .order_by(CustomerDiagram.customer_id.asc(), CustomerDiagram.macro_key.asc())
            .all()
        )
        diagram_macro_map = {}
        for diagram in active_diagrams:
            customer_key = str(diagram.customer_id)
            if customer_key not in diagram_macro_map:
                diagram_macro_map[customer_key] = []
            if (diagram.macro_key or "").strip():
                diagram_macro_map[customer_key].append(
                    {
                        "macro_key": diagram.macro_key,
                        "diagram_name": diagram.diagram_name,
                    }
                )
        statuses = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
        segments = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
        hist_page = request.args.get("hist_page", 1, type=int)
        history_pagination = EmailLog.query.order_by(EmailLog.created_at.desc()).paginate(
            page=hist_page, per_page=10, error_out=False
        )
        unsub_page = request.args.get("unsub_page", 1, type=int)
        unsubscribe_pagination = EmailUnsubscribe.query.order_by(EmailUnsubscribe.unsubscribed_at.desc()).paginate(
            page=unsub_page,
            per_page=10,
            error_out=False,
        )
        bulk_page = request.args.get("bulk_page", 1, type=int)
        bulk_exec_pagination = EmailBulkCsvExecution.query.order_by(EmailBulkCsvExecution.created_at.desc()).paginate(
            page=bulk_page,
            per_page=10,
            error_out=False,
        )
        lead_page = request.args.get("lead_page", 1, type=int)
        lead_q = (request.args.get("lead_q") or "").strip()
        lead_email_state = (request.args.get("lead_email_state") or "all").strip()
        leads_query = Lead.query
        if lead_q:
            like = f"%{lead_q}%"
            leads_query = leads_query.filter(
                db.or_(
                    Lead.lead_name.ilike(like),
                    Lead.email.ilike(like),
                    Lead.phone.ilike(like),
                    Lead.company.ilike(like),
                    Lead.city.ilike(like),
                    Lead.source.ilike(like),
                )
            )
        if lead_email_state == "emailed":
            leads_query = leads_query.filter(Lead.last_emailed_at.isnot(None))
        elif lead_email_state == "not_emailed":
            leads_query = leads_query.filter(Lead.last_emailed_at.is_(None))
        lead_pagination = leads_query.order_by(Lead.created_at.desc()).paginate(
            page=lead_page,
            per_page=10,
            error_out=False,
        )
        return render_template(
            "templates_list.html",
            tpl_pagination=tpl_pagination,
            all_templates=all_templates,
            system_template_names=system_template_names,
            system_templates=system_templates,
            customers=customers,
            diagram_macro_map=diagram_macro_map,
            email_macro_catalog=_email_template_macro_catalog(),
            statuses=statuses,
            segments=segments,
            history_pagination=history_pagination,
            unsubscribe_pagination=unsubscribe_pagination,
            bulk_exec_pagination=bulk_exec_pagination,
            lead_pagination=lead_pagination,
            lead_q=lead_q,
            lead_email_state=lead_email_state,
            leads_total_count=Lead.query.count(),
            scroll_to=anchor,
        )

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        # Add template
        if action == "add_template":
            name = (request.form.get("name") or "").strip()
            subject_template = (request.form.get("subject_template") or "").strip()
            body_template = _sanitize_email_template_body(request.form.get("body_template") or "")
            if not name or not subject_template or not body_template:
                flash("Name, subject, and body are required.", "error")
            elif EmailTemplate.query.filter_by(name=name).first():
                flash("Template name already exists.", "error")
            else:
                db.session.add(EmailTemplate(
                    name=name,
                    subject_template=subject_template,
                    body_template=body_template,
                ))
                db.session.commit()
                flash("Template created.", "success")
            return redirect(url_for("crm.template_list") + "#template-list")

        # Edit template
        elif action == "edit_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if not tpl:
                flash("Template not found.", "error")
            else:
                name = (request.form.get("name") or "").strip()
                subject_template = (request.form.get("subject_template") or "").strip()
                body_template = _sanitize_email_template_body(request.form.get("body_template") or "")
                if not name or not subject_template or not body_template:
                    flash("Name, subject, and body are required.", "error")
                else:
                    dup = EmailTemplate.query.filter(
                        EmailTemplate.name == name,
                        EmailTemplate.id != tpl.id,
                    ).first()
                    if dup:
                        flash("Another template already uses that name.", "error")
                    else:
                        tpl.name = name
                        tpl.subject_template = subject_template
                        tpl.body_template = body_template
                        db.session.commit()
                        flash("Template updated.", "success")
            return redirect(url_for("crm.template_list") + "#template-list")

        # Delete template
        elif action == "delete_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if tpl:
                if _is_system_template_name(tpl.name):
                    flash("System templates cannot be deleted. You can edit them.", "error")
                else:
                    db.session.delete(tpl)
                    db.session.commit()
                    flash("Template deleted.", "success")
            return redirect(url_for("crm.template_list") + "#template-list")

        # Send custom email
        elif action == "send_custom_email":
            recipient_mode = (request.form.get("recipient_mode") or "").strip()
            email_source   = (request.form.get("email_source") or "template").strip()

            # Resolve subject/body source
            if email_source == "template":
                template_id = request.form.get("template_id", type=int)
                tpl = EmailTemplate.query.get(template_id) if template_id else None
                if not tpl:
                    flash("Please select a valid template.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                use_template = True
            else:
                custom_subject = (request.form.get("custom_subject") or "").strip()
                custom_body    = (request.form.get("custom_body") or "").strip()
                if not custom_subject or not custom_body:
                    flash("Subject and body are required for a custom email.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                use_template = False

            # Resolve recipients
            def _send_to_customer(customer):
                if use_template:
                    mv = _build_template_macro_values_for_customer(
                        customer,
                        tpl,
                        recipient_email=customer.email,
                    )
                    subj = render_macros(tpl.subject_template, mv)
                    body = render_macros(tpl.body_template, mv)
                    tpl_id_log = tpl.id
                else:
                    subj = custom_subject
                    body = custom_body
                    tpl_id_log = None
                svc = EmailService(current_app)
                res = svc.send_html_email(customer.email, subj, body)
                db.session.add(EmailLog(
                    customer_id=customer.id,
                    template_id=tpl_id_log,
                    recipient_email=customer.email,
                    email_type="custom",
                    subject=subj,
                    body=body,
                    status=res.status,
                    error_message=res.error,
                ))
                _log_opportunity_history(
                    customer.id,
                    action="email-sent",
                    changes_summary=(
                        f"Email processed to {customer.email}. Source: {'template' if use_template else 'custom'} | "
                        f"Subject: {subj} | Status: {res.status}."
                    ),
                    tag_name="email",
                )
                return res

            def _send_to_address(email_addr, subj, body):
                svc = EmailService(current_app)
                res = svc.send_html_email(email_addr, subj, body)
                db.session.add(EmailLog(
                    customer_id=None,
                    template_id=None,
                    recipient_email=email_addr,
                    email_type="custom",
                    subject=subj,
                    body=body,
                    status=res.status,
                    error_message=res.error,
                ))
                return res

            sent = failed = 0

            if recipient_mode == "status":
                status_name = (request.form.get("filter_status") or "").strip()
                if not status_name:
                    flash("Please select a status.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                recipients = Customer.query.filter(
                    Customer.deal_status == status_name,
                    Customer.email.isnot(None),
                    Customer.email != "",
                ).all()
                for c in recipients:
                    r = _send_to_customer(c)
                    if r.success or r.status == "dev-mode":
                        sent += 1
                    else:
                        failed += 1
                db.session.commit()
                flash(f"Status '{status_name}': {sent} sent, {failed} failed.", "success" if not failed else "error")

            elif recipient_mode == "segment":
                segment_name = (request.form.get("filter_segment") or "").strip()
                if not segment_name:
                    flash("Please select a segment.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                recipients = Customer.query.filter(
                    Customer.segment == segment_name,
                    Customer.email.isnot(None),
                    Customer.email != "",
                ).all()
                for c in recipients:
                    r = _send_to_customer(c)
                    if r.success or r.status == "dev-mode":
                        sent += 1
                    else:
                        failed += 1
                db.session.commit()
                flash(f"Segment '{segment_name}': {sent} sent, {failed} failed.", "success" if not failed else "error")

            elif recipient_mode == "select":
                customer_ids = request.form.getlist("selected_customers")
                if not customer_ids:
                    flash("Please select at least one customer.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                for cid in customer_ids:
                    c = Customer.query.get(int(cid))
                    if c and c.email:
                        r = _send_to_customer(c)
                        if r.success or r.status == "dev-mode":
                            sent += 1
                        else:
                            failed += 1
                db.session.commit()
                flash(f"Selected customers: {sent} sent, {failed} failed.", "success" if not failed else "error")

            elif recipient_mode == "manual_email":
                manual_email = (request.form.get("manual_email") or "").strip()
                if not manual_email or "@" not in manual_email:
                    flash("Please enter a valid email address.", "error")
                    return redirect(url_for("crm.template_list") + "#send-custom")
                if use_template:
                    template_text = f"{tpl.subject_template or ''}\n{tpl.body_template or ''}"
                    if (
                        "{{meeting_availability_form_link}}" in template_text
                        or "{{meeting_availability_expires_at}}" in template_text
                    ):
                        flash(
                            "This template requires opportunity/customer context to generate the availability link. "
                            "Please use Status/Segment/Selected Customers mode.",
                            "error",
                        )
                        return redirect(url_for("crm.template_list") + "#send-custom")
                    subj = tpl.subject_template
                    body = tpl.body_template
                else:
                    subj = custom_subject
                    body = custom_body
                r = _send_to_address(manual_email, subj, body)
                db.session.commit()
                if r.success or r.status == "dev-mode":
                    flash(f"Email sent to {manual_email} (status: {r.status}).", "success")
                else:
                    flash(f"Email failed: {r.error}", "error")

            else:
                flash("Please select a recipient option.", "error")

            return redirect(url_for("crm.template_list") + "#send-custom")

        # Send bulk email
        elif action == "send_bulk_email":
            template_id = request.form.get("template_id", type=int)
            template = EmailTemplate.query.get(template_id)
            if not template:
                flash("Select a valid template.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk")
            all_customers = Customer.query.filter(Customer.email.isnot(None), Customer.email != "").all()
            sent = 0
            failed = 0
            email_service = EmailService(current_app)
            for customer in all_customers:
                macro_values = _build_template_macro_values_for_customer(
                    customer,
                    template,
                    recipient_email=customer.email,
                )
                rendered_subject = render_macros(template.subject_template, macro_values)
                rendered_body = render_macros(template.body_template, macro_values)
                result = email_service.send_html_email(customer.email, rendered_subject, rendered_body)
                db.session.add(EmailLog(
                    customer_id=customer.id,
                    template_id=template.id,
                    recipient_email=customer.email,
                    email_type="bulk",
                    subject=rendered_subject,
                    body=rendered_body,
                    status=result.status,
                    error_message=result.error,
                ))
                _log_opportunity_history(
                    customer.id,
                    action="bulk-email-sent",
                    changes_summary=(
                        f"Bulk email processed to {customer.email}. Template: {template.name} | "
                        f"Subject: {rendered_subject} | Status: {result.status}."
                    ),
                    tag_name="email",
                )
                if result.success or result.status == "dev-mode":
                    sent += 1
                else:
                    failed += 1
            db.session.commit()
            flash(f"Bulk email done: {sent} sent, {failed} failed.", "success" if not failed else "error")
            return redirect(url_for("crm.template_list") + "#send-bulk")

        # Send bulk email via CSV upload
        elif action == "send_bulk_csv":
            template_id = request.form.get("template_id", type=int)
            template = EmailTemplate.query.get(template_id) if template_id else None
            if not template:
                flash("Select a valid template before uploading CSV.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            if dns is None:
                flash("dnspython is not installed on server. Install dependencies first to run MX validation.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            csv_file = request.files.get("csv_file")
            if not csv_file or not csv_file.filename:
                flash("Please upload a CSV file.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            # Read CSV
            try:
                original_filename = secure_filename(csv_file.filename or "bulk.csv")
                content = csv_file.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(content))
                csv_rows = list(reader)
                csv_headers = [h.strip() for h in (reader.fieldnames or [])]
            except Exception as e:
                flash(f"Failed to read CSV: {e}", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            # Save rows into leads table first (user-required behavior).
            lead_imported = 0
            for row in csv_rows:
                if _upsert_lead_from_row(row, uploaded_from=original_filename):
                    lead_imported += 1
            db.session.commit()

            # Determine required columns
            macro_keys = _extract_template_macros(template)
            required_cols = ["email"] + macro_keys
            missing_cols = [c for c in required_cols if c not in csv_headers]
            if missing_cols:
                flash(
                    f"CSV is missing required columns: {', '.join(missing_cols)}. "
                    f"Expected: {', '.join(required_cols)}. Use the 'Download Sample CSV' button to get the correct format.",
                    "error",
                )
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            if not csv_rows:
                flash("CSV file has no data rows.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            if len(csv_rows) < 1:
                flash("CSV must contain at least 1 recipient record.", "error")
                return redirect(url_for("crm.template_list") + "#send-bulk-csv")

            execution_token = f"exec_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            bad_log_filename = f"{execution_token}_bad_emails.txt"
            success_log_filename = f"{execution_token}_success_emails.txt"
            bad_log_path = _bulk_csv_log_dir() / bad_log_filename
            success_log_path = _bulk_csv_log_dir() / success_log_filename

            unsubscribed_set = {
                (row.email or "").strip().lower()
                for row in EmailUnsubscribe.query.all()
                if (row.email or "").strip()
            }

            email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            mx_cache = {}

            bad_lines = [f"Bulk CSV Execution: {execution_token}", f"Template: {template.name}", ""]
            deliverable_rows = []
            unsubscribed_rows = 0

            # Step 1: syntax + unsubscribe checks
            for idx, row in enumerate(csv_rows, start=2):
                recipient = (row.get("email") or "").strip()
                row_ref = f"Row {idx}"
                if not recipient:
                    bad_lines.append(f"{row_ref}: EMPTY_EMAIL")
                    continue
                if not email_re.match(recipient):
                    bad_lines.append(f"{row_ref}: INVALID_SYNTAX -> {recipient}")
                    continue
                if recipient.lower() in unsubscribed_set:
                    unsubscribed_rows += 1
                    bad_lines.append(f"{row_ref}: UNSUBSCRIBED -> {recipient}")
                    continue
                deliverable_rows.append((idx, recipient, row))

            # Step 2: MX checks
            mx_valid_rows = []
            for idx, recipient, row in deliverable_rows:
                has_mx, reason = _email_has_mx(recipient, mx_cache)
                if not has_mx:
                    bad_lines.append(f"Row {idx}: MX_CHECK_FAILED({reason}) -> {recipient}")
                    continue
                mx_valid_rows.append((idx, recipient, row))

            if not mx_valid_rows:
                bad_log_path.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")
                success_log_path.write_text(
                    f"Bulk CSV Execution: {execution_token}\nTemplate: {template.name}\n\nNo emails were sent.\n",
                    encoding="utf-8",
                )
                execution = EmailBulkCsvExecution(
                    template_id=template.id,
                    uploaded_filename=original_filename,
                    bad_log_filename=bad_log_filename,
                    success_log_filename=success_log_filename,
                    total_rows=len(csv_rows),
                    unsubscribed_rows=unsubscribed_rows,
                    invalid_rows=len(csv_rows),
                    sent_rows=0,
                    failed_rows=0,
                )
                db.session.add(execution)
                db.session.commit()
                flash("No sendable emails left after unsubscribe + MX validation. Download bad email log for details.", "error")
                return redirect(url_for("crm.template_list") + "#bulk-csv-history")

            # Send emails and keep success/bad logs
            email_service = EmailService(current_app)
            sent = failed = 0
            success_lines = [f"Bulk CSV Execution: {execution_token}", f"Template: {template.name}", ""]
            for idx, recipient, row in mx_valid_rows:
                # Build macro values from CSV row (strip whitespace from all values)
                mv = {k: (row.get(k) or "").strip() for k in csv_headers}
                mv["today"] = datetime.utcnow().date().isoformat()
                rendered_subject = render_macros(template.subject_template, mv)
                rendered_body = render_macros(template.body_template, mv)
                result = email_service.send_html_email(recipient, rendered_subject, rendered_body)
                db.session.add(EmailLog(
                    customer_id=None,
                    template_id=template.id,
                    recipient_email=recipient,
                    email_type="csv-bulk",
                    subject=rendered_subject,
                    body=rendered_body,
                    status=result.status,
                    error_message=result.error,
                ))
                if result.success or result.status == "dev-mode":
                    sent += 1
                    success_lines.append(f"Row {idx}: SENT({result.status}) -> {recipient}")
                else:
                    failed += 1
                    bad_lines.append(f"Row {idx}: SEND_FAILED({result.status}) -> {recipient} | {result.error or '-'}")

            bad_log_path.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")
            success_log_path.write_text("\n".join(success_lines) + "\n", encoding="utf-8")

            execution = EmailBulkCsvExecution(
                template_id=template.id,
                uploaded_filename=original_filename,
                bad_log_filename=bad_log_filename,
                success_log_filename=success_log_filename,
                total_rows=len(csv_rows),
                unsubscribed_rows=unsubscribed_rows,
                invalid_rows=max(0, len(csv_rows) - len(mx_valid_rows)),
                sent_rows=sent,
                failed_rows=failed,
            )
            db.session.add(execution)
            db.session.commit()
            msg = (
                f"CSV bulk execution completed. Total rows: {len(csv_rows)}, sent: {sent}, failed: {failed}, "
                f"unsubscribed removed: {unsubscribed_rows}, excluded (invalid/no-mx/unsubscribed): {max(0, len(csv_rows) - len(mx_valid_rows))}, "
                f"leads imported/updated: {lead_imported}."
            )
            flash(msg, "success" if not failed else "error")
            return redirect(url_for("crm.template_list") + "#bulk-csv-history")

        elif action == "upload_leads_csv":
            csv_file = request.files.get("leads_csv_file")
            if not csv_file or not csv_file.filename:
                flash("Please choose a CSV file for leads upload.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            try:
                file_name = secure_filename(csv_file.filename or "leads.csv")
                content = csv_file.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(content))
                rows = list(reader)
                headers = [h.strip() for h in (reader.fieldnames or [])]
            except Exception as e:
                flash(f"Failed to read leads CSV: {e}", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            if "email" not in headers:
                flash("Leads CSV must include 'email' column.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            if not rows:
                flash("Leads CSV has no data rows.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            imported = skipped = 0
            for row in rows:
                if _upsert_lead_from_row(row, uploaded_from=file_name):
                    imported += 1
                else:
                    skipped += 1
            db.session.commit()
            flash(f"Leads upload done: {imported} imported/updated, {skipped} skipped (invalid/missing email).", "success")
            return redirect(url_for("crm.template_list") + "#leads-section")

        elif action == "add_lead":
            lead_email = (request.form.get("lead_email") or "").strip().lower()
            if not _is_valid_email(lead_email):
                flash("Valid lead email is required.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            existing = Lead.query.filter_by(email=lead_email).first()
            if existing:
                flash("Lead with this email already exists. Use edit to update.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            lead = Lead(
                lead_name=(request.form.get("lead_name") or "").strip() or None,
                email=lead_email,
                phone=(request.form.get("lead_phone") or "").strip() or None,
                company=(request.form.get("lead_company") or "").strip() or None,
                city=(request.form.get("lead_city") or "").strip() or None,
                source=(request.form.get("lead_source") or "").strip() or None,
                tags=(request.form.get("lead_tags") or "").strip() or None,
                notes=(request.form.get("lead_notes") or "").strip() or None,
                is_active=bool(request.form.get("lead_is_active")),
            )
            db.session.add(lead)
            db.session.commit()
            flash("Lead added.", "success")
            return redirect(url_for("crm.template_list") + "#leads-section")

        elif action == "edit_lead":
            lead_id = request.form.get("lead_id", type=int)
            lead = Lead.query.get(lead_id) if lead_id else None
            if not lead:
                flash("Lead not found.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            lead_email = (request.form.get("lead_email") or "").strip().lower()
            if not _is_valid_email(lead_email):
                flash("Valid lead email is required.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            dup = Lead.query.filter(Lead.email == lead_email, Lead.id != lead.id).first()
            if dup:
                flash("Another lead already uses this email.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")

            lead.lead_name = (request.form.get("lead_name") or "").strip() or None
            lead.email = lead_email
            lead.phone = (request.form.get("lead_phone") or "").strip() or None
            lead.company = (request.form.get("lead_company") or "").strip() or None
            lead.city = (request.form.get("lead_city") or "").strip() or None
            lead.source = (request.form.get("lead_source") or "").strip() or None
            lead.tags = (request.form.get("lead_tags") or "").strip() or None
            lead.notes = (request.form.get("lead_notes") or "").strip() or None
            lead.is_active = bool(request.form.get("lead_is_active"))
            db.session.commit()
            flash("Lead updated.", "success")
            return redirect(url_for("crm.template_list") + "#leads-section")

        elif action == "delete_lead":
            lead_id = request.form.get("lead_id", type=int)
            lead = Lead.query.get(lead_id) if lead_id else None
            if not lead:
                flash("Lead not found.", "error")
                return redirect(url_for("crm.template_list") + "#leads-section")
            db.session.delete(lead)
            db.session.commit()
            flash("Lead deleted.", "success")
            return redirect(url_for("crm.template_list") + "#leads-section")

        elif action == "send_lead_bulk_email":
            template_id = request.form.get("template_id", type=int)
            template = EmailTemplate.query.get(template_id) if template_id else None
            if not template:
                flash("Select a valid template for leads email.", "error")
                return redirect(url_for("crm.template_list") + "#send-lead-bulk")

            lead_send_state = (request.form.get("lead_send_state") or "all").strip()
            leads_query = Lead.query.filter(Lead.is_active.is_(True), Lead.email.isnot(None), Lead.email != "")
            if lead_send_state == "emailed":
                leads_query = leads_query.filter(Lead.last_emailed_at.isnot(None))
            elif lead_send_state == "not_emailed":
                leads_query = leads_query.filter(Lead.last_emailed_at.is_(None))
            leads = leads_query.all()
            if not leads:
                flash("No leads found for selected filter.", "error")
                return redirect(url_for("crm.template_list") + "#send-lead-bulk")

            sent = failed = 0
            email_service = EmailService(current_app)
            for lead in leads:
                macro_values = _lead_macro_values(lead)
                rendered_subject = render_macros(template.subject_template, macro_values)
                rendered_body = render_macros(template.body_template, macro_values)
                result = email_service.send_html_email(lead.email, rendered_subject, rendered_body)
                lead.last_emailed_at = datetime.utcnow()
                lead.last_email_status = result.status
                db.session.add(EmailLog(
                    customer_id=None,
                    template_id=template.id,
                    recipient_email=lead.email,
                    email_type="lead-bulk",
                    subject=rendered_subject,
                    body=rendered_body,
                    status=result.status,
                    error_message=result.error,
                ))
                if result.success or result.status == "dev-mode":
                    sent += 1
                else:
                    failed += 1
            db.session.commit()
            flash(f"Lead promotional bulk email done: {sent} sent, {failed} failed.", "success" if not failed else "error")
            return redirect(url_for("crm.template_list") + "#send-lead-bulk")

        return redirect(url_for("crm.template_list"))

    return _render()


@crm_bp.route("/configuration", methods=["GET", "POST"])
def configuration():
    _ensure_default_statuses()
    _ensure_default_segments()
    _ensure_default_cloud_operators()
    _ensure_default_sow_master_template()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "save_smtp":
            SystemSetting.set_value("smtp.host", (request.form.get("smtp_host") or "").strip())
            SystemSetting.set_value("smtp.port", (request.form.get("smtp_port") or "587").strip())
            SystemSetting.set_value("smtp.username", (request.form.get("smtp_username") or "").strip())
            SystemSetting.set_value("smtp.password", (request.form.get("smtp_password") or "").strip())
            SystemSetting.set_value("smtp.use_tls", "true" if request.form.get("smtp_use_tls") else "false")
            SystemSetting.set_value("smtp.mail_from", (request.form.get("smtp_mail_from") or "").strip())
            db.session.commit()
            flash("SMTP configuration saved.", "success")

        elif action == "test_smtp":
            test_to = (request.form.get("test_email_to") or "").strip()
            if not test_to or "@" not in test_to:
                flash("Please enter a valid test recipient email.", "error")
            else:
                email_service = EmailService(current_app)
                tpl, subject, body = _render_system_email_template(
                    "smtp_test",
                    {
                        "today": datetime.utcnow().date().isoformat(),
                        "test_email_to": test_to,
                    },
                )
                result = email_service.send_html_email(test_to, subject, body)
                db.session.add(EmailLog(
                    customer_id=None,
                    template_id=tpl.id if tpl else None,
                    recipient_email=test_to,
                    email_type="smtp-test",
                    subject=subject,
                    body=body,
                    status=result.status,
                    error_message=result.error,
                ))
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    if result.success or result.status == "dev-mode":
                        flash(
                            "SMTP test email sent, but log insert failed due to old DB schema. Restart app once to auto-fix.",
                            "error",
                        )
                    else:
                        flash(f"SMTP test failed: {result.error}", "error")
                    return redirect(url_for("crm.configuration") + "#smtp-config")
                if result.success or result.status == "dev-mode":
                    flash(f"Test email sent to {test_to} (status: {result.status}).", "success")
                else:
                    flash(f"SMTP test failed: {result.error}", "error")

        elif action == "add_template":
            name = (request.form.get("name") or "").strip()
            subject_template = (request.form.get("subject_template") or "").strip()
            body_template = _sanitize_email_template_body(request.form.get("body_template") or "")
            if not name or not subject_template or not body_template:
                flash("Template name, subject, and body are required.", "error")
            elif EmailTemplate.query.filter_by(name=name).first():
                flash("Template name already exists.", "error")
            else:
                db.session.add(EmailTemplate(
                    name=name,
                    subject_template=subject_template,
                    body_template=body_template,
                ))
                db.session.commit()
                flash("Email template created.", "success")
            return redirect(url_for("crm.configuration") + "#email-template-config")

        elif action == "edit_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if not tpl:
                flash("Template not found.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")

            name = (request.form.get("name") or "").strip()
            subject_template = (request.form.get("subject_template") or "").strip()
            body_template = _sanitize_email_template_body(request.form.get("body_template") or "")
            if not name or not subject_template or not body_template:
                flash("Template name, subject, and body are required.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")

            duplicate = EmailTemplate.query.filter(
                EmailTemplate.name == name,
                EmailTemplate.id != tpl.id,
            ).first()
            if duplicate:
                flash("Another template already uses that name.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")

            tpl.name = name
            tpl.subject_template = subject_template
            tpl.body_template = body_template
            db.session.commit()
            flash("Email template updated.", "success")
            return redirect(url_for("crm.configuration") + "#email-template-config")

        elif action == "delete_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if not tpl:
                flash("Template not found.", "error")
            elif _is_system_template_name(tpl.name):
                flash("System templates cannot be deleted. You can edit them.", "error")
            else:
                db.session.delete(tpl)
                db.session.commit()
                flash("Email template deleted.", "success")
            return redirect(url_for("crm.configuration") + "#email-template-config")

        elif action == "test_email_template":
            template_id = request.form.get("template_id", type=int)
            test_to = (request.form.get("test_email_to") or "").strip()
            customer_id = request.form.get("test_customer_id", type=int)

            if not template_id:
                flash("Please select an email template.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")
            if not test_to or "@" not in test_to:
                flash("Please enter a valid recipient email for test.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")

            template = EmailTemplate.query.get(template_id)
            if not template:
                flash("Template not found.", "error")
                return redirect(url_for("crm.configuration") + "#email-template-config")

            customer = Customer.query.get(customer_id) if customer_id else None
            template_text = f"{template.subject_template or ''}\n{template.body_template or ''}"
            needs_customer_context = (
                "{{meeting_availability_form_link}}" in template_text
                or "{{meeting_availability_expires_at}}" in template_text
            )

            if needs_customer_context and not customer:
                flash(
                    "This template needs opportunity/customer context. Please choose a customer for test send.",
                    "error",
                )
                return redirect(url_for("crm.configuration") + "#email-template-config")

            if customer:
                macro_values = _build_template_macro_values_for_customer(customer, template, recipient_email=test_to)
                rendered_subject = render_macros(template.subject_template, macro_values)
                rendered_body = render_macros(template.body_template, macro_values)
            else:
                rendered_subject = template.subject_template
                rendered_body = template.body_template

            email_service = EmailService(current_app)
            result = email_service.send_html_email(test_to, rendered_subject, rendered_body)
            db.session.add(EmailLog(
                customer_id=customer.id if customer else None,
                template_id=template.id,
                recipient_email=test_to,
                email_type="template-test",
                subject=rendered_subject,
                body=rendered_body,
                status=result.status,
                error_message=result.error,
            ))
            db.session.commit()

            if result.success or result.status == "dev-mode":
                flash(
                    f"Template test email sent to {test_to} (status: {result.status}).",
                    "success",
                )
            else:
                flash(f"Template test failed: {result.error}", "error")
            return redirect(url_for("crm.configuration") + "#email-template-config")

        elif action == "save_teams":
            SystemSetting.set_value("teams.tenant_id", (request.form.get("teams_tenant_id") or "").strip())
            SystemSetting.set_value("teams.client_id", (request.form.get("teams_client_id") or "").strip())
            SystemSetting.set_value("teams.client_secret", (request.form.get("teams_client_secret") or "").strip())
            SystemSetting.set_value("teams.organizer_id", (request.form.get("teams_organizer_id") or "").strip())
            SystemSetting.set_value(
                "teams.default_duration_minutes",
                (request.form.get("teams_default_duration_minutes") or "60").strip(),
            )
            db.session.commit()
            flash("Teams configuration saved.", "success")

        elif action == "save_meeting_settings":
            raw_days = (request.form.get("meeting_availability_link_expiry_days") or "7").strip()
            try:
                expiry_days = int(raw_days)
            except ValueError:
                flash("Availability link expiry must be a number.", "error")
                return redirect(url_for("crm.configuration"))

            if expiry_days < 1 or expiry_days > 90:
                flash("Availability link expiry must be between 1 and 90 days.", "error")
                return redirect(url_for("crm.configuration"))

            SystemSetting.set_value("meeting.availability_link_expiry_days", str(expiry_days))
            db.session.commit()
            flash("Meeting availability settings saved.", "success")

        elif action == "save_app_settings":
            app_base_url = (request.form.get("app_base_url") or "").strip()
            if not app_base_url.startswith("http://") and not app_base_url.startswith("https://"):
                flash("App Base URL must start with http:// or https://", "error")
                return redirect(url_for("crm.configuration"))

            SystemSetting.set_value("app.base_url", app_base_url.rstrip("/"))
            db.session.commit()
            flash("Application URL settings saved.", "success")

        elif action == "save_ai_settings":
            active_provider = (request.form.get("ai_active_provider") or "openai").strip().lower()
            current_active_provider = (
                (SystemSetting.get_value("ai.active_provider", None)
                or SystemSetting.get_value("ai.provider", "openai")
                or "openai")
                .strip()
                .lower()
            )
            # If provider selection changed, force activation to keep one active provider deterministic.
            activate_selected_provider = bool(request.form.get("ai_activate_selected_provider")) or (
                active_provider != current_active_provider
            )
            current_openai_api_key = (SystemSetting.get_value("ai.openai.api_key", "") or "").strip()
            current_openai_model = (SystemSetting.get_value("ai.openai.model", "gpt-4o-mini") or "gpt-4o-mini").strip()
            current_openai_base_url = (SystemSetting.get_value("ai.openai.base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1").strip()
            current_gemini_api_key = (SystemSetting.get_value("ai.gemini.api_key", "") or "").strip()
            current_gemini_model = (SystemSetting.get_value("ai.gemini.model", "gemini-1.5-flash") or "gemini-1.5-flash").strip()
            current_gemini_base_url = (SystemSetting.get_value("ai.gemini.base_url", "https://generativelanguage.googleapis.com/v1beta") or "https://generativelanguage.googleapis.com/v1beta").strip()

            openai_api_key = (request.form.get("openai_api_key") or current_openai_api_key).strip()
            openai_model = (request.form.get("openai_model") or current_openai_model or "gpt-4o-mini").strip()
            openai_base_url = (request.form.get("openai_base_url") or current_openai_base_url or "https://api.openai.com/v1").strip()
            gemini_api_key = (request.form.get("gemini_api_key") or current_gemini_api_key).strip()
            gemini_model = (request.form.get("gemini_model") or current_gemini_model or "gemini-1.5-flash").strip()
            gemini_base_url = (request.form.get("gemini_base_url") or current_gemini_base_url or "https://generativelanguage.googleapis.com/v1beta").strip()

            if active_provider not in {"openai", "gemini"}:
                flash("Active provider must be either openai or gemini.", "error")
                return redirect(url_for("crm.configuration"))
            if active_provider == "openai":
                if not openai_base_url.startswith("http://") and not openai_base_url.startswith("https://"):
                    flash("OpenAI Base URL must start with http:// or https://", "error")
                    return redirect(url_for("crm.configuration") + "#ai-config")
                if not openai_model:
                    flash("OpenAI model is required.", "error")
                    return redirect(url_for("crm.configuration") + "#ai-config")
            else:
                if not gemini_base_url.startswith("http://") and not gemini_base_url.startswith("https://"):
                    flash("Gemini Base URL must start with http:// or https://", "error")
                    return redirect(url_for("crm.configuration") + "#ai-config")
                if not gemini_model:
                    flash("Gemini model is required.", "error")
                    return redirect(url_for("crm.configuration") + "#ai-config")

            activation_warning = None
            if activate_selected_provider and active_provider == "openai" and not openai_api_key:
                activation_warning = "OpenAI is activated, but API key is empty. AI generation will fail until you add it."
            if activate_selected_provider and active_provider == "gemini" and not gemini_api_key:
                activation_warning = "Gemini is activated, but API key is empty. AI generation will fail until you add it."

            SystemSetting.set_value("ai.openai.api_key", openai_api_key)
            SystemSetting.set_value("ai.openai.model", openai_model)
            SystemSetting.set_value("ai.openai.base_url", openai_base_url.rstrip("/"))
            SystemSetting.set_value("ai.gemini.api_key", gemini_api_key)
            SystemSetting.set_value("ai.gemini.model", gemini_model)
            SystemSetting.set_value("ai.gemini.base_url", gemini_base_url.rstrip("/"))

            if activate_selected_provider:
                SystemSetting.set_value("ai.active_provider", active_provider)
                SystemSetting.set_value("ai.provider", active_provider)

                # Legacy compatibility key for old code paths.
                if active_provider == "openai":
                    SystemSetting.set_value("ai.api_key", openai_api_key)
                else:
                    SystemSetting.set_value("ai.api_key", gemini_api_key)

            db.session.commit()
            if activate_selected_provider:
                flash(
                    f"AI settings saved. Activated provider: {active_provider}. Previous provider is now inactive.",
                    "success",
                )
                if activation_warning:
                    flash(activation_warning, "error")
            else:
                flash("AI settings saved. Active provider unchanged.", "success")

        elif action == "activate_ai_provider":
            provider = (request.form.get("provider") or "").strip().lower()
            if provider not in {"openai", "gemini"}:
                flash("Provider must be either openai or gemini.", "error")
                return redirect(url_for("crm.configuration") + "#ai-config")

            openai_api_key = (SystemSetting.get_value("ai.openai.api_key", "") or "").strip()
            gemini_api_key = (SystemSetting.get_value("ai.gemini.api_key", "") or "").strip()

            activation_warning = None
            if provider == "openai" and not openai_api_key:
                activation_warning = "OpenAI is activated, but API key is empty. AI generation will fail until you add it."
            if provider == "gemini" and not gemini_api_key:
                activation_warning = "Gemini is activated, but API key is empty. AI generation will fail until you add it."

            SystemSetting.set_value("ai.active_provider", provider)
            SystemSetting.set_value("ai.provider", provider)

            # Legacy compatibility key for old code paths.
            if provider == "openai":
                SystemSetting.set_value("ai.api_key", openai_api_key)
            else:
                SystemSetting.set_value("ai.api_key", gemini_api_key)

            db.session.commit()
            flash(f"Active AI provider switched to {provider}.", "success")
            if activation_warning:
                flash(activation_warning, "error")
            return redirect(url_for("crm.configuration") + "#ai-config")

        elif action == "add_sow_master_template":
            template_name = (request.form.get("sow_template_name") or "").strip()
            if not template_name:
                flash("Template name is required.", "error")
                return redirect(url_for("crm.configuration") + "#sow-master-config")

            key = _generate_unique_sow_template_key(template_name)

            master = _create_master_template(template_name, key)
            db.session.add(master)
            db.session.commit()
            _ensure_template_sections(master)
            flash("Document template added.", "success")
            return redirect(
                url_for("crm.configuration", sow_template_id=master.id)
                + "#sow-master-config"
            )

        elif action == "duplicate_sow_master_template":
            source_id = request.form.get("sow_template_id", type=int)
            source = SOWMasterTemplate.query.get(source_id)
            if not source:
                flash("Selected document template was not found.", "error")
                return redirect(url_for("crm.configuration") + "#sow-master-config")

            new_name = f"{source.template_name} Copy"
            new_key = _generate_unique_sow_template_key(new_name)
            duplicate = _create_master_template(new_name, new_key)
            duplicate.content_html = source.content_html
            duplicate.updated_by = _actor_name()
            duplicate.updated_at = datetime.utcnow()

            db.session.add(duplicate)
            db.session.commit()
            source_sections = _ensure_template_sections(source)
            for section in source_sections:
                db.session.add(
                    SOWMasterTemplateSection(
                        template_id=duplicate.id,
                        section_name=section.section_name,
                        sequence_no=section.sequence_no,
                        content_html=section.content_html,
                    )
                )
            db.session.commit()
            flash("Document template duplicated.", "success")
            return redirect(
                url_for("crm.configuration", sow_template_id=duplicate.id)
                + "#sow-master-config"
            )

        elif action == "delete_sow_master_template":
            template_id = request.form.get("sow_template_id", type=int)
            template_obj = SOWMasterTemplate.query.get(template_id)
            if not template_obj:
                flash("Selected document template was not found.", "error")
                return redirect(url_for("crm.configuration") + "#sow-master-config")

            total_templates = SOWMasterTemplate.query.count()
            if total_templates <= 1:
                flash("At least one document template must exist.", "error")
                return redirect(
                    url_for("crm.configuration", sow_template_id=template_obj.id)
                    + "#sow-master-config"
                )

            usage_count = CustomerSOW.query.filter_by(master_template_id=template_obj.id).count()
            if usage_count > 0:
                flash("Cannot delete template because it is already used by opportunities.", "error")
                return redirect(
                    url_for("crm.configuration", sow_template_id=template_obj.id)
                    + "#sow-master-config"
                )

            fallback = SOWMasterTemplate.query.filter(SOWMasterTemplate.id != template_obj.id).order_by(SOWMasterTemplate.id.asc()).first()
            SOWMasterTemplateSection.query.filter_by(template_id=template_obj.id).delete(synchronize_session=False)
            db.session.delete(template_obj)
            db.session.commit()
            flash("Document template deleted.", "success")
            return redirect(
                url_for("crm.configuration", sow_template_id=fallback.id if fallback else None)
                + "#sow-master-config"
            )

        elif action == "add_status":
            name = (request.form.get("status_name") or "").strip()
            color = (request.form.get("status_color") or "#8a8f98").strip()

            if not name:
                flash("Status name is required.", "error")
            elif OpportunityStatus.query.filter_by(name=name).first():
                flash("Status already exists.", "error")
            else:
                db.session.add(OpportunityStatus(name=name, color=color, is_active=True))
                db.session.commit()
                flash("Status added.", "success")

        elif action == "update_status":
            status_id = request.form.get("status_id", type=int)
            name = (request.form.get("status_name") or "").strip()
            color = (request.form.get("status_color") or "#8a8f98").strip()

            status_obj = OpportunityStatus.query.get(status_id)
            if not status_obj:
                flash("Status not found.", "error")
            elif not name:
                flash("Status name is required.", "error")
            else:
                duplicate = OpportunityStatus.query.filter(
                    OpportunityStatus.name == name,
                    OpportunityStatus.id != status_obj.id,
                ).first()
                if duplicate:
                    flash("Another status already uses this name.", "error")
                else:
                    old_name = status_obj.name
                    status_obj.name = name
                    status_obj.color = color
                    if old_name != name:
                        Customer.query.filter(Customer.deal_status == old_name).update(
                            {Customer.deal_status: name},
                            synchronize_session=False,
                        )
                    db.session.commit()
                    flash("Status updated.", "success")

        elif action == "delete_status":
            status_id = request.form.get("status_id", type=int)
            status_obj = OpportunityStatus.query.get(status_id)
            if not status_obj:
                flash("Status not found.", "error")
            else:
                Customer.query.filter(Customer.deal_status == status_obj.name).update(
                    {Customer.deal_status: ""},
                    synchronize_session=False,
                )
                db.session.delete(status_obj)
                db.session.commit()
                flash("Status deleted.", "success")

        elif action == "add_segment":
            name = (request.form.get("segment_name") or "").strip()

            if not name:
                flash("Segment name is required.", "error")
            elif OpportunitySegment.query.filter_by(name=name).first():
                flash("Segment already exists.", "error")
            else:
                db.session.add(OpportunitySegment(name=name, is_active=True))
                db.session.commit()
                flash("Segment added.", "success")

        elif action == "update_segment":
            segment_id = request.form.get("segment_id", type=int)
            name = (request.form.get("segment_name") or "").strip()

            segment_obj = OpportunitySegment.query.get(segment_id)
            if not segment_obj:
                flash("Segment not found.", "error")
            elif not name:
                flash("Segment name is required.", "error")
            else:
                duplicate = OpportunitySegment.query.filter(
                    OpportunitySegment.name == name,
                    OpportunitySegment.id != segment_obj.id,
                ).first()
                if duplicate:
                    flash("Another segment already uses this name.", "error")
                else:
                    old_name = segment_obj.name
                    segment_obj.name = name
                    if old_name != name:
                        Customer.query.filter(Customer.segment == old_name).update(
                            {Customer.segment: name},
                            synchronize_session=False,
                        )
                    db.session.commit()
                    flash("Segment updated.", "success")

        elif action == "delete_segment":
            segment_id = request.form.get("segment_id", type=int)
            segment_obj = OpportunitySegment.query.get(segment_id)
            if not segment_obj:
                flash("Segment not found.", "error")
            else:
                Customer.query.filter(Customer.segment == segment_obj.name).update(
                    {Customer.segment: ""},
                    synchronize_session=False,
                )
                db.session.delete(segment_obj)
                db.session.commit()
                flash("Segment deleted.", "success")

        elif action == "add_cloud_operator":
            name = (request.form.get("cloud_name") or "").strip()

            if not name:
                flash("Cloud operator name is required.", "error")
            elif OpportunityCloudOperator.query.filter_by(name=name).first():
                flash("Cloud operator already exists.", "error")
            else:
                db.session.add(OpportunityCloudOperator(name=name, is_active=True))
                db.session.commit()
                flash("Cloud operator added.", "success")

        elif action == "update_cloud_operator":
            cloud_id = request.form.get("cloud_id", type=int)
            name = (request.form.get("cloud_name") or "").strip()

            cloud_obj = OpportunityCloudOperator.query.get(cloud_id)
            if not cloud_obj:
                flash("Cloud operator not found.", "error")
            elif not name:
                flash("Cloud operator name is required.", "error")
            else:
                duplicate = OpportunityCloudOperator.query.filter(
                    OpportunityCloudOperator.name == name,
                    OpportunityCloudOperator.id != cloud_obj.id,
                ).first()
                if duplicate:
                    flash("Another cloud operator already uses this name.", "error")
                else:
                    old_name = cloud_obj.name
                    cloud_obj.name = name
                    if old_name != name:
                        Customer.query.filter(Customer.cloud == old_name).update(
                            {Customer.cloud: name},
                            synchronize_session=False,
                        )
                    db.session.commit()
                    flash("Cloud operator updated.", "success")

        elif action == "delete_cloud_operator":
            cloud_id = request.form.get("cloud_id", type=int)
            cloud_obj = OpportunityCloudOperator.query.get(cloud_id)
            if not cloud_obj:
                flash("Cloud operator not found.", "error")
            else:
                Customer.query.filter(Customer.cloud == cloud_obj.name).update(
                    {Customer.cloud: ""},
                    synchronize_session=False,
                )
                db.session.delete(cloud_obj)
                db.session.commit()
                flash("Cloud operator deleted.", "success")

        elif action == "add_update_tag":
            name = (request.form.get("tag_name") or "").strip().lower()
            color = (request.form.get("tag_color") or "#6b7280").strip()

            if not name:
                flash("Tag name is required.", "error")
            elif OpportunityUpdateTag.query.filter_by(name=name).first():
                flash("Tag already exists.", "error")
            else:
                db.session.add(OpportunityUpdateTag(name=name, color=color, is_active=True))
                db.session.commit()
                flash("Update tag added.", "success")

        elif action == "update_update_tag":
            tag_id = request.form.get("tag_id", type=int)
            name = (request.form.get("tag_name") or "").strip().lower()
            color = (request.form.get("tag_color") or "#6b7280").strip()

            tag_obj = OpportunityUpdateTag.query.get(tag_id)
            if not tag_obj:
                flash("Tag not found.", "error")
            elif not name:
                flash("Tag name is required.", "error")
            else:
                duplicate = OpportunityUpdateTag.query.filter(
                    OpportunityUpdateTag.name == name,
                    OpportunityUpdateTag.id != tag_obj.id,
                ).first()
                if duplicate:
                    flash("Another tag already uses this name.", "error")
                else:
                    old_name = tag_obj.name
                    tag_obj.name = name
                    tag_obj.color = color
                    if old_name != name:
                        OpportunityHistory.query.filter(OpportunityHistory.tag_name == old_name).update(
                            {OpportunityHistory.tag_name: name},
                            synchronize_session=False,
                        )
                    db.session.commit()
                    flash("Update tag updated.", "success")

        elif action == "delete_update_tag":
            tag_id = request.form.get("tag_id", type=int)
            tag_obj = OpportunityUpdateTag.query.get(tag_id)
            if not tag_obj:
                flash("Tag not found.", "error")
            elif tag_obj.name in {"email", "important", "update", "meeting"}:
                flash("This default tag cannot be deleted.", "error")
            else:
                db.session.delete(tag_obj)
                db.session.commit()
                flash("Update tag deleted.", "success")

        elif action == "add_admin_user":
            username = (request.form.get("admin_username") or "").strip()
            email = (request.form.get("admin_email") or "").strip().lower()
            password = request.form.get("admin_password") or ""

            if not username:
                flash("Admin username is required.", "error")
            elif not email or "@" not in email:
                flash("Valid admin email is required.", "error")
            elif len(password) < 6:
                flash("Admin password must be at least 6 characters.", "error")
            elif User.query.filter_by(username=username).first():
                flash("Admin username already exists.", "error")
            elif User.query.filter_by(email=email).first():
                flash("Admin email already exists.", "error")
            else:
                user = User(username=username, email=email, is_active_user=True)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash("Admin user added.", "success")

        elif action == "restart_app":
            _request_process_restart()
            flash("Restart requested. The service should come back in a few seconds.", "success")

        return redirect(url_for("crm.configuration"))

    smtp_settings = _get_smtp_settings()
    teams_settings = _get_teams_settings()
    meeting_settings = _get_meeting_settings()
    ai_settings = _get_ai_settings()
    app_settings = {
        "base_url": _get_effective_app_base_url(),
    }
    _ensure_default_sow_master_template()
    sow_master_templates = SOWMasterTemplate.query.order_by(SOWMasterTemplate.created_at.asc()).all()
    selected_sow_template_id = request.args.get("sow_template_id", type=int)

    selected_sow_template = None
    if selected_sow_template_id:
        selected_sow_template = next((t for t in sow_master_templates if t.id == selected_sow_template_id), None)
    if not selected_sow_template and sow_master_templates:
        selected_sow_template = sow_master_templates[0]

    selected_sow_template_usage_count = 0
    if selected_sow_template:
        _ensure_template_sections(selected_sow_template)
        selected_sow_template_usage_count = CustomerSOW.query.filter_by(master_template_id=selected_sow_template.id).count()

    statuses = OpportunityStatus.query.order_by(OpportunityStatus.created_at.asc()).all()
    segments = OpportunitySegment.query.order_by(OpportunitySegment.created_at.asc()).all()
    cloud_operators = OpportunityCloudOperator.query.order_by(OpportunityCloudOperator.created_at.asc()).all()
    update_tags = OpportunityUpdateTag.query.order_by(OpportunityUpdateTag.created_at.asc()).all()
    admin_users = User.query.order_by(User.created_at.asc()).all()
    email_templates = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).all()
    customers = Customer.query.order_by(Customer.customer_name.asc()).all()
    active_diagrams = (
        CustomerDiagram.query
        .filter_by(is_active=True)
        .order_by(CustomerDiagram.customer_id.asc(), CustomerDiagram.macro_key.asc())
        .all()
    )
    diagram_macro_map = {}
    for diagram in active_diagrams:
        customer_key = str(diagram.customer_id)
        if customer_key not in diagram_macro_map:
            diagram_macro_map[customer_key] = []
        if (diagram.macro_key or "").strip():
            diagram_macro_map[customer_key].append(
                {
                    "macro_key": diagram.macro_key,
                    "diagram_name": diagram.diagram_name,
                }
            )

    return render_template(
        "configuration.html",
        smtp=smtp_settings,
        teams=teams_settings,
        meeting=meeting_settings,
        ai=ai_settings,
        app_settings=app_settings,
        sow_master_templates=sow_master_templates,
        selected_sow_template=selected_sow_template,
        selected_sow_template_usage_count=selected_sow_template_usage_count,
        sow_template_count=len(sow_master_templates),
        statuses=statuses,
        segments=segments,
        cloud_operators=cloud_operators,
        update_tags=update_tags,
        admin_users=admin_users,
        email_templates=email_templates,
        customers=customers,
        diagram_macro_map=diagram_macro_map,
        email_macro_catalog=_email_template_macro_catalog(),
        system_template_names=_system_template_name_set(),
    )


@crm_bp.route("/configuration/sow-template/<int:template_id>/sections", methods=["GET", "POST"])
@login_required
def configuration_sow_template_sections(template_id):
    _ensure_default_sow_master_template()
    master = SOWMasterTemplate.query.get_or_404(template_id)
    _ensure_template_sections(master)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "add_section":
            section_name = (request.form.get("new_section_name") or "").strip()
            requested_seq = request.form.get("new_section_sequence", type=int)
            if not section_name:
                flash("Section name is required.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))

            max_seq = db.session.query(db.func.max(SOWMasterTemplateSection.sequence_no)).filter_by(template_id=master.id).scalar() or 0
            seq = requested_seq if requested_seq and requested_seq > 0 else max_seq + 1
            db.session.add(
                SOWMasterTemplateSection(
                    template_id=master.id,
                    section_name=section_name,
                    sequence_no=seq,
                    content_html="<p>Add section content here.</p>",
                )
            )
            _normalize_template_section_sequence(master.id)
            master.updated_by = _actor_name()
            master.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Section added.", "success")
            return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))

        if action == "update_section_meta":
            section_id = request.form.get("section_id", type=int)
            section_name = (request.form.get("section_name") or "").strip()
            sequence_no = request.form.get("sequence_no", type=int)
            section = SOWMasterTemplateSection.query.filter_by(id=section_id, template_id=master.id).first()
            if not section:
                flash("Section not found.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))
            if not section_name:
                flash("Section name is required.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id, section_id=section.id))

            section.section_name = section_name
            if sequence_no and sequence_no > 0:
                _move_template_section_to_position(master.id, section.id, sequence_no)
            else:
                _normalize_template_section_sequence(master.id)
            master.updated_by = _actor_name()
            master.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Section metadata updated.", "success")
            return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id, section_id=section.id))

        if action == "delete_section":
            section_id = request.form.get("section_id", type=int)
            section = SOWMasterTemplateSection.query.filter_by(id=section_id, template_id=master.id).first()
            if not section:
                flash("Section not found.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))

            if SOWMasterTemplateSection.query.filter_by(template_id=master.id).count() <= 1:
                flash("At least one section must remain.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id, section_id=section.id))

            db.session.delete(section)
            _normalize_template_section_sequence(master.id)
            master.updated_by = _actor_name()
            master.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Section deleted.", "success")
            return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))

        if action == "save_section_content":
            section_id = request.form.get("section_id", type=int)
            section_content = (request.form.get("section_content") or "").strip()
            section = SOWMasterTemplateSection.query.filter_by(id=section_id, template_id=master.id).first()
            if not section:
                flash("Section not found.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))
            if not section_content:
                flash("Section content cannot be empty.", "error")
                return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id, section_id=section.id))

            section.content_html = section_content
            master.updated_by = _actor_name()
            master.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Section content updated.", "success")
            return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id, section_id=section.id))

        if action == "save_template_title_label":
            label = (request.form.get("document_title_label") or "").strip()
            _set_sow_document_title_label(master.id, label)
            db.session.commit()
            flash("Template document title updated.", "success")
            return redirect(url_for("crm.configuration_sow_template_sections", template_id=master.id))

    sections = _get_template_sections(master)
    selected_section_id = request.args.get("section_id", type=int)
    selected_section = next((s for s in sections if s.id == selected_section_id), None) if selected_section_id else None
    if not selected_section and sections:
        selected_section = sections[0]

    return render_template(
        "sow_template_sections.html",
        master_template=master,
        sections=sections,
        selected_section=selected_section,
        document_title_label=_get_sow_document_title_label(master.id),
    )


@crm_bp.route("/templates/new", methods=["GET", "POST"])
def template_new():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        subject_template = (request.form.get("subject_template") or "").strip()
        body_template = (request.form.get("body_template") or "").strip()

        if not name or not subject_template or not body_template:
            flash("Name, subject, and body are required.", "error")
            return redirect(url_for("crm.template_new"))

        if EmailTemplate.query.filter_by(name=name).first():
            flash("Template name already exists.", "error")
            return redirect(url_for("crm.template_new"))

        db.session.add(EmailTemplate(
            name=name,
            subject_template=subject_template,
            body_template=body_template,
        ))
        db.session.commit()
        flash("Template created.", "success")
        return redirect(url_for("crm.template_list") + "#template-list")

    customers = Customer.query.order_by(Customer.customer_name.asc()).all()
    active_diagrams = (
        CustomerDiagram.query
        .filter_by(is_active=True)
        .order_by(CustomerDiagram.customer_id.asc(), CustomerDiagram.macro_key.asc())
        .all()
    )
    diagram_macro_map = {}
    for diagram in active_diagrams:
        customer_key = str(diagram.customer_id)
        if customer_key not in diagram_macro_map:
            diagram_macro_map[customer_key] = []
        if (diagram.macro_key or "").strip():
            diagram_macro_map[customer_key].append(
                {
                    "macro_key": diagram.macro_key,
                    "diagram_name": diagram.diagram_name,
                }
            )

    return render_template(
        "template_form.html",
        customers=customers,
        diagram_macro_map=diagram_macro_map,
    )


@crm_bp.route("/ai/generate/email-template", methods=["POST"])
@login_required
def ai_generate_email_template():
    data = request.get_json(silent=True) or {}
    objective = (data.get("objective") or "").strip()
    tone = (data.get("tone") or "professional").strip()
    business_context = (data.get("business_context") or "").strip()
    current_subject = (data.get("current_subject") or "").strip()
    current_body = (data.get("current_body") or "").strip()
    current_template_name = (data.get("current_template_name") or "").strip()
    selected_opportunity = (data.get("selected_opportunity") or "").strip()
    preserve_subject = bool(data.get("preserve_subject"))
    raw_macros = data.get("available_macros") or []
    available_macros = [str(item).strip() for item in raw_macros if str(item).strip()]

    context_parts = []
    if business_context:
        context_parts.append(f"Prompt details: {business_context}")
    if current_template_name:
        context_parts.append(f"Current template name: {current_template_name}")
    if current_subject:
        context_parts.append(f"Current subject template: {current_subject}")
    if current_body:
        context_parts.append(f"Current body HTML source: {current_body}")
    if selected_opportunity:
        context_parts.append(f"Opportunity context: {selected_opportunity}")
    if available_macros:
        context_parts.append(
            "Allowed macros for output subject/body: " + ", ".join(available_macros)
        )
        context_parts.append(
            "Do not invent unknown macros. Prefer the allowed macros and keep HTML email friendly."
        )
    if preserve_subject and current_subject:
        context_parts.append(
            "Do not change the subject. Keep exactly this subject template: " + current_subject
        )

    combined_context = "\n".join(context_parts)

    svc = AIService(current_app)
    result = svc.generate_email_template(
        business_context=combined_context,
        objective=objective,
        tone=tone,
    )
    if not result.get("success"):
        return jsonify(success=False, message=result.get("error") or "AI generation failed."), 400

    return jsonify(
        success=True,
        template_name=result.get("template_name"),
        subject_template=result.get("subject_template"),
        body_template=result.get("body_template"),
    )


@crm_bp.route("/ai/generate/sow-section-content", methods=["POST"])
@login_required
def ai_generate_sow_section_content():
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    section_id = data.get("section_id")
    extra_prompt = (data.get("extra_prompt") or "").strip()
    current_content = (data.get("current_content") or "").strip()

    try:
        template_id = int(template_id)
        section_id = int(section_id)
    except (TypeError, ValueError):
        return jsonify(success=False, message="Invalid template or section id."), 400

    master = SOWMasterTemplate.query.get(template_id)
    if not master:
        return jsonify(success=False, message="Document template not found."), 404

    section = SOWMasterTemplateSection.query.filter_by(id=section_id, template_id=master.id).first()
    if not section:
        return jsonify(success=False, message="Section not found for this template."), 404

    sections = _get_template_sections(master)
    section_lines = []
    for s in sections:
        raw_text = re.sub(r"<[^>]+>", " ", s.content_html or "")
        clean_text = re.sub(r"\s+", " ", html.unescape(raw_text)).strip()
        if len(clean_text) > 400:
            clean_text = clean_text[:400] + "..."
        section_lines.append(f"- {s.sequence_no}. {s.section_name}: {clean_text}")

    context_text = "\n".join(
        [
            "Company: Ambifo Technology Pvt Ltd",
            f"Document Template Name: {master.template_name}",
            f"Target Section Name: {section.section_name}",
            f"Target Section Sequence: {section.sequence_no}",
            f"Current Section HTML Content: {current_content or (section.content_html or '')}",
            "All template sections (summary):",
            *section_lines,
        ]
    )

    objective = (
        f"Generate professional HTML content for the document section '{section.section_name}' "
        "for Ambifo Technology. Keep it structured and business-ready. "
        "Use only HTML tags like <h1>, <h2>, <h3>, <p>, <ul>, <li>, <table> when needed. "
        "Do not include <html> or <body> tags. "
        f"Extra prompt guidance: {extra_prompt or 'N/A'}"
    )

    svc = AIService(current_app)
    result = svc.generate_document_content(context_text, objective)
    if not result.get("success"):
        return jsonify(success=False, message=result.get("error") or "AI generation failed."), 400

    return jsonify(success=True, content_html=(result.get("content_html") or "").strip())


@crm_bp.route("/opportunities/<int:customer_id>/ai/generate-document-content", methods=["POST"])
@login_required
def ai_generate_document_content(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}
    objective = (data.get("objective") or "").strip()

    context_text = _build_ai_customer_context(customer)
    svc = AIService(current_app)
    result = svc.generate_document_content(context_text, objective)
    if not result.get("success"):
        return jsonify(success=False, message=result.get("error") or "AI generation failed."), 400

    return jsonify(success=True, content_html=result.get("content_html") or "")


@crm_bp.route("/opportunities/<int:customer_id>/ai/generate-architecture-diagram", methods=["POST"])
@login_required
def ai_generate_architecture_diagram(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}
    use_case = (data.get("use_case") or "").strip()

    context_text = _build_ai_customer_context(customer)
    svc = AIService(current_app)
    result = svc.generate_architecture_diagram(context_text, use_case)
    if not result.get("success"):
        return jsonify(success=False, message=result.get("error") or "AI generation failed."), 400

    return jsonify(
        success=True,
        diagram_name=result.get("diagram_name") or "AI Architecture Diagram",
        macro_key=result.get("macro_key") or "ai_architecture",
        diagram_content=result.get("diagram_content") or "",
    )


@crm_bp.route("/opportunities/<int:customer_id>/send-email", methods=["POST"])
@login_required
def opportunity_send_email(customer_id):
    """AJAX endpoint: send email from the popup modal on the opportunity list."""
    from flask import jsonify
    email_source = (request.form.get("email_source") or "template").strip().lower()
    template_id = request.form.get("template_id", type=int)
    cc_raw = (request.form.get("cc_emails") or "").strip()
    custom_subject = (request.form.get("custom_subject") or "").strip()
    custom_body = (request.form.get("custom_body") or "").strip()

    cc_list = [e.strip() for e in cc_raw.replace(";", ",").split(",") if e.strip()]
    invalid_cc = [e for e in cc_list if not _is_valid_email(e)]
    if invalid_cc:
        return jsonify(success=False, message="Please enter valid CC emails separated by commas."), 400

    customer = Customer.query.get(customer_id)
    template = EmailTemplate.query.get(template_id) if template_id else None

    if not customer:
        return jsonify(success=False, message="Opportunity not found."), 404

    if email_source == "custom":
        if not custom_subject or not custom_body:
            return jsonify(success=False, message="Subject and body are required for custom email."), 400
        rendered_subject = custom_subject
        rendered_body = custom_body
        email_type = "custom"
        template_id_for_log = None
    else:
        if not template:
            return jsonify(success=False, message="Please select a valid template."), 400
        macro_values = _build_template_macro_values_for_customer(
            customer,
            template,
            recipient_email=customer.email,
        )
        rendered_subject = render_macros(template.subject_template, macro_values)
        rendered_body = render_macros(template.body_template, macro_values)
        email_type = "template"
        template_id_for_log = template.id

    email_service = EmailService(current_app)
    result = email_service.send_html_email(
        customer.email,
        rendered_subject,
        rendered_body,
        cc_emails=cc_list,
    )

    email_log = EmailLog(
        customer_id=customer.id,
        template_id=template_id_for_log,
        recipient_email=customer.email,
        email_type=email_type,
        subject=rendered_subject,
        body=rendered_body,
        status=result.status,
        error_message=result.error,
    )
    db.session.add(email_log)
    _log_opportunity_history(
        customer.id,
        action="email-sent",
        changes_summary=(
            f"Email processed from opportunity list to {customer.email}. "
            f"Source: {email_type}. Subject: {rendered_subject}. "
            f"CC: {', '.join(cc_list) if cc_list else 'None'}. Status: {result.status}."
        ),
        tag_name="email",
    )
    db.session.commit()

    if result.success or result.status == "dev-mode":
        return jsonify(success=True, message=f"Email sent (status: {result.status}).")
    return jsonify(success=False, message=f"Email failed: {result.error}"), 500


@crm_bp.route("/emails/send", methods=["GET", "POST"])
def send_template_email():
    selected_customer_id = request.args.get("customer_id", type=int)
    customers = Customer.query.order_by(Customer.customer_name.asc()).all()
    templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()

    if request.method == "POST":
        customer_id = request.form.get("customer_id", type=int)
        template_id = request.form.get("template_id", type=int)

        customer = Customer.query.get(customer_id)
        template = EmailTemplate.query.get(template_id)

        if not customer or not template:
            flash("Select a valid customer and template.", "error")
            return render_template("send_email.html", customers=customers, templates=templates)

        macro_values = _build_template_macro_values_for_customer(
            customer,
            template,
            recipient_email=customer.email,
        )
        rendered_subject = render_macros(template.subject_template, macro_values)
        rendered_body = render_macros(template.body_template, macro_values)

        email_service = EmailService(current_app)
        result = email_service.send_html_email(customer.email, rendered_subject, rendered_body)

        email_log = EmailLog(
            customer_id=customer.id,
            template_id=template.id,
            recipient_email=customer.email,
            email_type="template",
            subject=rendered_subject,
            body=rendered_body,
            status=result.status,
            error_message=result.error,
        )
        db.session.add(email_log)
        _log_opportunity_history(
            customer.id,
            action="email-sent",
            changes_summary=(
                f"Template email processed to {customer.email}. Template: {template.name}. "
                f"Subject: {rendered_subject}. Status: {result.status}."
            ),
            tag_name="email",
        )
        db.session.commit()

        if result.success:
            flash(f"Email processed with status: {result.status}", "success")
        else:
            flash(f"Email failed: {result.error}", "error")

        return redirect(url_for("crm.send_template_email"))

    return render_template(
        "send_email.html",
        customers=customers,
        templates=templates,
        selected_customer_id=selected_customer_id,
    )


@crm_bp.route("/emails/history/<int:log_id>/resend", methods=["POST"])
@login_required
def email_resend(log_id):
    """Resend a previously logged email to the same recipient."""
    log = EmailLog.query.get_or_404(log_id)
    to_addr = log.recipient_email or (log.customer.email if log.customer else None)
    if not to_addr:
        flash("Cannot resend â€” no recipient address stored.", "error")
        return redirect(url_for("crm.template_list") + "#email-history")

    svc = EmailService(current_app)
    result = svc.send_html_email(to_addr, log.subject, log.body)

    db.session.add(EmailLog(
        customer_id=log.customer_id,
        template_id=log.template_id,
        recipient_email=to_addr,
        email_type="resend",
        subject=log.subject,
        body=log.body,
        status=result.status,
        error_message=result.error,
    ))
    if log.customer_id:
        _log_opportunity_history(
            log.customer_id,
            action="email-resent",
            changes_summary=(
                f"Email resend processed to {to_addr}. Subject: {log.subject}. Status: {result.status}."
            ),
            tag_name="email",
        )
    db.session.commit()

    if result.success or result.status == "dev-mode":
        flash(f"Email resent to {to_addr} (status: {result.status}).", "success")
    else:
        flash(f"Resend failed: {result.error}", "error")
    return redirect(url_for("crm.template_list") + "#email-history")


@crm_bp.route("/gathering/send", methods=["GET", "POST"])
def send_gathering_request():
    customers = Customer.query.order_by(Customer.customer_name.asc()).all()
    selected_customer_id = request.args.get("customer_id", type=int)
    default_expiry_days = 7
    form_values = {
        "cc": "",
        "bcc": "",
        "note": "",
        "expiry_days": default_expiry_days,
    }

    if request.method == "POST":
        customer_id = request.form.get("customer_id", type=int)
        note = (request.form.get("note") or "").strip()
        cc_raw = (request.form.get("cc_emails") or "").strip()
        bcc_raw = (request.form.get("bcc_emails") or "").strip()
        expiry_days = request.form.get("expiry_days", type=int) or default_expiry_days
        customer = Customer.query.get(customer_id)

        form_values = {
            "cc": cc_raw,
            "bcc": bcc_raw,
            "note": note,
            "expiry_days": expiry_days,
        }

        cc_list = [e.strip() for e in cc_raw.split(",") if e.strip()]
        bcc_list = [e.strip() for e in bcc_raw.split(",") if e.strip()]

        invalid_cc = [e for e in cc_list if "@" not in e]
        invalid_bcc = [e for e in bcc_list if "@" not in e]
        if invalid_cc or invalid_bcc:
            flash("Please enter valid CC/BCC emails separated by commas.", "error")
            return render_template(
                "send_gathering.html",
                customers=customers,
                selected_customer_id=customer_id,
                default_expiry_days=default_expiry_days,
                form_values=form_values,
            )

        if not customer:
            flash("Select a valid customer.", "error")
            return render_template(
                "send_gathering.html",
                customers=customers,
                selected_customer_id=selected_customer_id,
                default_expiry_days=default_expiry_days,
                form_values=form_values,
            )

        if expiry_days < 1 or expiry_days > 90:
            flash("Expiry must be between 1 and 90 days.", "error")
            return render_template(
                "send_gathering.html",
                customers=customers,
                selected_customer_id=customer_id,
                default_expiry_days=default_expiry_days,
                form_values=form_values,
            )

        token = secrets.token_urlsafe(24)
        access_key = _generate_access_key()
        attachment = request.files.get("gathering_sheet")
        saved_name = None

        if attachment and attachment.filename:
            safe_name = secure_filename(attachment.filename)
            saved_name = f"sheet_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
            target = Path(current_app.config["UPLOAD_FOLDER"]) / saved_name
            attachment.save(target)

        request_record = GatheringRequest(
            token=token,
            customer_id=customer.id,
            note=note,
            expires_at=datetime.utcnow() + timedelta(days=expiry_days),
            access_key_hash=generate_password_hash(access_key),
            access_key_hint=access_key[-4:],
            sheet_file_name=saved_name,
            status="sent",
        )
        db.session.add(request_record)
        db.session.flush()

        form_link = f"{_get_effective_app_base_url()}/gathering/form/{token}"
        expires_at_text = request_record.expires_at.strftime("%Y-%m-%d %H:%M UTC") if request_record.expires_at else ""
        macro_values = build_macro_values(
            customer,
            {
                "gathering_form_link": form_link,
                "gathering_access_key": access_key,
                "gathering_expires_at": expires_at_text,
                "note": note,
            },
        )

        tpl, rendered_subject, rendered_body = _render_system_email_template("gathering_request", macro_values)

        email_service = EmailService(current_app)
        result = email_service.send_html_email(
            customer.email,
            rendered_subject,
            rendered_body,
            cc_emails=cc_list,
            bcc_emails=bcc_list,
        )

        email_log = EmailLog(
            customer_id=customer.id,
            template_id=tpl.id if tpl else None,
            recipient_email=customer.email,
            email_type="gathering",
            subject=rendered_subject,
            body=rendered_body,
            status=result.status,
            error_message=result.error,
        )
        db.session.add(email_log)
        _log_opportunity_history(
            customer.id,
            action="gathering-link-sent",
            changes_summary=(
                f"Gathering request processed to {customer.email}. Subject: {rendered_subject}. "
                f"Expiry: {expires_at_text}. CC: {', '.join(cc_list) if cc_list else 'None'}. "
                f"BCC: {', '.join(bcc_list) if bcc_list else 'None'}. Status: {result.status}."
            ),
            remark=note or None,
            tag_name="gathering",
        )
        db.session.commit()

        if result.success:
            flash(f"Gathering request processed with status: {result.status}", "success")
        else:
            flash(f"Gathering email failed: {result.error}", "error")
        flash(
            f"Secure form link generated. Access key (save now): {access_key} | Expires: {expires_at_text}",
            "success",
        )

        return redirect(url_for("crm.send_gathering_request"))

    return render_template(
        "send_gathering.html",
        customers=customers,
        selected_customer_id=selected_customer_id,
        default_expiry_days=default_expiry_days,
        form_values=form_values,
    )


@crm_bp.route("/gathering/form/<token>", methods=["GET", "POST"])
def gathering_form(token):
    request_record = GatheringRequest.query.filter_by(token=token).first_or_404()
    is_expired = _is_gathering_request_expired(request_record)
    session_key = f"gathering_access_ok_{request_record.id}"
    key_required = bool(request_record.access_key_hash)
    key_verified = bool(session.get(session_key))

    # Locked by admin — block all edits and imports
    if request_record.is_locked:
        return render_template(
            "gathering_form.html",
            request_record=request_record,
            submitted=False,
            is_locked=True,
        )

    if is_expired:
        if request_record.status not in ("submitted", "expired"):
            request_record.status = "expired"
            db.session.commit()
        return render_template(
            "gathering_form.html",
            request_record=request_record,
            submitted=False,
            link_expired=True,
            key_required=False,
        )

    if request.method == "POST" and request.form.get("form_action") == "verify_key":
        entered_key = (request.form.get("access_key") or "").strip().upper()
        if not entered_key:
            return render_template(
                "gathering_form.html",
                request_record=request_record,
                submitted=False,
                key_required=True,
                key_error="Enter the access key shared in the email.",
            )

        if not request_record.access_key_hash or check_password_hash(request_record.access_key_hash, entered_key):
            session[session_key] = True
            request_record.access_verified_at = request_record.access_verified_at or datetime.utcnow()
            db.session.commit()
            return redirect(url_for("crm.gathering_form", token=token))

        return render_template(
            "gathering_form.html",
            request_record=request_record,
            submitted=False,
            key_required=True,
            key_error="Invalid key. Please check the email and try again.",
        )

    if key_required and not key_verified:
        return render_template(
            "gathering_form.html",
            request_record=request_record,
            submitted=False,
            key_required=True,
        )

    if request.method == "POST" and request.form.get("form_action") in (
        "import-main",
        "import-server",
        "import-file-nas",
        "import-block-storage",
    ):
        action = request.form.get("form_action")
        import_errors = []
        import_message = None

        if action == "import-main":
            upload = request.files.get("submitted_sheet")
            if not upload or not upload.filename:
                import_errors.append("Please select a workbook/CSV file for main import.")
            else:
                safe_name = secure_filename(upload.filename)
                final_name = f"submitted_import_{request_record.id}_{safe_name}"
                target = Path(current_app.config["UPLOAD_FOLDER"]) / final_name
                upload.save(target)
                try:
                    s_added, f_added, b_added, parse_errors = _import_uploaded_file_to_all_tables(
                        str(target),
                        request_record.customer_id,
                        request_record.id,
                    )
                    import_errors.extend(parse_errors)
                    imported_total = s_added + f_added + b_added
                    if imported_total:
                        _log_opportunity_history(
                            request_record.customer_id,
                            action="gathering-data-imported",
                            changes_summary=(
                                f"Customer imported workbook - Server: {s_added}, "
                                f"FileNAS: {f_added}, Block Storage: {b_added}."
                            ),
                        )
                        db.session.commit()
                        import_message = (
                            f"Imported rows - Server: {s_added}, FileNAS: {f_added}, "
                            f"Block Storage: {b_added}."
                        )
                    else:
                        import_errors.append("No valid rows found in the selected file.")
                except Exception:
                    import_errors.append("Could not parse file. Please upload a valid CSV/XLSX.")
                finally:
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
        else:
            upload_map = {
                "import-server": ("submitted_server_sheet", "server", "Server"),
                "import-file-nas": ("submitted_file_nas_sheet", "file-nas", "FileNAS"),
                "import-block-storage": ("submitted_block_storage_sheet", "block-storage", "Block Storage"),
            }
            field_name, target_type, target_label = upload_map[action]
            upload = request.files.get(field_name)
            if not upload or not upload.filename:
                import_errors.append(f"Please select a file for {target_label} import.")
            else:
                try:
                    added, parse_errors = _import_uploaded_file_for_target(
                        upload,
                        target_type,
                        request_record.customer_id,
                        request_record.id,
                    )
                    import_errors.extend(parse_errors)
                    if added:
                        _log_opportunity_history(
                            request_record.customer_id,
                            action="gathering-data-imported",
                            changes_summary=f"Customer imported {added} {target_label} row(s).",
                        )
                        db.session.commit()
                        import_message = f"Imported {added} {target_label} row(s)."
                    else:
                        import_errors.append(f"No valid {target_label} rows found in file.")
                except Exception:
                    import_errors.append(f"Could not parse {target_label} import file.")

        return render_template(
            "gathering_form.html",
            request_record=request_record,
            submitted=False,
            import_message=import_message,
            import_errors=import_errors,
        )

    if request.method == "POST":
        request_record.company_website = (request.form.get("company_website") or "").strip()
        request_record.current_tools = (request.form.get("current_tools") or "").strip()
        request_record.pain_points = (request.form.get("pain_points") or "").strip()

        upload = request.files.get("submitted_sheet")
        if upload and upload.filename:
            safe_name = secure_filename(upload.filename)
            final_name = f"submitted_{request_record.id}_{safe_name}"
            target = Path(current_app.config["UPLOAD_FOLDER"]) / final_name
            upload.save(target)
            request_record.submitted_sheet_path = str(target)

            # If customer uploads CSV/XLSX gathering sheet, auto-import all records.
            try:
                s_added, f_added, b_added, _import_errors = _import_uploaded_file_to_all_tables(
                    str(target),
                    request_record.customer_id,
                    request_record.id,
                )
                imported_total = s_added + f_added + b_added
                if imported_total:
                    _log_opportunity_history(
                        request_record.customer_id,
                        action="gathering-data-imported",
                        changes_summary=(
                            f"Customer uploaded sheet import - Server: {s_added}, "
                            f"FileNAS: {f_added}, Block Storage: {b_added}."
                        ),
                    )
            except Exception:
                # Keep form submission resilient even if import parsing fails.
                pass

        # Save structured server rows submitted by the customer
        server_names = request.form.getlist("server_name[]")
        cpu_cores_list = request.form.getlist("cpu_cores[]")
        memory_mb_list = request.form.getlist("memory_mb[]")
        storage_list = request.form.getlist("provisioned_storage_gb[]")
        os_list = request.form.getlist("operating_system[]")
        virtual_list = request.form.getlist("is_virtual[]")
        hypervisor_list = request.form.getlist("hypervisor_name[]")
        cpu_str_list = request.form.getlist("cpu_string[]")
        env_list = request.form.getlist("environment[]")
        sql_list = request.form.getlist("sql_edition[]")
        app_list = request.form.getlist("application[]")
        stype_list = request.form.getlist("storage_type[]")
        cpu_util_list = request.form.getlist("cpu_utilization_peak[]")
        mem_util_list = request.form.getlist("memory_utilization_peak[]")
        tiu_list = request.form.getlist("time_in_use[]")
        cost_list = request.form.getlist("annual_cost_usd[]")

        def _gf(lst, i):
            try:
                v = lst[i].strip() if i < len(lst) else ""
                return float(v) if v else None
            except (ValueError, IndexError):
                return None

        def _gi(lst, i):
            try:
                v = lst[i].strip() if i < len(lst) else ""
                return int(v) if v else None
            except (ValueError, IndexError):
                return None

        def _gs(lst, i):
            return (lst[i] or "").strip() or None if i < len(lst) else None

        for idx, sname in enumerate(server_names):
            if not (sname or "").strip():
                continue
            db.session.add(GatheringServerDetail(
                customer_id=request_record.customer_id,
                gathering_request_id=request_record.id,
                server_name=sname.strip(),
                cpu_cores=_gi(cpu_cores_list, idx),
                memory_mb=_gi(memory_mb_list, idx),
                provisioned_storage_gb=_gf(storage_list, idx),
                operating_system=_gs(os_list, idx),
                is_virtual=(_gs(virtual_list, idx) or "").lower() in ("yes", "true", "1"),
                hypervisor_name=_gs(hypervisor_list, idx),
                cpu_string=_gs(cpu_str_list, idx),
                environment=_gs(env_list, idx),
                sql_edition=_gs(sql_list, idx),
                application=_gs(app_list, idx),
                storage_type=_gs(stype_list, idx),
                cpu_utilization_peak=_gf(cpu_util_list, idx),
                memory_utilization_peak=_gf(mem_util_list, idx),
                time_in_use=_gf(tiu_list, idx),
                annual_cost_usd=_gf(cost_list, idx),
            ))

        # Save FileNAS rows
        file_share_names = request.form.getlist("file_server_share_name[]")
        file_total_used = request.form.getlist("file_total_used_capacity_gb[]")
        file_access_protocol = request.form.getlist("file_access_protocol[]")
        file_total_provisioned = request.form.getlist("file_total_provisioned_capacity_gb[]")
        file_storage_eff_ratio = request.form.getlist("file_storage_efficiency_ratio[]")
        file_peak_iops = request.form.getlist("file_peak_iops[]")
        file_peak_throughput = request.form.getlist("file_peak_throughput_mbps[]")
        file_avg_iops = request.form.getlist("file_average_iops[]")
        file_avg_throughput = request.form.getlist("file_average_throughput_mbps[]")
        file_storage_pool_name = request.form.getlist("file_storage_pool_name[]")
        file_array_name = request.form.getlist("file_array_name[]")
        file_array_vendor = request.form.getlist("file_array_vendor[]")
        file_avg_latency = request.form.getlist("file_average_latency_ms[]")
        file_application = request.form.getlist("file_application[]")

        for idx, name in enumerate(file_share_names):
            if not (name or "").strip():
                continue
            db.session.add(GatheringFileNasDetail(
                customer_id=request_record.customer_id,
                gathering_request_id=request_record.id,
                file_server_share_name=name.strip(),
                total_used_capacity_gb=_gf(file_total_used, idx),
                access_protocol=_gs(file_access_protocol, idx),
                total_provisioned_capacity_gb=_gf(file_total_provisioned, idx),
                storage_efficiency_ratio=_gf(file_storage_eff_ratio, idx),
                peak_iops=_gf(file_peak_iops, idx),
                peak_throughput_mbps=_gf(file_peak_throughput, idx),
                average_iops=_gf(file_avg_iops, idx),
                average_throughput_mbps=_gf(file_avg_throughput, idx),
                storage_pool_name=_gs(file_storage_pool_name, idx),
                array_name=_gs(file_array_name, idx),
                array_vendor=_gs(file_array_vendor, idx),
                average_latency_ms=_gf(file_avg_latency, idx),
                application=_gs(file_application, idx),
            ))

        # Save Block Storage rows
        block_volume_name = request.form.getlist("block_volume_name[]")
        block_total_used = request.form.getlist("block_total_used_capacity_gb[]")
        block_total_provisioned = request.form.getlist("block_total_provisioned_capacity_gb[]")
        block_peak_iops = request.form.getlist("block_peak_iops[]")
        block_peak_throughput = request.form.getlist("block_peak_throughput_mbps[]")
        block_avg_iops = request.form.getlist("block_average_iops[]")
        block_avg_throughput = request.form.getlist("block_average_throughput_mbps[]")
        block_array_name = request.form.getlist("block_array_name[]")
        block_avg_latency = request.form.getlist("block_average_latency_ms[]")
        block_application = request.form.getlist("block_application[]")

        for idx, name in enumerate(block_volume_name):
            if not (name or "").strip():
                continue
            db.session.add(GatheringBlockStorageDetail(
                customer_id=request_record.customer_id,
                gathering_request_id=request_record.id,
                volume_name=name.strip(),
                total_used_capacity_gb=_gf(block_total_used, idx),
                total_provisioned_capacity_gb=_gf(block_total_provisioned, idx),
                peak_iops=_gf(block_peak_iops, idx),
                peak_throughput_mbps=_gf(block_peak_throughput, idx),
                average_iops=_gf(block_avg_iops, idx),
                average_throughput_mbps=_gf(block_avg_throughput, idx),
                array_name=_gs(block_array_name, idx),
                average_latency_ms=_gf(block_avg_latency, idx),
                application=_gs(block_application, idx),
            ))

        if request_record.status not in ("submitted", "locked"):
            request_record.status = "submitted"
        request_record.submitted_at = datetime.utcnow()
        db.session.commit()

        return redirect(url_for("crm.gathering_form", token=token, saved=1))

    saved = request.args.get("saved")
    return render_template(
        "gathering_form.html",
        request_record=request_record,
        submitted=False,
        just_saved=bool(saved),
    )


@crm_bp.route("/gathering/request/<int:request_id>/lock", methods=["POST"])
@login_required
def gathering_request_lock(request_id):
    gr = GatheringRequest.query.get_or_404(request_id)
    gr.is_locked = True
    gr.locked_at = datetime.utcnow()
    gr.locked_by = _actor_name()
    _log_opportunity_history(
        gr.customer_id,
        action="gathering-locked",
        changes_summary=f"Gathering request #{gr.id} locked by {gr.locked_by}.",
    )
    db.session.commit()
    flash("Gathering form locked. Customer can no longer update.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=gr.customer_id, tab="gathering"))


@crm_bp.route("/gathering/request/<int:request_id>/unlock", methods=["POST"])
@login_required
def gathering_request_unlock(request_id):
    gr = GatheringRequest.query.get_or_404(request_id)
    gr.is_locked = False
    gr.locked_at = None
    gr.locked_by = None
    _log_opportunity_history(
        gr.customer_id,
        action="gathering-unlocked",
        changes_summary=f"Gathering request #{gr.id} unlocked by {_actor_name()}.",
    )
    db.session.commit()
    flash("Gathering form unlocked. Customer can update again.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=gr.customer_id, tab="gathering"))


@crm_bp.route("/gathering/request/<int:request_id>/delete", methods=["POST"])
@login_required
def gathering_request_delete(request_id):
    """Delete a gathering link. All collected data rows are preserved on the customer
    by nullifying their gathering_request_id FK before removing the parent record."""
    gr = GatheringRequest.query.get_or_404(request_id)
    customer_id = gr.customer_id

    # Detach child rows — keep them on the customer, just unlink from this request
    GatheringServerDetail.query.filter_by(gathering_request_id=request_id).update(
        {"gathering_request_id": None}, synchronize_session=False
    )
    GatheringFileNasDetail.query.filter_by(gathering_request_id=request_id).update(
        {"gathering_request_id": None}, synchronize_session=False
    )
    GatheringBlockStorageDetail.query.filter_by(gathering_request_id=request_id).update(
        {"gathering_request_id": None}, synchronize_session=False
    )

    _log_opportunity_history(
        customer_id,
        action="gathering-link-deleted",
        changes_summary=f"Gathering link #{request_id} (token …{gr.token[-6:]}) deleted by {_actor_name()}. Collected data preserved.",
    )
    db.session.delete(gr)
    db.session.commit()
    flash("Gathering link deleted. All previously collected data has been preserved.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))


@crm_bp.route("/gathering/request/<int:request_id>/renew", methods=["POST"])
@login_required
def gathering_request_renew(request_id):
    """Generate a brand-new link for the same customer. Old link and its data are untouched."""
    gr = GatheringRequest.query.get_or_404(request_id)
    customer = Customer.query.get_or_404(gr.customer_id)
    expiry_days = request.form.get("expiry_days", type=int) or 7

    new_token = secrets.token_urlsafe(24)
    new_access_key = _generate_access_key()
    new_gr = GatheringRequest(
        token=new_token,
        customer_id=customer.id,
        note=gr.note,
        expires_at=datetime.utcnow() + timedelta(days=expiry_days),
        access_key_hash=generate_password_hash(new_access_key),
        access_key_hint=new_access_key[-4:],
        status="sent",
    )
    db.session.add(new_gr)
    _log_opportunity_history(
        customer.id,
        action="gathering-link-renewed",
        changes_summary=f"New gathering link generated by {_actor_name()} (replaces #{request_id}). Expiry: {expiry_days} days.",
    )
    db.session.commit()
    form_link = f"{_get_effective_app_base_url()}/gathering/form/{new_token}"
    expires_text = new_gr.expires_at.strftime("%Y-%m-%d %H:%M UTC")
    flash(
        f"New link generated — copy the access key now (it will not be shown again): "
        f"{new_access_key} | Expires: {expires_text}",
        "success",
    )
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/gathering/form/<token>/sample.xlsx")
def gathering_form_sample_xlsx(token):
    GatheringRequest.query.filter_by(token=token).first_or_404()

    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        return "openpyxl is not installed on server.", 500

    wb = openpyxl.Workbook()
    ws_instructions = wb.active
    ws_instructions.title = "Instructions"
    ws_instructions.append([
        "This workbook is the data import template for AWS migration assessment. Fill the applicable sheets and upload from the customer form."
    ])

    ws_glossary = wb.create_sheet("Glossary")
    ws_glossary.append(["Attribute Name", "Example", "Requirement", "Notes"])
    ws_glossary.append(["Server Name", "Apache01", "Required for Template sheet", "Unique workload identifier"])
    ws_glossary.append(["File Server/Share Name", "CorpFiles01", "Required for FileNAS rows", "Used for NAS import mapping"])
    ws_glossary.append(["Volume Name", "vol-oracle-prod", "Required for Block Storage rows", "Used for block import mapping"])

    ws_server = wb.create_sheet("Template")
    ws_server.append([
        "Server Name", "CPU Cores", "Memory (MB)", "Provisioned Storage (GB)",
        "Operating System", "Is Virtual?", "Hypervisor Name", "Cpu String",
        "Environment", "SQL Edition", "Application",
        "Cpu Utilization Peak (%)", "Memory Utilization Peak (%)", "Time In-Use (%)",
        "Annual Cost (USD)", "Storage Type",
    ])
    ws_server.append([
        "Apache01", 4, 4096, 500,
        "Windows Server 2012 R2", "Yes", "Host-1", "Intel Xeon E7-8893 v4 @ 3.2GHz",
        "Production", "SQL Server 2012 Enterprise", "Service Now",
        0.60, 0.95, 1.00,
        3400, "HDD",
    ])

    ws_file = wb.create_sheet("FileNAS Storage (If applicable)")
    ws_file.append([
        "File Server/Share Name", "Total Used Capacity (GB) - Usable", "Access Protocol (CIFS/NFS)",
        "Total Provisioned Capacity (GB) - Usable", "Storage Efficiency Ratio (Dedupe/Compression)",
        "Peak  IOPS (reads & writes)", "Peak Throughput (MBps)", "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)", "Storage Pool Name", "Array Name", "Array Vendor",
        "Average Latency (ms)", "Application",
    ])
    ws_file.append([
        "CorpFiles01", 820, "CIFS", 1200, 1.35,
        14500, 1200, 9100, 760, "Pool-A", "NetApp01", "NetApp", 1.8, "File Sharing",
    ])

    ws_block = wb.create_sheet("Block Storage (If applicable)")
    ws_block.append([
        "Volume Name", "Total Used Capacity (GB) - Usable", "Total Provisioned Capacity (GB) - Usable",
        "Peak  IOPS (reads & writes)", "Peak Throughput (MBps)", "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)", "Array Name", "Average Latency (ms)", "Application",
    ])
    ws_block.append([
        "vol-oracle-prod", 2600, 3200, 42000, 1800, 30000, 1260, "PureArray01", 1.2, "Oracle DB",
    ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="gathering_data_sample.xlsx",
    )


@crm_bp.route("/gathering/form/<token>/sample-server.csv")
def gathering_form_sample_server_csv(token):
    GatheringRequest.query.filter_by(token=token).first_or_404()

    columns = [
        "Server Name", "CPU Cores", "Memory (MB)", "Provisioned Storage (GB)",
        "Operating System", "Is Virtual (Yes/No)", "Hypervisor Name", "CPU String",
        "Environment", "SQL Edition", "Application",
        "CPU Util Peak (%)", "Memory Util Peak (%)", "Time In-Use (%)",
        "Annual Cost (USD)", "Storage Type",
    ]
    sample = [
        "Apache01", "4", "4096", "500",
        "Windows Server 2012 R2", "Yes", "Host-1", "Intel Xeon E7-8893 v4 @ 3.2GHz",
        "Production", "SQL Server 2012 Enterprise", "Service Now",
        "0.60", "0.95", "1.00",
        "3400", "HDD",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_data_sample.csv",
    )


@crm_bp.route("/gathering/form/<token>/sample-file-nas.csv")
def gathering_form_sample_file_nas_csv(token):
    GatheringRequest.query.filter_by(token=token).first_or_404()

    columns = [
        "File Server/Share Name",
        "Total Used Capacity (GB) - Usable",
        "Access Protocol (CIFS/NFS)",
        "Total Provisioned Capacity (GB) - Usable",
        "Storage Efficiency Ratio (Dedupe/Compression)",
        "Peak  IOPS (reads & writes)",
        "Peak Throughput (MBps)",
        "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)",
        "Storage Pool Name",
        "Array Name",
        "Array Vendor",
        "Average Latency (ms)",
        "Application",
    ]
    sample = [
        "CorpFiles01", "820", "CIFS", "1200", "1.35", "14500", "1200", "9100", "760",
        "Pool-A", "NetApp01", "NetApp", "1.8", "File Sharing",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_file_nas_sample.csv",
    )


@crm_bp.route("/gathering/form/<token>/sample-block-storage.csv")
def gathering_form_sample_block_storage_csv(token):
    GatheringRequest.query.filter_by(token=token).first_or_404()

    columns = [
        "Volume Name",
        "Total Used Capacity (GB) - Usable",
        "Total Provisioned Capacity (GB) - Usable",
        "Peak  IOPS (reads & writes)",
        "Peak Throughput (MBps)",
        "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)",
        "Array Name",
        "Average Latency (ms)",
        "Application",
    ]
    sample = [
        "vol-oracle-prod", "2600", "3200", "42000", "1800", "30000", "1260", "PureArray01", "1.2", "Oracle DB",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_block_storage_sample.csv",
    )


# â”€â”€ Gathering data: edit row â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/<int:entry_id>/edit", methods=["POST"])
@login_required
def opportunity_gathering_data_edit(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringServerDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid gathering data entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    try:
        server_name = (request.form.get("server_name") or "").strip()
        if not server_name:
            flash("Server name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry.server_name = server_name
        entry.cpu_cores = _to_int(request.form.get("cpu_cores"))
        entry.memory_mb = _to_int(request.form.get("memory_mb"))
        entry.provisioned_storage_gb = _to_float(request.form.get("provisioned_storage_gb"))
        entry.operating_system = (request.form.get("operating_system") or "").strip() or None
        entry.is_virtual = (request.form.get("is_virtual") or "").strip().lower() in ("yes", "true", "1")
        entry.hypervisor_name = (request.form.get("hypervisor_name") or "").strip() or None
        entry.cpu_string = (request.form.get("cpu_string") or "").strip() or None
        entry.environment = (request.form.get("environment") or "").strip() or None
        entry.sql_edition = (request.form.get("sql_edition") or "").strip() or None
        entry.application = (request.form.get("application") or "").strip() or None
        entry.storage_type = (request.form.get("storage_type") or "").strip() or None
        entry.cpu_utilization_peak = _to_float(request.form.get("cpu_utilization_peak"))
        entry.memory_utilization_peak = _to_float(request.form.get("memory_utilization_peak"))
        entry.time_in_use = _to_float(request.form.get("time_in_use"))
        entry.annual_cost_usd = _to_float(request.form.get("annual_cost_usd"))
        db.session.commit()

        _log_opportunity_history(
            customer.id,
            action="gathering-data-edited",
            changes_summary=f"Gathering data entry updated for server '{entry.server_name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("Gathering data entry updated.", "success")
    except ValueError:
        flash("Please enter valid numeric values for numeric fields.", "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


# â”€â”€ Gathering data: update delete redirect to edit page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/<int:entry_id>/delete-from-edit", methods=["POST"])
@login_required
def opportunity_gathering_data_delete_from_edit(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringServerDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid gathering data entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    sname = entry.server_name
    db.session.delete(entry)
    _log_opportunity_history(
        customer.id,
        action="gathering-data-deleted",
        changes_summary=f"Gathering data entry deleted for server '{sname}'.",
        remark="Deleted from opportunity edit page",
    )
    db.session.commit()
    flash("Gathering data entry deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


# â”€â”€ Gathering data: add from edit page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/add", methods=["POST"])
@login_required
def opportunity_gathering_data_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    try:
        server_name = (request.form.get("server_name") or "").strip()
        if not server_name:
            flash("Server name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry = GatheringServerDetail(
            customer_id=customer.id,
            server_name=server_name,
            cpu_cores=_to_int(request.form.get("cpu_cores")),
            memory_mb=_to_int(request.form.get("memory_mb")),
            provisioned_storage_gb=_to_float(request.form.get("provisioned_storage_gb")),
            operating_system=(request.form.get("operating_system") or "").strip() or None,
            is_virtual=(request.form.get("is_virtual") or "").strip().lower() in ("yes", "true", "1"),
            hypervisor_name=(request.form.get("hypervisor_name") or "").strip() or None,
            cpu_string=(request.form.get("cpu_string") or "").strip() or None,
            environment=(request.form.get("environment") or "").strip() or None,
            sql_edition=(request.form.get("sql_edition") or "").strip() or None,
            application=(request.form.get("application") or "").strip() or None,
            storage_type=(request.form.get("storage_type") or "").strip() or None,
            cpu_utilization_peak=_to_float(request.form.get("cpu_utilization_peak")),
            memory_utilization_peak=_to_float(request.form.get("memory_utilization_peak")),
            time_in_use=_to_float(request.form.get("time_in_use")),
            annual_cost_usd=_to_float(request.form.get("annual_cost_usd")),
        )
        db.session.add(entry)
        _log_opportunity_history(
            customer.id,
            action="gathering-data-added",
            changes_summary=f"Gathering data entry added for server '{server_name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("Gathering data row saved.", "success")
    except ValueError:
        flash("Please enter valid numeric values.", "error")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-file-nas/add", methods=["POST"])
@login_required
def opportunity_gathering_file_nas_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    try:
        name = (request.form.get("file_server_share_name") or "").strip()
        if not name:
            flash("File Server/Share Name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry = GatheringFileNasDetail(
            customer_id=customer.id,
            file_server_share_name=name,
            total_used_capacity_gb=_to_float(request.form.get("total_used_capacity_gb")),
            access_protocol=(request.form.get("access_protocol") or "").strip() or None,
            total_provisioned_capacity_gb=_to_float(request.form.get("total_provisioned_capacity_gb")),
            storage_efficiency_ratio=_to_float(request.form.get("storage_efficiency_ratio")),
            peak_iops=_to_float(request.form.get("peak_iops")),
            peak_throughput_mbps=_to_float(request.form.get("peak_throughput_mbps")),
            average_iops=_to_float(request.form.get("average_iops")),
            average_throughput_mbps=_to_float(request.form.get("average_throughput_mbps")),
            storage_pool_name=(request.form.get("storage_pool_name") or "").strip() or None,
            array_name=(request.form.get("array_name") or "").strip() or None,
            array_vendor=(request.form.get("array_vendor") or "").strip() or None,
            average_latency_ms=_to_float(request.form.get("average_latency_ms")),
            application=(request.form.get("application") or "").strip() or None,
        )
        db.session.add(entry)
        _log_opportunity_history(
            customer.id,
            action="gathering-file-nas-added",
            changes_summary=f"FileNAS entry added: '{name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("FileNAS row saved.", "success")
    except ValueError:
        flash("Please enter valid numeric values.", "error")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-file-nas/<int:entry_id>/edit", methods=["POST"])
@login_required
def opportunity_gathering_file_nas_edit(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringFileNasDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid FileNAS entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    try:
        name = (request.form.get("file_server_share_name") or "").strip()
        if not name:
            flash("File Server/Share Name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry.file_server_share_name = name
        entry.total_used_capacity_gb = _to_float(request.form.get("total_used_capacity_gb"))
        entry.access_protocol = (request.form.get("access_protocol") or "").strip() or None
        entry.total_provisioned_capacity_gb = _to_float(request.form.get("total_provisioned_capacity_gb"))
        entry.storage_efficiency_ratio = _to_float(request.form.get("storage_efficiency_ratio"))
        entry.peak_iops = _to_float(request.form.get("peak_iops"))
        entry.peak_throughput_mbps = _to_float(request.form.get("peak_throughput_mbps"))
        entry.average_iops = _to_float(request.form.get("average_iops"))
        entry.average_throughput_mbps = _to_float(request.form.get("average_throughput_mbps"))
        entry.storage_pool_name = (request.form.get("storage_pool_name") or "").strip() or None
        entry.array_name = (request.form.get("array_name") or "").strip() or None
        entry.array_vendor = (request.form.get("array_vendor") or "").strip() or None
        entry.average_latency_ms = _to_float(request.form.get("average_latency_ms"))
        entry.application = (request.form.get("application") or "").strip() or None
        db.session.commit()

        _log_opportunity_history(
            customer.id,
            action="gathering-file-nas-edited",
            changes_summary=f"FileNAS entry updated: '{name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("FileNAS row updated.", "success")
    except ValueError:
        flash("Please enter valid numeric values.", "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-file-nas/<int:entry_id>/delete", methods=["POST"])
@login_required
def opportunity_gathering_file_nas_delete(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringFileNasDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid FileNAS entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    name = entry.file_server_share_name
    db.session.delete(entry)
    _log_opportunity_history(
        customer.id,
        action="gathering-file-nas-deleted",
        changes_summary=f"FileNAS entry deleted: '{name}'.",
        remark="Deleted from opportunity edit page",
    )
    db.session.commit()
    flash("FileNAS row deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-block-storage/add", methods=["POST"])
@login_required
def opportunity_gathering_block_storage_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    try:
        name = (request.form.get("volume_name") or "").strip()
        if not name:
            flash("Volume Name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry = GatheringBlockStorageDetail(
            customer_id=customer.id,
            volume_name=name,
            total_used_capacity_gb=_to_float(request.form.get("total_used_capacity_gb")),
            total_provisioned_capacity_gb=_to_float(request.form.get("total_provisioned_capacity_gb")),
            peak_iops=_to_float(request.form.get("peak_iops")),
            peak_throughput_mbps=_to_float(request.form.get("peak_throughput_mbps")),
            average_iops=_to_float(request.form.get("average_iops")),
            average_throughput_mbps=_to_float(request.form.get("average_throughput_mbps")),
            array_name=(request.form.get("array_name") or "").strip() or None,
            average_latency_ms=_to_float(request.form.get("average_latency_ms")),
            application=(request.form.get("application") or "").strip() or None,
        )
        db.session.add(entry)
        _log_opportunity_history(
            customer.id,
            action="gathering-block-storage-added",
            changes_summary=f"Block Storage entry added: '{name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("Block Storage row saved.", "success")
    except ValueError:
        flash("Please enter valid numeric values.", "error")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-block-storage/<int:entry_id>/edit", methods=["POST"])
@login_required
def opportunity_gathering_block_storage_edit(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringBlockStorageDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid Block Storage entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    try:
        name = (request.form.get("volume_name") or "").strip()
        if not name:
            flash("Volume Name is required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        entry.volume_name = name
        entry.total_used_capacity_gb = _to_float(request.form.get("total_used_capacity_gb"))
        entry.total_provisioned_capacity_gb = _to_float(request.form.get("total_provisioned_capacity_gb"))
        entry.peak_iops = _to_float(request.form.get("peak_iops"))
        entry.peak_throughput_mbps = _to_float(request.form.get("peak_throughput_mbps"))
        entry.average_iops = _to_float(request.form.get("average_iops"))
        entry.average_throughput_mbps = _to_float(request.form.get("average_throughput_mbps"))
        entry.array_name = (request.form.get("array_name") or "").strip() or None
        entry.average_latency_ms = _to_float(request.form.get("average_latency_ms"))
        entry.application = (request.form.get("application") or "").strip() or None
        db.session.commit()

        _log_opportunity_history(
            customer.id,
            action="gathering-block-storage-edited",
            changes_summary=f"Block Storage entry updated: '{name}'.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()
        flash("Block Storage row updated.", "success")
    except ValueError:
        flash("Please enter valid numeric values.", "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-block-storage/<int:entry_id>/delete", methods=["POST"])
@login_required
def opportunity_gathering_block_storage_delete(customer_id, entry_id):
    customer = Customer.query.get_or_404(customer_id)
    entry = GatheringBlockStorageDetail.query.get_or_404(entry_id)
    if entry.customer_id != customer.id:
        flash("Invalid Block Storage entry.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    name = entry.volume_name
    db.session.delete(entry)
    _log_opportunity_history(
        customer.id,
        action="gathering-block-storage-deleted",
        changes_summary=f"Block Storage entry deleted: '{name}'.",
        remark="Deleted from opportunity edit page",
    )
    db.session.commit()
    flash("Block Storage row deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/import/<string:import_target>", methods=["POST"])
@login_required
def opportunity_gathering_data_import_single(customer_id, import_target):
    customer = Customer.query.get_or_404(customer_id)
    upload = request.files.get("import_file")
    if not upload or not upload.filename:
        flash("Please select a CSV or XLSX file to import.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    target = (import_target or "").strip().lower()
    if target not in ("server", "file-nas", "block-storage"):
        flash("Invalid import target.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    filename = upload.filename.lower()
    rows = []
    if filename.endswith(".csv"):
        rows = _read_csv_rows(upload.stream)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        try:
            sheets = _read_xlsx_rows_by_sheet(upload.stream)
            # For single import, try matching sheet name first; fallback to first detected non-empty sheet.
            if target == "server":
                rows = sheets.get("template", [])
            elif target == "file-nas":
                rows = sheets.get("filenas storage (if applicable)", [])
            elif target == "block-storage":
                rows = sheets.get("block storage (if applicable)", [])

            if not rows and sheets:
                rows = next(iter(sheets.values()))
        except ImportError:
            flash("openpyxl is not installed. Run: pip install openpyxl", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))
    else:
        flash("Unsupported file format. Use .csv or .xlsx.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    added = 0
    errors = []
    if target == "server":
        added, errors = _import_server_rows(rows, customer.id)
    elif target == "file-nas":
        added, errors = _import_file_nas_rows(rows, customer.id)
    elif target == "block-storage":
        added, errors = _import_block_storage_rows(rows, customer.id)

    if added:
        _log_opportunity_history(
            customer.id,
            action="gathering-data-imported",
            changes_summary=f"Imported {added} row(s) for {target} from single-sheet file.",
        )
        db.session.commit()
        flash(f"Imported {added} row(s) for {target}.", "success")
    else:
        flash(f"No valid rows were imported for {target}.", "error")

    if errors:
        for e in errors[:6]:
            flash(e, "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


# â”€â”€ Gathering data: sample CSV download â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/gathering-data/sample.csv")
@login_required
def gathering_data_sample_csv():
    columns = [
        "Server Name", "CPU Cores", "Memory (MB)", "Provisioned Storage (GB)",
        "Operating System", "Is Virtual (Yes/No)", "Hypervisor Name", "CPU String",
        "Environment", "SQL Edition", "Application",
        "CPU Util Peak (%)", "Memory Util Peak (%)", "Time In-Use (%)",
        "Annual Cost (USD)", "Storage Type",
    ]
    sample = [
        "Apache01", "4", "4096", "500",
        "Windows Server 2012 R2", "Yes", "Host-1", "Intel Xeon E7-8893 v4 @ 3.2GHz",
        "Production", "SQL Server 2012 Enterprise", "Service Now",
        "0.60", "0.95", "1.00",
        "3400", "HDD",
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_data_sample.csv",
    )


@crm_bp.route("/opportunities/gathering-data/sample-file-nas.csv")
@login_required
def gathering_data_sample_file_nas_csv():
    columns = [
        "File Server/Share Name",
        "Total Used Capacity (GB) - Usable",
        "Access Protocol (CIFS/NFS)",
        "Total Provisioned Capacity (GB) - Usable",
        "Storage Efficiency Ratio (Dedupe/Compression)",
        "Peak  IOPS (reads & writes)",
        "Peak Throughput (MBps)",
        "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)",
        "Storage Pool Name",
        "Array Name",
        "Array Vendor",
        "Average Latency (ms)",
        "Application",
    ]
    sample = [
        "CorpFiles01", "820", "CIFS", "1200", "1.35", "14500", "1200", "9100", "760",
        "Pool-A", "NetApp01", "NetApp", "1.8", "File Sharing",
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_file_nas_sample.csv",
    )


@crm_bp.route("/opportunities/gathering-data/sample-block-storage.csv")
@login_required
def gathering_data_sample_block_storage_csv():
    columns = [
        "Volume Name",
        "Total Used Capacity (GB) - Usable",
        "Total Provisioned Capacity (GB) - Usable",
        "Peak  IOPS (reads & writes)",
        "Peak Throughput (MBps)",
        "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)",
        "Array Name",
        "Average Latency (ms)",
        "Application",
    ]
    sample = [
        "vol-oracle-prod", "2600", "3200", "42000", "1800", "30000", "1260", "PureArray01", "1.2", "Oracle DB",
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerow(sample)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="gathering_block_storage_sample.csv",
    )


@crm_bp.route("/opportunities/gathering-data/sample.xlsx")
@login_required
def gathering_data_sample_xlsx():
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        flash("openpyxl is not installed. Run: pip install openpyxl", "error")
        return redirect(url_for("crm.opportunity_list"))

    wb = openpyxl.Workbook()

    ws_instructions = wb.active
    ws_instructions.title = "Instructions"
    ws_instructions.append([
        "This workbook is the data import template for AWS migration assessment. Fill the applicable sheets and upload from Main Import."
    ])

    ws_glossary = wb.create_sheet("Glossary")
    ws_glossary.append(["Attribute Name", "Example", "Requirement", "Notes"])
    ws_glossary.append(["Server Name", "Apache01", "Required for Template sheet", "Unique workload identifier"])
    ws_glossary.append(["File Server/Share Name", "CorpFiles01", "Required for FileNAS rows", "Used for NAS import mapping"])
    ws_glossary.append(["Volume Name", "vol-oracle-prod", "Required for Block Storage rows", "Used for block import mapping"])

    ws_server = wb.create_sheet("Template")
    ws_server.append([
        "Server Name", "CPU Cores", "Memory (MB)", "Provisioned Storage (GB)",
        "Operating System", "Is Virtual?", "Hypervisor Name", "Cpu String",
        "Environment", "SQL Edition", "Application",
        "Cpu Utilization Peak (%)", "Memory Utilization Peak (%)", "Time In-Use (%)",
        "Annual Cost (USD)", "Storage Type",
    ])
    ws_server.append([
        "Apache01", 4, 4096, 500,
        "Windows Server 2012 R2", "Yes", "Host-1", "Intel Xeon E7-8893 v4 @ 3.2GHz",
        "Production", "SQL Server 2012 Enterprise", "Service Now",
        0.60, 0.95, 1.00,
        3400, "HDD",
    ])

    ws_file = wb.create_sheet("FileNAS Storage (If applicable)")
    ws_file.append([
        "File Server/Share Name", "Total Used Capacity (GB) - Usable", "Access Protocol (CIFS/NFS)",
        "Total Provisioned Capacity (GB) - Usable", "Storage Efficiency Ratio (Dedupe/Compression)",
        "Peak  IOPS (reads & writes)", "Peak Throughput (MBps)", "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)", "Storage Pool Name", "Array Name", "Array Vendor",
        "Average Latency (ms)", "Application",
    ])
    ws_file.append([
        "CorpFiles01", 820, "CIFS", 1200, 1.35,
        14500, 1200, 9100, 760, "Pool-A", "NetApp01", "NetApp", 1.8, "File Sharing",
    ])

    ws_block = wb.create_sheet("Block Storage (If applicable)")
    ws_block.append([
        "Volume Name", "Total Used Capacity (GB) - Usable", "Total Provisioned Capacity (GB) - Usable",
        "Peak  IOPS (reads & writes)", "Peak Throughput (MBps)", "Average  IOPS (reads & writes)",
        "Average Throughput (MBps)", "Array Name", "Average Latency (ms)", "Application",
    ])
    ws_block.append([
        "vol-oracle-prod", 2600, 3200, 42000, 1800, 30000, 1260, "PureArray01", 1.2, "Oracle DB",
    ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="gathering_data_sample.xlsx",
    )


# -- Gathering data: CSV / XLSX import (Servers + FileNAS + Block Storage) ---

SERVER_FIELD_MAP = {
    "server name": "server_name",
    "cpu cores": "cpu_cores",
    "memory (mb)": "memory_mb",
    "provisioned storage (gb)": "provisioned_storage_gb",
    "operating system": "operating_system",
    "is virtual?": "is_virtual",
    "is virtual (yes/no)": "is_virtual",
    "hypervisor name": "hypervisor_name",
    "cpu string": "cpu_string",
    "environment": "environment",
    "sql edition": "sql_edition",
    "application": "application",
    "cpu utilization peak (%)": "cpu_utilization_peak",
    "cpu util peak (%)": "cpu_utilization_peak",
    "memory utilization peak (%)": "memory_utilization_peak",
    "memory util peak (%)": "memory_utilization_peak",
    "time in-use (%)": "time_in_use",
    "annual cost (usd)": "annual_cost_usd",
    "storage type": "storage_type",
}

FILE_NAS_FIELD_MAP = {
    "file server/share name": "file_server_share_name",
    "total used capacity (gb) - usable": "total_used_capacity_gb",
    "access protocol (cifs/nfs)": "access_protocol",
    "total provisioned capacity (gb) - usable": "total_provisioned_capacity_gb",
    "storage efficiency ratio (dedupe/compression)": "storage_efficiency_ratio",
    "peak  iops (reads & writes)": "peak_iops",
    "peak iops (reads & writes)": "peak_iops",
    "peak throughput (mbps)": "peak_throughput_mbps",
    "average  iops (reads & writes)": "average_iops",
    "average iops (reads & writes)": "average_iops",
    "average throughput (mbps)": "average_throughput_mbps",
    "storage pool name": "storage_pool_name",
    "array name": "array_name",
    "array vendor": "array_vendor",
    "average latency (ms)": "average_latency_ms",
    "application": "application",
}

BLOCK_STORAGE_FIELD_MAP = {
    "volume name": "volume_name",
    "total used capacity (gb) - usable": "total_used_capacity_gb",
    "total provisioned capacity (gb) - usable": "total_provisioned_capacity_gb",
    "peak  iops (reads & writes)": "peak_iops",
    "peak iops (reads & writes)": "peak_iops",
    "peak throughput (mbps)": "peak_throughput_mbps",
    "average  iops (reads & writes)": "average_iops",
    "average iops (reads & writes)": "average_iops",
    "average throughput (mbps)": "average_throughput_mbps",
    "array name": "array_name",
    "average latency (ms)": "average_latency_ms",
    "application": "application",
}


def _to_float_safe(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    return float(raw)


def _to_int_safe(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    return int(float(raw))


def _normalize_row(row):
    mapped = {}
    for key, value in (row or {}).items():
        k = (str(key or "")).strip().lower()
        mapped[k] = str(value or "").strip()
    return mapped


def _import_server_rows(rows_of_dicts, customer_id, gathering_request_id=None):
    added = 0
    errors = []
    for i, row in enumerate(rows_of_dicts):
        norm = _normalize_row(row)
        mapped = {}
        for raw_col, val in norm.items():
            field = SERVER_FIELD_MAP.get(raw_col)
            if field:
                mapped[field] = val

        sname = mapped.get("server_name", "")
        if not sname:
            continue
        try:
            db.session.add(GatheringServerDetail(
                customer_id=customer_id,
                gathering_request_id=gathering_request_id,
                server_name=sname,
                cpu_cores=_to_int_safe(mapped.get("cpu_cores")),
                memory_mb=_to_int_safe(mapped.get("memory_mb")),
                provisioned_storage_gb=_to_float_safe(mapped.get("provisioned_storage_gb")),
                operating_system=mapped.get("operating_system") or None,
                is_virtual=(mapped.get("is_virtual") or "").lower() in ("yes", "true", "1"),
                hypervisor_name=mapped.get("hypervisor_name") or None,
                cpu_string=mapped.get("cpu_string") or None,
                environment=mapped.get("environment") or None,
                sql_edition=mapped.get("sql_edition") or None,
                application=mapped.get("application") or None,
                storage_type=mapped.get("storage_type") or None,
                cpu_utilization_peak=_to_float_safe(mapped.get("cpu_utilization_peak")),
                memory_utilization_peak=_to_float_safe(mapped.get("memory_utilization_peak")),
                time_in_use=_to_float_safe(mapped.get("time_in_use")),
                annual_cost_usd=_to_float_safe(mapped.get("annual_cost_usd")),
            ))
            added += 1
        except ValueError as exc:
            errors.append(f"Server row {i + 2}: {exc} - skipped.")
    return added, errors


def _import_file_nas_rows(rows_of_dicts, customer_id, gathering_request_id=None):
    added = 0
    errors = []
    for i, row in enumerate(rows_of_dicts):
        norm = _normalize_row(row)
        mapped = {}
        for raw_col, val in norm.items():
            field = FILE_NAS_FIELD_MAP.get(raw_col)
            if field:
                mapped[field] = val

        name = mapped.get("file_server_share_name", "")
        if not name:
            continue
        try:
            db.session.add(GatheringFileNasDetail(
                customer_id=customer_id,
                gathering_request_id=gathering_request_id,
                file_server_share_name=name,
                total_used_capacity_gb=_to_float_safe(mapped.get("total_used_capacity_gb")),
                access_protocol=mapped.get("access_protocol") or None,
                total_provisioned_capacity_gb=_to_float_safe(mapped.get("total_provisioned_capacity_gb")),
                storage_efficiency_ratio=_to_float_safe(mapped.get("storage_efficiency_ratio")),
                peak_iops=_to_float_safe(mapped.get("peak_iops")),
                peak_throughput_mbps=_to_float_safe(mapped.get("peak_throughput_mbps")),
                average_iops=_to_float_safe(mapped.get("average_iops")),
                average_throughput_mbps=_to_float_safe(mapped.get("average_throughput_mbps")),
                storage_pool_name=mapped.get("storage_pool_name") or None,
                array_name=mapped.get("array_name") or None,
                array_vendor=mapped.get("array_vendor") or None,
                average_latency_ms=_to_float_safe(mapped.get("average_latency_ms")),
                application=mapped.get("application") or None,
            ))
            added += 1
        except ValueError as exc:
            errors.append(f"FileNAS row {i + 2}: {exc} - skipped.")
    return added, errors


def _import_block_storage_rows(rows_of_dicts, customer_id, gathering_request_id=None):
    added = 0
    errors = []
    for i, row in enumerate(rows_of_dicts):
        norm = _normalize_row(row)
        mapped = {}
        for raw_col, val in norm.items():
            field = BLOCK_STORAGE_FIELD_MAP.get(raw_col)
            if field:
                mapped[field] = val

        volume_name = mapped.get("volume_name", "")
        if not volume_name:
            continue
        try:
            db.session.add(GatheringBlockStorageDetail(
                customer_id=customer_id,
                gathering_request_id=gathering_request_id,
                volume_name=volume_name,
                total_used_capacity_gb=_to_float_safe(mapped.get("total_used_capacity_gb")),
                total_provisioned_capacity_gb=_to_float_safe(mapped.get("total_provisioned_capacity_gb")),
                peak_iops=_to_float_safe(mapped.get("peak_iops")),
                peak_throughput_mbps=_to_float_safe(mapped.get("peak_throughput_mbps")),
                average_iops=_to_float_safe(mapped.get("average_iops")),
                average_throughput_mbps=_to_float_safe(mapped.get("average_throughput_mbps")),
                array_name=mapped.get("array_name") or None,
                average_latency_ms=_to_float_safe(mapped.get("average_latency_ms")),
                application=mapped.get("application") or None,
            ))
            added += 1
        except ValueError as exc:
            errors.append(f"BlockStorage row {i + 2}: {exc} - skipped.")
    return added, errors


def _read_csv_rows(file_stream):
    content = file_stream.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


def _read_xlsx_rows_by_sheet(file_stream):
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.load_workbook(file_stream, data_only=True)
    sheet_rows = {}
    for ws in wb.worksheets:
        row_iter = ws.iter_rows(min_row=1, max_row=1)
        first = next(row_iter, None)
        if not first:
            continue
        headers = [str(c.value or "").strip() for c in first]
        if not any(headers):
            continue

        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(v not in (None, "") for v in row):
                continue
            rows.append({headers[j]: ("" if row[j] is None else str(row[j])) for j in range(len(headers))})
        sheet_rows[ws.title.strip().lower()] = rows
    return sheet_rows


def _detect_rows_type(rows):
    if not rows:
        return "unknown"
    normalized_keys = {(str(k or "")).strip().lower() for k in rows[0].keys()}
    if "server name" in normalized_keys:
        return "server"
    if "file server/share name" in normalized_keys:
        return "file_nas"
    if "volume name" in normalized_keys:
        return "block_storage"
    return "unknown"


def _import_uploaded_file_to_all_tables(file_path, customer_id, gathering_request_id=None):
    """Import uploaded customer file (.csv/.xlsx) into relevant gathering tables."""
    p = Path(file_path)
    name = p.name.lower()

    total_server = 0
    total_file_nas = 0
    total_block = 0
    errors = []

    if name.endswith(".csv"):
        with p.open("rb") as f:
            rows = _read_csv_rows(f)
        detected_type = _detect_rows_type(rows)
        if detected_type == "server":
            total_server, errors = _import_server_rows(rows, customer_id, gathering_request_id)
        elif detected_type == "file_nas":
            total_file_nas, errors = _import_file_nas_rows(rows, customer_id, gathering_request_id)
        elif detected_type == "block_storage":
            total_block, errors = _import_block_storage_rows(rows, customer_id, gathering_request_id)
        else:
            errors.append("Could not detect CSV type.")
        return total_server, total_file_nas, total_block, errors

    if name.endswith(".xlsx") or name.endswith(".xls"):
        with p.open("rb") as f:
            sheets = _read_xlsx_rows_by_sheet(f)
        server_rows = sheets.get("template", [])
        file_nas_rows = sheets.get("filenas storage (if applicable)", [])
        block_rows = sheets.get("block storage (if applicable)", [])

        if not server_rows and not file_nas_rows and not block_rows:
            for _, rows in sheets.items():
                kind = _detect_rows_type(rows)
                if kind == "server":
                    server_rows.extend(rows)
                elif kind == "file_nas":
                    file_nas_rows.extend(rows)
                elif kind == "block_storage":
                    block_rows.extend(rows)

        s_added, s_err = _import_server_rows(server_rows, customer_id, gathering_request_id)
        f_added, f_err = _import_file_nas_rows(file_nas_rows, customer_id, gathering_request_id)
        b_added, b_err = _import_block_storage_rows(block_rows, customer_id, gathering_request_id)
        total_server += s_added
        total_file_nas += f_added
        total_block += b_added
        errors.extend(s_err + f_err + b_err)

    return total_server, total_file_nas, total_block, errors


def _import_uploaded_file_for_target(upload, target, customer_id, gathering_request_id=None):
    filename = (upload.filename or "").lower()
    rows = []
    normalized_target = (target or "").strip().lower()

    if filename.endswith(".csv"):
        rows = _read_csv_rows(upload.stream)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        sheets = _read_xlsx_rows_by_sheet(upload.stream)
        if normalized_target == "server":
            rows = sheets.get("template", [])
        elif normalized_target == "file-nas":
            rows = sheets.get("filenas storage (if applicable)", [])
        elif normalized_target == "block-storage":
            rows = sheets.get("block storage (if applicable)", [])

        if not rows and sheets:
            rows = next(iter(sheets.values()))
    else:
        return 0, ["Unsupported file format. Use .csv or .xlsx."]

    if normalized_target == "server":
        return _import_server_rows(rows, customer_id, gathering_request_id)
    if normalized_target == "file-nas":
        return _import_file_nas_rows(rows, customer_id, gathering_request_id)
    if normalized_target == "block-storage":
        return _import_block_storage_rows(rows, customer_id, gathering_request_id)
    return 0, ["Invalid import target."]


@crm_bp.route("/opportunities/<int:customer_id>/gathering-data/import", methods=["POST"])
@login_required
def opportunity_gathering_data_import(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    upload = request.files.get("import_file")
    if not upload or not upload.filename:
        flash("Please select a CSV or XLSX file to import.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    filename = upload.filename.lower()
    total_server = 0
    total_file_nas = 0
    total_block = 0
    errors = []

    if filename.endswith(".csv"):
        rows = _read_csv_rows(upload.stream)
        detected_type = _detect_rows_type(rows)
        if detected_type == "server":
            total_server, errors = _import_server_rows(rows, customer.id)
        elif detected_type == "file_nas":
            total_file_nas, errors = _import_file_nas_rows(rows, customer.id)
        elif detected_type == "block_storage":
            total_block, errors = _import_block_storage_rows(rows, customer.id)
        else:
            flash("Could not detect CSV type. Use Server, FileNAS, or Block Storage columns.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        try:
            sheets = _read_xlsx_rows_by_sheet(upload.stream)
        except ImportError:
            flash("openpyxl is not installed. Run: pip install openpyxl", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

        server_rows = sheets.get("template", [])
        file_nas_rows = sheets.get("filenas storage (if applicable)", [])
        block_rows = sheets.get("block storage (if applicable)", [])

        # fallback if sheet names differ: detect by headers
        if not server_rows and not file_nas_rows and not block_rows:
            for _, rows in sheets.items():
                kind = _detect_rows_type(rows)
                if kind == "server":
                    server_rows.extend(rows)
                elif kind == "file_nas":
                    file_nas_rows.extend(rows)
                elif kind == "block_storage":
                    block_rows.extend(rows)

        s_added, s_err = _import_server_rows(server_rows, customer.id)
        f_added, f_err = _import_file_nas_rows(file_nas_rows, customer.id)
        b_added, b_err = _import_block_storage_rows(block_rows, customer.id)
        total_server += s_added
        total_file_nas += f_added
        total_block += b_added
        errors.extend(s_err + f_err + b_err)
    else:
        flash("Unsupported file format. Use .csv or .xlsx.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))

    total_added = total_server + total_file_nas + total_block
    if total_added:
        _log_opportunity_history(
            customer.id,
            action="gathering-data-imported",
            changes_summary=(
                f"Imported Server: {total_server}, FileNAS: {total_file_nas}, "
                f"Block Storage: {total_block} row(s)."
            ),
        )
        db.session.commit()
        flash(
            f"Imported rows - Server: {total_server}, FileNAS: {total_file_nas}, Block Storage: {total_block}.",
            "success",
        )
    else:
        flash("No valid rows were imported.", "error")

    if errors:
        for e in errors[:8]:
            flash(e, "error")

    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="gathering"))


# â”€â”€ Documents: upload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/documents/upload", methods=["POST"])
@login_required
def opportunity_document_upload(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    upload = request.files.get("document_file")
    if not upload or not upload.filename:
        flash("Please select a file to upload.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    description = (request.form.get("doc_description") or "").strip()
    svc = StorageService(current_app._get_current_object())
    result = svc.save_document(upload, upload.filename, customer.id)

    if not result.success:
        flash(f"Upload failed: {result.error}", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    import mimetypes  # noqa: PLC0415
    mime = mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"
    doc = CustomerDocument(
        customer_id=customer.id,
        original_filename=upload.filename,
        stored_filename=result.stored_filename,
        file_path=result.file_path,
        blob_url=result.blob_url,
        storage_backend=result.storage_backend,
        mime_type=mime,
        description=description,
        uploaded_by=_actor_name(),
    )
    db.session.add(doc)
    _log_opportunity_history(
        customer.id,
        action="document-uploaded",
        changes_summary=f"Document '{upload.filename}' uploaded (backend: {result.storage_backend}).",
    )
    db.session.commit()
    flash(f"Document '{upload.filename}' uploaded.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))


# â”€â”€ Documents: download â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/download")
@login_required
def opportunity_document_download(customer_id, doc_id):
    customer = Customer.query.get_or_404(customer_id)
    doc = CustomerDocument.query.get_or_404(doc_id)
    if doc.customer_id != customer.id:
        flash("Document not found.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    if doc.storage_backend in ("azure", "aws") and doc.blob_url:
        return redirect(doc.blob_url)

    if doc.file_path and Path(doc.file_path).exists():
        return send_file(
            doc.file_path,
            as_attachment=True,
            download_name=doc.original_filename,
            mimetype=doc.mime_type or "application/octet-stream",
        )

    flash("File not found on disk.", "error")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))


# â”€â”€ Documents: delete â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@crm_bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def opportunity_document_delete(customer_id, doc_id):
    customer = Customer.query.get_or_404(customer_id)
    doc = CustomerDocument.query.get_or_404(doc_id)
    if doc.customer_id != customer.id:
        flash("Document not found.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    svc = StorageService(current_app._get_current_object())
    svc.delete_document(doc)
    fname = doc.original_filename
    db.session.delete(doc)
    _log_opportunity_history(
        customer.id,
        action="document-deleted",
        changes_summary=f"Document '{fname}' deleted.",
    )
    db.session.commit()
    flash(f"Document '{fname}' deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))


@crm_bp.route("/opportunities/<int:customer_id>/diagrams/add", methods=["POST"])
@login_required
def opportunity_diagram_add(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    diagram_name = (request.form.get("diagram_name") or "").strip()
    macro_key = _normalize_macro_key(request.form.get("macro_key") or "")
    diagram_content = (request.form.get("diagram_content") or "").strip()
    is_active = bool(request.form.get("is_active"))

    if not diagram_name:
        flash("Diagram name is required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))
    if not macro_key:
        flash("Macro key is required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))
    if not diagram_content:
        flash("Diagram content is required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    duplicate_macro = CustomerDiagram.query.filter(
        CustomerDiagram.customer_id == customer.id,
        CustomerDiagram.macro_key == macro_key,
    ).first()
    if duplicate_macro:
        flash("This macro key already exists for this opportunity.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    diagram = CustomerDiagram(
        customer_id=customer.id,
        diagram_name=diagram_name,
        macro_key=macro_key,
        diagram_content=diagram_content,
        is_active=is_active,
        created_by=_actor_name(),
    )
    db.session.add(diagram)
    _log_opportunity_history(
        customer.id,
        action="diagram-added",
        changes_summary=f"Diagram '{diagram_name}' added with macro {{{{{macro_key}}}}}.",
        tag_name="update",
    )
    db.session.commit()
    flash("Diagram added.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))


@crm_bp.route("/opportunities/<int:customer_id>/diagrams/<int:diagram_id>/update", methods=["POST"])
@login_required
def opportunity_diagram_update(customer_id, diagram_id):
    customer = Customer.query.get_or_404(customer_id)
    diagram = CustomerDiagram.query.get_or_404(diagram_id)
    if diagram.customer_id != customer.id:
        flash("Diagram not found.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    diagram_name = (request.form.get("diagram_name") or "").strip()
    macro_key = _normalize_macro_key(request.form.get("macro_key") or "")
    diagram_content = (request.form.get("diagram_content") or "").strip()
    is_active = bool(request.form.get("is_active"))

    if not diagram_name or not macro_key or not diagram_content:
        flash("Diagram name, macro key, and content are required.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    duplicate_macro = CustomerDiagram.query.filter(
        CustomerDiagram.customer_id == customer.id,
        CustomerDiagram.macro_key == macro_key,
        CustomerDiagram.id != diagram.id,
    ).first()
    if duplicate_macro:
        flash("This macro key already exists for another diagram.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    old_macro = diagram.macro_key
    diagram.diagram_name = diagram_name
    diagram.macro_key = macro_key
    diagram.diagram_content = diagram_content
    diagram.is_active = is_active
    diagram.updated_at = datetime.utcnow()
    _log_opportunity_history(
        customer.id,
        action="diagram-updated",
        changes_summary=f"Diagram '{diagram_name}' updated. Macro: {{{{{old_macro}}}}} -> {{{{{macro_key}}}}}.",
        tag_name="update",
    )
    db.session.commit()
    flash("Diagram updated.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))


@crm_bp.route("/opportunities/<int:customer_id>/diagrams/<int:diagram_id>/delete", methods=["POST"])
@login_required
def opportunity_diagram_delete(customer_id, diagram_id):
    customer = Customer.query.get_or_404(customer_id)
    diagram = CustomerDiagram.query.get_or_404(diagram_id)
    if diagram.customer_id != customer.id:
        flash("Diagram not found.", "error")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    name = diagram.diagram_name
    macro_key = diagram.macro_key
    db.session.delete(diagram)
    _log_opportunity_history(
        customer.id,
        action="diagram-deleted",
        changes_summary=f"Diagram '{name}' with macro {{{{{macro_key}}}}} deleted.",
        tag_name="update",
    )
    db.session.commit()
    flash("Diagram deleted.", "success")
    return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

