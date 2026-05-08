import html
import secrets
from datetime import datetime, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from werkzeug.security import generate_password_hash

from app.models import (
    Customer,
    EmailLog,
    GatheringRequest,
    MeetingAvailabilityRequest,
    MeetingInvite,
    db,
)
from app.services.email_service import EmailService
from app.services.macro_service import build_macro_values
from app.services.teams_service import TeamsService


def register_engagement_routes(
    bp,
    *,
    actor_name,
    customer_alternate_email_list,
    format_option_dt,
    generate_access_key,
    get_effective_app_base_url,
    get_meeting_settings,
    is_valid_email,
    is_gathering_request_expired,
    log_opportunity_history,
    merge_cc_lists,
    render_system_email_template,
):
    if getattr(bp, "_engagement_routes_registered", False):
        return
    setattr(bp, "_engagement_routes_registered", True)

    @bp.route("/opportunities/<int:customer_id>/gathering-status")
    @login_required
    def opportunity_gathering_status(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        links = (
            GatheringRequest.query
            .filter_by(customer_id=customer_id)
            .order_by(GatheringRequest.created_at.desc())
            .all()
        )
        base = get_effective_app_base_url()
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

    @bp.route("/opportunities/<int:customer_id>/send-gathering-link", methods=["POST"])
    @login_required
    def opportunity_send_gathering_link(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json(silent=True) or {}
        expiry_days = int(data.get("expiry_days") or 7)
        note = (data.get("note") or "").strip()

        if expiry_days < 1 or expiry_days > 90:
            return jsonify({"success": False, "message": "Expiry must be between 1 and 90 days."})

        token = secrets.token_urlsafe(24)
        access_key = generate_access_key()
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

        form_link = f"{get_effective_app_base_url()}/gathering/form/{token}"
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
        tpl, rendered_subject, rendered_body = render_system_email_template("gathering_request", macro_values)
        email_service = EmailService(current_app)
        result = email_service.send_html_email(customer.email, rendered_subject, rendered_body)
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
        log_opportunity_history(
            customer.id,
            action="gathering-link-sent",
            changes_summary=(
                f"Gathering link sent to {customer.email} by {actor_name()} "
                f"(from opportunity list). Expiry: {expires_at_text}. Token: …{token[-6:]}."
            ),
            remark=note or None,
        )
        db.session.commit()

        if result.success:
            return jsonify(
                {
                    "success": True,
                    "message": f"Gathering link sent to {customer.email}.",
                    "access_key": access_key,
                    "expires_at": expires_at_text,
                    "form_url": form_link,
                }
            )
        return jsonify(
            {
                "success": False,
                "message": f"Email delivery failed: {result.error}. Link created — access key: {access_key}",
                "access_key": access_key,
                "expires_at": expires_at_text,
                "form_url": form_link,
            }
        )

    @bp.route("/opportunities/<int:customer_id>/meeting-link/send", methods=["POST"])
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
        include_alternate_cc = bool(request.form.get("include_alternate_cc"))
        teams_service = TeamsService(current_app)
        teams_is_configured = teams_service.is_configured()

        if not recipient_emails or not subject or not agenda or not required_data:
            flash("At least one recipient email, subject, agenda, and required data are mandatory.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

        invalid_emails = [e for e in recipient_emails if "@" not in e]
        if invalid_emails:
            flash("Please enter valid recipient emails separated by comma.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="meeting"))

        alternate_cc_list = customer_alternate_email_list(customer) if include_alternate_cc else []
        cc_list = merge_cc_lists(recipient_emails, manual_cc=[], alternate_cc=alternate_cc_list)

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
        tpl, rendered_subject, rendered_body = render_system_email_template("meeting_link", template_macro_values)

        email_service = EmailService(current_app)
        sent_count = 0
        failed_count = 0

        for recipient_email in recipient_emails:
            result = email_service.send_html_email(
                recipient_email,
                rendered_subject,
                rendered_body,
                cc_emails=cc_list,
            )
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
                        created_by=actor_name(),
                    )
                )
            else:
                failed_count += 1

        history_summary = (
            f"Teams meeting invite processed for {len(recipient_emails)} recipient(s).\n"
            f"Sent: {sent_count}, Failed: {failed_count}\n"
            f"Recipients: {', '.join(recipient_emails)}\n"
            f"CC: {', '.join(cc_list) if cc_list else 'None'}\n"
            f"Link Source: {link_source}\n"
            f"Subject: {subject}\n"
            f"When: {meeting_when}\n"
            f"Meeting Link: {meeting_link}"
        )
        log_opportunity_history(
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

    @bp.route("/opportunities/<int:customer_id>/meeting-availability/send", methods=["POST"])
    @login_required
    def opportunity_send_meeting_availability(customer_id):
        customer = Customer.query.get_or_404(customer_id)

        recipient_email = (request.form.get("recipient_email") or customer.email or "").strip()
        subject = (request.form.get("subject") or "Select Your Preferred Meeting Time").strip()
        option_1_raw = (request.form.get("option_1") or "").strip()
        option_2_raw = (request.form.get("option_2") or "").strip()
        option_3_raw = (request.form.get("option_3") or "").strip()
        remark = (request.form.get("remark") or "").strip()
        include_alternate_cc = bool(request.form.get("include_alternate_cc"))

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
        meeting_settings = get_meeting_settings()
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
            created_by=actor_name(),
        )
        db.session.add(req)
        db.session.flush()

        base = get_effective_app_base_url()
        option_1_link = f"{base}/meeting/availability/{token}/1"
        option_2_link = f"{base}/meeting/availability/{token}/2"
        option_3_link = f"{base}/meeting/availability/{token}/3"
        form_link = f"{base}/meeting/availability/form/{token}"

        expires_at_text = html.escape(expires_at.strftime("%d %b %Y, %I:%M %p UTC"))
        template_macro_values = build_macro_values(
            customer,
            {
                "meeting_subject": html.escape(subject),
                "option_1_link": html.escape(option_1_link),
                "option_2_link": html.escape(option_2_link),
                "option_3_link": html.escape(option_3_link),
                "option_1_text": html.escape(format_option_dt(option_1_at)),
                "option_2_text": html.escape(format_option_dt(option_2_at)),
                "option_3_text": html.escape(format_option_dt(option_3_at)),
                "meeting_availability_form_link": html.escape(form_link),
                "meeting_availability_expires_at": expires_at_text,
            },
        )
        tpl, rendered_subject, rendered_body = render_system_email_template("meeting_availability", template_macro_values)

        alternate_cc_list = customer_alternate_email_list(customer) if include_alternate_cc else []
        cc_list = merge_cc_lists([recipient_email], manual_cc=[], alternate_cc=alternate_cc_list)
        result = EmailService(current_app).send_html_email(
            recipient_email,
            rendered_subject,
            rendered_body,
            cc_emails=cc_list,
        )
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
            f"CC: {', '.join(cc_list) if cc_list else 'None'}\n"
            f"Option 1: {format_option_dt(option_1_at)}\n"
            f"Option 2: {format_option_dt(option_2_at)}\n"
            f"Option 3: {format_option_dt(option_3_at)}\n"
            f"Token: ...{token[-6:]}"
        )
        log_opportunity_history(
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

    @bp.route("/meeting/availability/<token>/<int:option_no>", methods=["GET"])
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

        selected_text = format_option_dt(selected_dt)
        comment_line = f"Customer selected meeting option {option_no}: {selected_text}"
        existing_comment = (customer.comment or "").strip()
        customer.comment = f"{existing_comment}\n{comment_line}".strip() if existing_comment else comment_line

        log_opportunity_history(
            customer.id,
            action="meeting-availability-selected",
            changes_summary=f"Customer selected Option {option_no} from one-click email: {selected_text}",
            remark=f"Response captured from token ...{token[-6:]}",
            tag_name="meeting",
        )

        db.session.commit()
        return "Thank you. Your preferred meeting time has been submitted.", 200

    @bp.route("/meeting/availability/form/<token>", methods=["GET", "POST"])
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
                return (
                    render_template(
                        "meeting_availability_form.html",
                        request_record=req,
                        customer=customer,
                        form_error="Please enter all 3 valid date/time values.",
                        form_values=form_values,
                    ),
                    400,
                )

            unique_slots = {c1.isoformat(), c2.isoformat(), c3.isoformat()}
            if len(unique_slots) < 3:
                return (
                    render_template(
                        "meeting_availability_form.html",
                        request_record=req,
                        customer=customer,
                        form_error="Please provide 3 different date/time options.",
                        form_values=form_values,
                    ),
                    400,
                )

            if extra_recipients:
                recipient_list = [item.strip() for item in extra_recipients.replace(";", ",").split(",") if item.strip()]
                invalid_emails = [email for email in recipient_list if not is_valid_email(email)]
                if invalid_emails:
                    return (
                        render_template(
                            "meeting_availability_form.html",
                            request_record=req,
                            customer=customer,
                            form_error="Please enter valid extra recipient emails separated by comma.",
                            form_values=form_values,
                        ),
                        400,
                    )
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
                f"Option 1: {format_option_dt(c1)}",
                f"Option 2: {format_option_dt(c2)}",
                f"Option 3: {format_option_dt(c3)}",
            ]
            if extra_recipients:
                summary_lines.append(f"Extra recipients: {extra_recipients}")
            if customer_note:
                summary_lines.append(f"Customer note: {customer_note}")

            existing_comment = (customer.comment or "").strip()
            append_comment = "Customer shared 3 preferred meeting slots."
            customer.comment = f"{existing_comment}\n{append_comment}".strip() if existing_comment else append_comment

            log_opportunity_history(
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
