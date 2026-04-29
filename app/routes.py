from datetime import datetime, timedelta
import csv
import html
import io
import os
from pathlib import Path
import secrets
import threading

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
    CustomerDocument,
    EmailLog,
    EmailTemplate,
    GatheringBlockStorageDetail,
    GatheringFileNasDetail,
    GatheringRequest,
    GatheringServerDetail,
    MeetingInvite,
    OpportunityHistory,
    OpportunityUpdateTag,
    OpportunitySegment,
    OpportunityStatus,
    SystemSetting,
    User,
    db,
)
from app.services.email_service import EmailService
from app.services.macro_service import build_macro_values, render_macros
from app.services.storage_service import StorageService
from app.services.teams_service import TeamsService
from app import _request_process_restart


crm_bp = Blueprint("crm", __name__)

DEFAULT_STATUSES = [
    ("In Pipeline", "#f4a259"),
    ("Qualified", "#2a9d8f"),
    ("Proposal", "#4d96ff"),
    ("Won", "#1a936f"),
    ("Lost", "#d1495b"),
]

DEFAULT_SEGMENTS = ["SUP", "SMB", "Enterprise", "Startup"]


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


@crm_bp.before_app_request
def require_login_for_crm_routes():
    endpoint = request.endpoint or ""
    g.user = current_user

    allowed_endpoints = {
        "crm.login",
        "crm.gathering_form",
        "crm.gathering_form_sample_xlsx",
        "crm.gathering_form_sample_server_csv",
        "crm.gathering_form_sample_file_nas_csv",
        "crm.gathering_form_sample_block_storage_csv",
        "static",
    }

    if endpoint in allowed_endpoints:
        return

    if endpoint.startswith("crm.") and not current_user.is_authenticated:
        return redirect(url_for("crm.login", next=request.path))


