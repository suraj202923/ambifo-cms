import csv
import io
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required
from werkzeug.utils import secure_filename

from app.models import (
    Customer,
    CustomerDiagram,
    EmailBulkCsvExecution,
    EmailLog,
    EmailTemplate,
    EmailUnsubscribe,
    Lead,
    OpportunitySegment,
    OpportunityStatus,
    db,
)
from app.services.email_service import EmailService
from app.services.email_queue import wake_queue_worker
from app.services.macro_service import render_macros

try:
    import dns.resolver  # type: ignore
except Exception:  # pragma: no cover
    dns = None


def register_template_routes(
    bp,
    *,
    build_template_macro_values_for_customer,
    email_template_macro_catalog,
    extract_template_macros,
    is_system_template_name,
    is_valid_email,
    lead_macro_values,
    lead_sample_columns,
    log_opportunity_history,
    sanitize_email_template_body,
    system_template_name_set,
    upsert_lead_from_row,
):
    if getattr(bp, "_template_routes_registered", False):
        return
    setattr(bp, "_template_routes_registered", True)

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

    @bp.route("/templates/csv-sample")
    @login_required
    def template_csv_sample():
        template_id = request.args.get("template_id", type=int)
        if not template_id:
            return jsonify({"error": "template_id required"}), 400
        template = EmailTemplate.query.get(template_id)
        if not template:
            return jsonify({"error": "Template not found"}), 404

        macro_keys = extract_template_macros(template)
        columns = ["email"] + macro_keys

        if request.args.get("info"):
            return jsonify({"columns": columns, "template_name": template.name})

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        sample_row = ["recipient@example.com"] + [f"sample_{k}" for k in macro_keys]
        writer.writerow(sample_row)
        csv_bytes = output.getvalue().encode("utf-8")
        buf = io.BytesIO(csv_bytes)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", template.name)
        return send_file(
            buf,
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"sample_{safe_name}.csv",
        )

    @bp.route("/templates/csv-executions/<int:execution_id>/download/<string:kind>")
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

    @bp.route("/leads/csv-sample")
    @login_required
    def leads_csv_sample():
        columns = lead_sample_columns()
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

    @bp.route("/templates", methods=["GET", "POST"])
    def template_list():
        def _render(anchor=None):
            system_template_names = system_template_name_set()
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
            hist_status = (request.args.get("hist_status") or "all").strip()
            history_query = EmailLog.query
            if hist_status in ("queued", "processing", "sent", "failed"):
                history_query = history_query.filter_by(queue_status=hist_status)
            history_pagination = history_query.order_by(EmailLog.created_at.desc()).paginate(
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
                email_macro_catalog=email_template_macro_catalog(),
                statuses=statuses,
                segments=segments,
                history_pagination=history_pagination,
                hist_status=hist_status,
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

            if action == "add_template":
                name = (request.form.get("name") or "").strip()
                subject_template = (request.form.get("subject_template") or "").strip()
                body_template = sanitize_email_template_body(request.form.get("body_template") or "")
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

            elif action == "edit_template":
                tpl_id = request.form.get("template_id", type=int)
                tpl = EmailTemplate.query.get(tpl_id)
                if not tpl:
                    flash("Template not found.", "error")
                else:
                    name = (request.form.get("name") or "").strip()
                    subject_template = (request.form.get("subject_template") or "").strip()
                    body_template = sanitize_email_template_body(request.form.get("body_template") or "")
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

            elif action == "delete_template":
                tpl_id = request.form.get("template_id", type=int)
                tpl = EmailTemplate.query.get(tpl_id)
                if tpl:
                    if is_system_template_name(tpl.name):
                        flash("System templates cannot be deleted. You can edit them.", "error")
                    else:
                        db.session.delete(tpl)
                        db.session.commit()
                        flash("Template deleted.", "success")
                return redirect(url_for("crm.template_list") + "#template-list")

            elif action == "send_custom_email":
                recipient_mode = (request.form.get("recipient_mode") or "").strip()
                email_source = (request.form.get("email_source") or "template").strip()

                if email_source == "template":
                    template_id = request.form.get("template_id", type=int)
                    tpl = EmailTemplate.query.get(template_id) if template_id else None
                    if not tpl:
                        flash("Please select a valid template.", "error")
                        return redirect(url_for("crm.template_list") + "#send-custom")
                    use_template = True
                else:
                    custom_subject = (request.form.get("custom_subject") or "").strip()
                    custom_body = (request.form.get("custom_body") or "").strip()
                    if not custom_subject or not custom_body:
                        flash("Subject and body are required for a custom email.", "error")
                        return redirect(url_for("crm.template_list") + "#send-custom")
                    use_template = False

                def _send_to_customer(customer):
                    if use_template:
                        mv = build_template_macro_values_for_customer(
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
                    db.session.add(EmailLog(
                        customer_id=customer.id,
                        template_id=tpl_id_log,
                        recipient_email=customer.email,
                        email_type="custom",
                        subject=subj,
                        body=body,
                        status="queued",
                        queue_status="queued",
                    ))
                    return True

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

                sent = 0

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
                        _send_to_customer(c)
                        sent += 1
                    db.session.commit()
                    wake_queue_worker()
                    flash(f"Status '{status_name}': {sent} emails queued for sending.", "success")

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
                        _send_to_customer(c)
                        sent += 1
                    db.session.commit()
                    wake_queue_worker()
                    flash(f"Segment '{segment_name}': {sent} emails queued for sending.", "success")

                elif recipient_mode == "select":
                    customer_ids = request.form.getlist("selected_customers")
                    if not customer_ids:
                        flash("Please select at least one customer.", "error")
                        return redirect(url_for("crm.template_list") + "#send-custom")
                    for cid in customer_ids:
                        c = Customer.query.get(int(cid))
                        if c and c.email:
                            _send_to_customer(c)
                            sent += 1
                    db.session.commit()
                    wake_queue_worker()
                    flash(f"Selected customers: {sent} emails queued for sending.", "success")

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

            elif action == "send_bulk_email":
                template_id = request.form.get("template_id", type=int)
                template = EmailTemplate.query.get(template_id)
                if not template:
                    flash("Select a valid template.", "error")
                    return redirect(url_for("crm.template_list") + "#send-bulk")
                all_customers = Customer.query.filter(Customer.email.isnot(None), Customer.email != "").all()
                queued = 0
                for customer in all_customers:
                    macro_values = build_template_macro_values_for_customer(
                        customer,
                        template,
                        recipient_email=customer.email,
                    )
                    rendered_subject = render_macros(template.subject_template, macro_values)
                    rendered_body = render_macros(template.body_template, macro_values)
                    db.session.add(EmailLog(
                        customer_id=customer.id,
                        template_id=template.id,
                        recipient_email=customer.email,
                        email_type="bulk",
                        subject=rendered_subject,
                        body=rendered_body,
                        status="queued",
                        queue_status="queued",
                    ))
                    queued += 1
                db.session.commit()
                wake_queue_worker()
                flash(f"Bulk email queued: {queued} emails will be sent shortly.", "success")
                return redirect(url_for("crm.template_list") + "#send-bulk")

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

                try:
                    original_filename = secure_filename(csv_file.filename or "bulk.csv")
                    content = csv_file.read().decode("utf-8-sig")
                    reader = csv.DictReader(io.StringIO(content))
                    csv_rows = list(reader)
                    csv_headers = [h.strip() for h in (reader.fieldnames or [])]
                except Exception as e:
                    flash(f"Failed to read CSV: {e}", "error")
                    return redirect(url_for("crm.template_list") + "#send-bulk-csv")

                lead_imported = 0
                for row in csv_rows:
                    if upsert_lead_from_row(row, uploaded_from=original_filename):
                        lead_imported += 1
                db.session.commit()

                macro_keys = extract_template_macros(template)
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

                queued = 0
                success_lines = [f"Bulk CSV Execution: {execution_token}", f"Template: {template.name}", ""]
                for idx, recipient, row in mx_valid_rows:
                    mv = {k: (row.get(k) or "").strip() for k in csv_headers}
                    mv["today"] = datetime.utcnow().date().isoformat()
                    rendered_subject = render_macros(template.subject_template, mv)
                    rendered_body = render_macros(template.body_template, mv)
                    db.session.add(EmailLog(
                        customer_id=None,
                        template_id=template.id,
                        recipient_email=recipient,
                        email_type="csv-bulk",
                        subject=rendered_subject,
                        body=rendered_body,
                        status="queued",
                        queue_status="queued",
                    ))
                    queued += 1
                    success_lines.append(f"Row {idx}: QUEUED -> {recipient}")

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
                    sent_rows=queued,
                    failed_rows=0,
                )
                db.session.add(execution)
                db.session.commit()
                wake_queue_worker()
                msg = (
                    f"CSV bulk emails queued. Total rows: {len(csv_rows)}, queued: {queued}, "
                    f"unsubscribed removed: {unsubscribed_rows}, excluded (invalid/no-mx/unsubscribed): {max(0, len(csv_rows) - len(mx_valid_rows))}, "
                    f"leads imported/updated: {lead_imported}. Emails will be sent shortly."
                )
                flash(msg, "success")
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
                    if upsert_lead_from_row(row, uploaded_from=file_name):
                        imported += 1
                    else:
                        skipped += 1
                db.session.commit()
                flash(f"Leads upload done: {imported} imported/updated, {skipped} skipped (invalid/missing email).", "success")
                return redirect(url_for("crm.template_list") + "#leads-section")

            elif action == "add_lead":
                lead_email = (request.form.get("lead_email") or "").strip().lower()
                if not is_valid_email(lead_email):
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
                if not is_valid_email(lead_email):
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

                queued = 0
                for lead in leads:
                    macro_values = lead_macro_values(lead)
                    rendered_subject = render_macros(template.subject_template, macro_values)
                    rendered_body = render_macros(template.body_template, macro_values)
                    db.session.add(EmailLog(
                        customer_id=None,
                        template_id=template.id,
                        recipient_email=lead.email,
                        email_type="lead-bulk",
                        subject=rendered_subject,
                        body=rendered_body,
                        status="queued",
                        queue_status="queued",
                    ))
                    lead.last_emailed_at = datetime.utcnow()
                    lead.last_email_status = "queued"
                    queued += 1
                db.session.commit()
                wake_queue_worker()
                flash(f"Lead promotional bulk email queued: {queued} emails will be sent shortly.", "success")
                return redirect(url_for("crm.template_list") + "#send-lead-bulk")

            return redirect(url_for("crm.template_list"))

        return _render()
