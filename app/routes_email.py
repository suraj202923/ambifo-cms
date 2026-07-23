from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from app.models import Customer, EmailLog, EmailTemplate, db
from app.services.email_service import EmailService
from app.services.macro_service import render_macros


def register_email_routes(
    bp,
    *,
    build_template_macro_values_for_customer,
    customer_alternate_email_list,
    is_valid_email,
    log_opportunity_history,
    merge_cc_lists,
):
    if getattr(bp, "_email_routes_registered", False):
        return
    setattr(bp, "_email_routes_registered", True)

    @bp.route("/opportunities/<int:customer_id>/send-email", methods=["POST"])
    @login_required
    def opportunity_send_email(customer_id):
        """AJAX endpoint: send email from the popup modal on the opportunity list."""
        email_source = (request.form.get("email_source") or "template").strip().lower()
        template_id = request.form.get("template_id", type=int)
        cc_raw = (request.form.get("cc_emails") or "").strip()
        include_alternate_cc = bool(request.form.get("include_alternate_cc"))
        custom_subject = (request.form.get("custom_subject") or "").strip()
        custom_body = (request.form.get("custom_body") or "").strip()

        cc_list = [e.strip() for e in cc_raw.replace(";", ",").split(",") if e.strip()]
        invalid_cc = [e for e in cc_list if not is_valid_email(e)]
        if invalid_cc:
            return jsonify(success=False, message="Please enter valid CC emails separated by commas."), 400

        customer = Customer.query.get(customer_id)
        template = EmailTemplate.query.get(template_id) if template_id else None

        if not customer:
            return jsonify(success=False, message="Opportunity not found."), 404

        alternate_cc_list = customer_alternate_email_list(customer) if include_alternate_cc else []
        cc_list = merge_cc_lists([customer.email], manual_cc=cc_list, alternate_cc=alternate_cc_list)

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
            macro_values = build_template_macro_values_for_customer(
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
        log_opportunity_history(
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

    @bp.route("/emails/send", methods=["GET", "POST"])
    def send_template_email():
        selected_customer_id = request.values.get("customer_id", type=int)
        customer_q = (request.values.get("customer_q") or "").strip()
        customer_page = request.values.get("customer_page", 1, type=int)
        customers_query = Customer.query
        if customer_q:
            like = f"%{customer_q}%"
            customers_query = customers_query.filter(
                db.or_(
                    Customer.customer_name.ilike(like),
                    Customer.email.ilike(like),
                    Customer.account_name.ilike(like),
                )
            )
        customers_pagination = customers_query.order_by(Customer.customer_name.asc()).paginate(
            page=max(customer_page or 1, 1), per_page=50, error_out=False
        )
        customers = list(customers_pagination.items)
        if selected_customer_id and all(c.id != selected_customer_id for c in customers):
            selected_customer = Customer.query.get(selected_customer_id)
            if selected_customer:
                customers.insert(0, selected_customer)
        templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()

        if request.method == "POST":
            customer_id = request.form.get("customer_id", type=int)
            template_id = request.form.get("template_id", type=int)
            include_alternate_cc = bool(request.form.get("include_alternate_cc"))

            customer = Customer.query.get(customer_id)
            template = EmailTemplate.query.get(template_id)

            if not customer or not template:
                flash("Select a valid customer and template.", "error")
                return render_template(
                    "send_email.html",
                    customers=customers,
                    customers_pagination=customers_pagination,
                    customer_q=customer_q,
                    templates=templates,
                    selected_customer_id=customer_id,
                )

            macro_values = build_template_macro_values_for_customer(
                customer,
                template,
                recipient_email=customer.email,
            )
            rendered_subject = render_macros(template.subject_template, macro_values)
            rendered_body = render_macros(template.body_template, macro_values)

            cc_list = []
            if include_alternate_cc:
                cc_list = merge_cc_lists(
                    [customer.email],
                    manual_cc=[],
                    alternate_cc=customer_alternate_email_list(customer),
                )

            email_service = EmailService(current_app)
            result = email_service.send_html_email(
                customer.email,
                rendered_subject,
                rendered_body,
                cc_emails=cc_list,
            )

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
            log_opportunity_history(
                customer.id,
                action="email-sent",
                changes_summary=(
                    f"Template email processed to {customer.email}. Template: {template.name}. "
                    f"Subject: {rendered_subject}. CC: {', '.join(cc_list) if cc_list else 'None'}. Status: {result.status}."
                ),
                tag_name="email",
            )
            db.session.commit()

            if result.success:
                flash(f"Email processed with status: {result.status}", "success")
            else:
                flash(f"Email failed: {result.error}", "error")

            return redirect(url_for("crm.send_template_email", customer_id=customer.id, customer_q=customer_q, customer_page=customer_page))

        return render_template(
            "send_email.html",
            customers=customers,
            customers_pagination=customers_pagination,
            customer_q=customer_q,
            templates=templates,
            selected_customer_id=selected_customer_id,
        )

    @bp.route("/emails/history/<int:log_id>/resend", methods=["POST"])
    @login_required
    def email_resend(log_id):
        """Resend a previously logged email to the same recipient."""
        log = EmailLog.query.get_or_404(log_id)
        to_addr = log.recipient_email or (log.customer.email if log.customer else None)
        if not to_addr:
            flash("Cannot resend - no recipient address stored.", "error")
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
            log_opportunity_history(
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

    @bp.route("/api/email-queue-status")
    @login_required
    def email_queue_status():
        records = (
            EmailLog.query
            .filter(EmailLog.queue_status.in_(["queued", "processing", "sent", "failed"]))
            .order_by(EmailLog.created_at.desc())
            .limit(100)
            .all()
        )
        result = []
        for r in records:
            result.append({"id": r.id, "queue_status": r.queue_status, "status": r.status})
        queued = sum(1 for r in records if r.queue_status in ("queued", "processing"))
        return jsonify(queued=queued, records=result)

    @bp.route("/emails/retry/<int:log_id>", methods=["POST"])
    @login_required
    def email_retry(log_id):
        """Re-queue a single failed email for retry."""
        log = EmailLog.query.get_or_404(log_id)
        if log.queue_status != "failed":
            flash("Only failed emails can be retried.", "error")
            return redirect(url_for("crm.template_list") + "#email-history")

        log.queue_status = "queued"
        log.status = "queued"
        log.error_message = None
        log.retry_count = (log.retry_count or 0) + 1
        db.session.commit()

        from app.services.email_queue import wake_queue_worker
        wake_queue_worker()

        flash(f"Email to {log.recipient_email} re-queued for retry.", "success")
        return redirect(url_for("crm.template_list") + "#email-history")

    @bp.route("/emails/retry-all-failed", methods=["POST"])
    @login_required
    def email_retry_all_failed():
        """Re-queue all failed emails for retry."""
        failed_logs = EmailLog.query.filter_by(queue_status="failed").all()
        if not failed_logs:
            flash("No failed emails to retry.", "info")
            return redirect(url_for("crm.template_list") + "#email-history")

        count = 0
        for log in failed_logs:
            log.queue_status = "queued"
            log.status = "queued"
            log.error_message = None
            log.retry_count = (log.retry_count or 0) + 1
            count += 1
        db.session.commit()

        from app.services.email_queue import wake_queue_worker
        wake_queue_worker()

        flash(f"{count} failed email(s) re-queued for retry.", "success")
        return redirect(url_for("crm.template_list") + "#email-history")
