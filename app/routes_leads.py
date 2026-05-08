"""Lead management routes — list, add, edit, delete, convert, CSV import."""

from datetime import datetime
import csv
import io

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from werkzeug.utils import secure_filename

from app.models import Customer, Lead, db

_REGISTERED = False


def register_lead_routes(
    bp,
    *,
    is_valid_email,
    log_opportunity_history,
    upsert_lead_from_row,
):
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @bp.route("/leads", methods=["GET", "POST"])
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
                    if upsert_lead_from_row(row, uploaded_from=file_name):
                        imported += 1
                    else:
                        skipped += 1
                db.session.commit()
                flash(f"Leads upload done: {imported} imported/updated, {skipped} skipped.", "success")
                return redirect(url_for("crm.lead_list"))

            if action == "add_lead":
                lead_email = (request.form.get("lead_email") or "").strip().lower()
                if not is_valid_email(lead_email):
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
                if not is_valid_email(lead_email):
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
                if not is_valid_email(lead.email or ""):
                    flash("Lead email is invalid. Please edit and fix email before conversion.", "error")
                    return redirect(url_for("crm.lead_list"))

                existing_customer = Customer.query.filter_by(email=(lead.email or "").strip()).first()
                if existing_customer:
                    lead.converted_customer_id = existing_customer.id
                    lead.converted_at = datetime.utcnow()
                    lead.lead_status = "converted"
                    lead.is_active = False
                    log_opportunity_history(
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

                log_opportunity_history(
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
