"""Partner reference contact and activity management routes."""

from datetime import datetime

from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.models import (
    Customer,
    PartnerReferenceActivity,
    PartnerReferenceContact,
    PartnerReferenceOpportunity,
    db,
)

_REGISTERED = False


def register_reference_routes(
    bp,
    *,
    log_opportunity_history,
):
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @bp.route("/references")
    def reference_list():
        query = (request.args.get("q") or "").strip()
        partner_filter = (request.args.get("partner") or "").strip()
        sort_by = (request.args.get("sort") or "latest_activity_desc").strip()
        page = request.args.get("page", 1, type=int)
        per_page = 10

        activity_stats_subq = (
            db.session.query(
                PartnerReferenceActivity.reference_contact_id.label("ref_id"),
                db.func.count(PartnerReferenceActivity.id).label("activity_count"),
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
            db.session.query(
                PartnerReferenceContact,
                db.func.coalesce(activity_stats_subq.c.activity_count, 0).label("activity_count"),
                activity_stats_subq.c.last_activity_at,
            )
            .outerjoin(activity_stats_subq, PartnerReferenceContact.id == activity_stats_subq.c.ref_id)
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
                activity_stats_subq.c.last_activity_at.desc(),
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
                activity_stats_subq.c.last_activity_at.desc(),
                PartnerReferenceContact.created_at.desc(),
            )

        pagination = contacts_query.paginate(page=page, per_page=per_page, error_out=False)

        rows = []
        for contact, activity_count, last_activity_at in pagination.items:
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

    @bp.route("/references/add", methods=["POST"])
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
            log_opportunity_history(
                assigned_customer.id,
                action="reference-contact-added",
                changes_summary=f"Reference contact added from References page: {contact.contact_name} ({contact.partner_name}).",
                tag_name="important",
            )
            db.session.commit()

        flash("Reference created successfully.", "success")
        return redirect(url_for("crm.reference_list"))

    @bp.route("/references/<int:reference_id>/assign", methods=["POST"])
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
                log_opportunity_history(
                    old_customer.id,
                    action="reference-unassigned",
                    changes_summary=f"Reference contact unassigned: {contact.contact_name} ({contact.partner_name}).",
                    tag_name="assign",
                )

        if contact.customer_id:
            log_opportunity_history(
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

    @bp.route("/opportunities/<int:customer_id>/reference-contacts/add", methods=["POST"])
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

        log_opportunity_history(
            customer.id,
            action="reference-contact-added",
            changes_summary=f"Reference contact added: {contact.contact_name} ({contact.partner_name}).",
            tag_name="important",
        )
        db.session.commit()
        flash("Reference contact added.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/edit", methods=["POST"])
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

        log_opportunity_history(
            customer.id,
            action="reference-contact-updated",
            changes_summary=f"Reference contact updated: {contact.contact_name} ({contact.partner_name}).",
            tag_name="update",
        )
        db.session.commit()
        flash("Reference contact updated.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/delete", methods=["POST"])
    def reference_contact_delete(customer_id, contact_id):
        customer = Customer.query.get_or_404(customer_id)
        contact = PartnerReferenceContact.query.filter_by(id=contact_id, customer_id=customer.id).first_or_404()
        contact_name = contact.contact_name
        partner_name = contact.partner_name
        PartnerReferenceActivity.query.filter_by(reference_contact_id=contact.id).delete(synchronize_session=False)
        PartnerReferenceOpportunity.query.filter_by(reference_contact_id=contact.id).delete(synchronize_session=False)
        db.session.delete(contact)
        db.session.commit()

        log_opportunity_history(
            customer.id,
            action="reference-contact-deleted",
            changes_summary=f"Reference contact deleted: {contact_name} ({partner_name}).",
            tag_name="update",
        )
        db.session.commit()
        flash("Reference contact deleted.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/reference-contacts/<int:contact_id>/activities/add", methods=["POST"])
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

        log_opportunity_history(
            customer.id,
            action="reference-activity-added",
            changes_summary=f"Reference activity ({activity_type}) added for {contact.contact_name}: {summary}",
            tag_name="meeting" if activity_type in {"call", "meeting"} else "update",
        )
        db.session.commit()
        flash("Reference activity added.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/references/assign", methods=["POST"])
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
        log_opportunity_history(
            customer.id,
            action="reference-assigned",
            changes_summary=f"Reference assigned to opportunity: {reference.contact_name} ({reference.partner_name}).",
            tag_name="assign",
        )
        db.session.commit()
        flash("Reference assigned to opportunity.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/references/<int:reference_id>/unassign", methods=["POST"])
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
        log_opportunity_history(
            customer.id,
            action="reference-unassigned",
            changes_summary=f"Reference unassigned from opportunity: {reference.contact_name} ({reference.partner_name}).",
            tag_name="assign",
        )
        db.session.commit()
        flash("Reference unassigned from opportunity.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))

    @bp.route("/opportunities/<int:customer_id>/reference-activities/<int:activity_id>/delete", methods=["POST"])
    def reference_contact_activity_delete(customer_id, activity_id):
        customer = Customer.query.get_or_404(customer_id)
        activity = PartnerReferenceActivity.query.filter_by(id=activity_id, customer_id=customer.id).first_or_404()
        activity_text = activity.summary
        db.session.delete(activity)
        db.session.commit()

        log_opportunity_history(
            customer.id,
            action="reference-activity-deleted",
            changes_summary=f"Reference activity deleted: {activity_text}",
            tag_name="update",
        )
        db.session.commit()
        flash("Reference activity deleted.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="references"))