@crm_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("crm.opportunity_list"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active_user:
            login_user(user)
            next_url = request.args.get("next") or url_for("crm.opportunity_list")
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


@crm_bp.route("/")
def index():
    return redirect(url_for("crm.opportunity_list"))


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
    base = current_app.config["APP_BASE_URL"].rstrip("/")
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

    form_link = f"{current_app.config['APP_BASE_URL'].rstrip('/')}/gathering/form/{token}"
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
    body_template = """
    <p>Hello {{customer_name}},</p>
    <p>Please share your required details using the secure form link below:</p>
    <p><a href='{{gathering_form_link}}'>Open Gathering Form</a></p>
    <p><strong>Access Key:</strong> {{gathering_access_key}}</p>
    <p><strong>Link Expiry:</strong> {{gathering_expires_at}}</p>
    <p>{{note}}</p>
    <p>Regards,<br>Ambifo Team</p>
    """
    rendered_body = render_macros(body_template, macro_values)
    email_service = EmailService(current_app)
    result = email_service.send_html_email(
        customer.email, "Ambifo - Gathering Sheet & Information Request", rendered_body
    )
    db.session.add(
        EmailLog(
            customer_id=customer.id,
            template_id=None,
            recipient_email=customer.email,
            email_type="gathering",
            subject="Ambifo - Gathering Sheet & Information Request",
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

    body = (
        f"<p>Hello {html.escape(customer.customer_name or '')},</p>"
        "<p>Please find the meeting details below:</p>"
        f"<p><strong>Subject:</strong> {html.escape(subject)}</p>"
        f"<p><strong>When:</strong> {meeting_when_html}</p>"
        f"<p><strong>Agenda:</strong><br>{agenda_html}</p>"
        f"<p><strong>Required Data:</strong><br>{required_data_html}</p>"
        f"<p><strong>Join Microsoft Teams:</strong><br><a href=\"{meeting_link_html}\">{meeting_link_html}</a></p>"
        "<p>Regards,<br>Ambifo Team</p>"
    )

    email_service = EmailService(current_app)
    sent_count = 0
    failed_count = 0

    for recipient_email in recipient_emails:
        result = email_service.send_html_email(recipient_email, subject, body)
        db.session.add(
            EmailLog(
                customer_id=customer.id,
                template_id=None,
                recipient_email=recipient_email,
                email_type="meeting-link",
                subject=subject,
                body=body,
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


@crm_bp.route("/customers")
@crm_bp.route("/opportunities")
def opportunity_list():
    _ensure_default_statuses()
    _ensure_default_segments()
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
        admin_users=admin_users,
        assign_colors=_user_color_map(admin_users),
        status_colors=_status_color_map(statuses),
        email_templates=email_templates,
        total_count=total_count,
    )


@crm_bp.route("/customers")
def customer_list():
    return redirect(url_for("crm.opportunity_list", **request.args))


@crm_bp.route("/customers/new", methods=["GET", "POST"])
@crm_bp.route("/opportunities/new", methods=["GET", "POST"])
def opportunity_new():
    _ensure_default_statuses()
    _ensure_default_segments()
    status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
    segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
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
                admin_users=admin_users,
                email_templates=email_templates,
            )

        selected_status = (request.form.get("deal_status") or "").strip()
        selected_segment = (request.form.get("segment") or "").strip()
        assigned_user_id = request.form.get("assign_to_user_id", type=int)
        send_welcome_email = bool(request.form.get("send_welcome_email"))
        welcome_template_id = request.form.get("welcome_template_id", type=int)
        assigned_user = None

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
                macro_values = build_macro_values(customer)
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
    customer = Customer.query.get_or_404(customer_id)
    status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
    segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
    admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
    email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
    history_entries = OpportunityHistory.query.filter_by(customer_id=customer.id).order_by(OpportunityHistory.created_at.desc()).all()
    history_tag_colors = _tag_color_map()
    update_tags = OpportunityUpdateTag.query.filter_by(is_active=True).order_by(OpportunityUpdateTag.name.asc()).all()
    gathering_entries = GatheringServerDetail.query.filter_by(customer_id=customer.id).order_by(GatheringServerDetail.created_at.desc()).all()
    file_nas_entries = GatheringFileNasDetail.query.filter_by(customer_id=customer.id).order_by(GatheringFileNasDetail.created_at.desc()).all()
    block_storage_entries = GatheringBlockStorageDetail.query.filter_by(customer_id=customer.id).order_by(GatheringBlockStorageDetail.created_at.desc()).all()
    documents = CustomerDocument.query.filter_by(customer_id=customer.id).order_by(CustomerDocument.created_at.desc()).all()
    gathering_requests = GatheringRequest.query.filter_by(customer_id=customer.id).order_by(GatheringRequest.created_at.desc()).all()

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
                active_tab='info',
                base_url=current_app.config.get('APP_BASE_URL', 'http://127.0.0.1:5000'),
            )

        new_values = {
            "account_name": (request.form.get("account_name") or "").strip(),
            "customer_name": customer_name,
            "email": email,
            "phone": (request.form.get("phone") or "").strip(),
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
            "city": "City",
            "aws_id": "AWS ID",
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
        teams_auto_available=TeamsService(current_app).is_configured(),
        active_tab=request.args.get("tab", "info"),
        base_url=current_app.config.get("APP_BASE_URL", "http://127.0.0.1:5000"),
    )


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


@crm_bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
@crm_bp.route("/opportunities/<int:customer_id>/delete", methods=["POST"])
def opportunity_delete(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    flash("Opportunity deleted.", "success")
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


@crm_bp.route("/templates", methods=["GET", "POST"])
def template_list():
    def _render(anchor=None):
        tpl_page = request.args.get("tpl_page", 1, type=int)
        tpl_pagination = EmailTemplate.query.order_by(EmailTemplate.created_at.desc()).paginate(
            page=tpl_page, per_page=5, error_out=False
        )
        all_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
        customers = Customer.query.order_by(Customer.customer_name.asc()).all()
        statuses = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
        segments = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
        hist_page = request.args.get("hist_page", 1, type=int)
        history_pagination = EmailLog.query.order_by(EmailLog.created_at.desc()).paginate(
            page=hist_page, per_page=10, error_out=False
        )
        return render_template(
            "templates_list.html",
            tpl_pagination=tpl_pagination,
            all_templates=all_templates,
            customers=customers,
            statuses=statuses,
            segments=segments,
            history_pagination=history_pagination,
            scroll_to=anchor,
        )

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        # â”€â”€ Add template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if action == "add_template":
            name = (request.form.get("name") or "").strip()
            subject_template = (request.form.get("subject_template") or "").strip()
            body_template = (request.form.get("body_template") or "").strip()
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

        # â”€â”€ Edit template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif action == "edit_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if not tpl:
                flash("Template not found.", "error")
            else:
                name = (request.form.get("name") or "").strip()
                subject_template = (request.form.get("subject_template") or "").strip()
                body_template = (request.form.get("body_template") or "").strip()
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

        # â”€â”€ Delete template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif action == "delete_template":
            tpl_id = request.form.get("template_id", type=int)
            tpl = EmailTemplate.query.get(tpl_id)
            if tpl:
                db.session.delete(tpl)
                db.session.commit()
                flash("Template deleted.", "success")
            return redirect(url_for("crm.template_list") + "#template-list")

        # â”€â”€ Send custom email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        elif action == "send_custom_email":
            recipient_mode = (request.form.get("recipient_mode") or "").strip()
            email_source   = (request.form.get("email_source") or "template").strip()

            # â”€â”€ Resolve subject / body â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

            # â”€â”€ Resolve recipients â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            def _send_to_customer(customer):
                if use_template:
                    mv = build_macro_values(customer)
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

        # â”€â”€ Send bulk email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                macro_values = build_macro_values(customer)
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
                if result.success or result.status == "dev-mode":
                    sent += 1
                else:
                    failed += 1
            db.session.commit()
            flash(f"Bulk email done: {sent} sent, {failed} failed.", "success" if not failed else "error")
            return redirect(url_for("crm.template_list") + "#send-bulk")

        return redirect(url_for("crm.template_list"))

    return _render()


@crm_bp.route("/configuration", methods=["GET", "POST"])
def configuration():
    _ensure_default_statuses()
    _ensure_default_segments()

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
                subject = "SMTP Test Email - Ambifo CRM"
                body = (
                    "<p>This is a test email from Ambifo CRM SMTP Configuration.</p>"
                    "<p>If you received this, SMTP is working correctly.</p>"
                )
                result = email_service.send_html_email(test_to, subject, body)
                if result.success or result.status == "dev-mode":
                    flash(f"Test email sent to {test_to} (status: {result.status}).", "success")
                else:
                    flash(f"SMTP test failed: {result.error}", "error")

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
    statuses = OpportunityStatus.query.order_by(OpportunityStatus.created_at.asc()).all()
    segments = OpportunitySegment.query.order_by(OpportunitySegment.created_at.asc()).all()
    update_tags = OpportunityUpdateTag.query.order_by(OpportunityUpdateTag.created_at.asc()).all()
    admin_users = User.query.order_by(User.created_at.asc()).all()
    return render_template(
        "configuration.html",
        smtp=smtp_settings,
        teams=teams_settings,
        statuses=statuses,
        segments=segments,
        update_tags=update_tags,
        admin_users=admin_users,
    )


@crm_bp.route("/templates/new", methods=["GET", "POST"])
def template_new():
    # Legacy route â€” redirect to unified templates page
    return redirect(url_for("crm.template_list") + "#add-template")


@crm_bp.route("/opportunities/<int:customer_id>/send-email", methods=["POST"])
@login_required
def opportunity_send_email(customer_id):
    """AJAX endpoint: send email from the popup modal on the opportunity list."""
    from flask import jsonify
    template_id = request.form.get("template_id", type=int)

    customer = Customer.query.get(customer_id)
    template = EmailTemplate.query.get(template_id) if template_id else None

    if not customer or not template:
        return jsonify(success=False, message="Please select a valid template."), 400

    macro_values = build_macro_values(customer)
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

        macro_values = build_macro_values(customer)
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

        form_link = f"{current_app.config['APP_BASE_URL'].rstrip('/')}/gathering/form/{token}"
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

        subject = "Ambifo - Gathering Sheet & Information Request"
        body_template = """
        <p>Hello {{customer_name}},</p>
        <p>Please share your required details using the secure form link below:</p>
        <p><a href='{{gathering_form_link}}'>Open Gathering Form</a></p>
        <p><strong>Access Key:</strong> {{gathering_access_key}}</p>
        <p><strong>Link Expiry:</strong> {{gathering_expires_at}}</p>
        <p>If needed, you can also upload your gathering sheet directly in this form.</p>
        <p>{{note}}</p>
        <p>Regards,<br>Ambifo Team</p>
        """
        rendered_body = render_macros(body_template, macro_values)

        email_service = EmailService(current_app)
        result = email_service.send_html_email(
            customer.email,
            subject,
            rendered_body,
            cc_emails=cc_list,
            bcc_emails=bcc_list,
        )

        email_log = EmailLog(
            customer_id=customer.id,
            template_id=None,
            recipient_email=customer.email,
            email_type="gathering",
            subject=subject,
            body=rendered_body,
            status=result.status,
            error_message=result.error,
        )
        db.session.add(email_log)
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
    form_link = f"{current_app.config['APP_BASE_URL'].rstrip('/')}/gathering/form/{new_token}"
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

