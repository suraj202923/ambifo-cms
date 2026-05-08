"""Opportunity / Customer core CRUD routes and inline history management."""

from datetime import datetime

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.models import (
    Customer,
    CustomerDiagram,
    CustomerDocument,
    CustomerSOW,
    EmailLog,
    EmailTemplate,
    GatheringBlockStorageDetail,
    GatheringFileNasDetail,
    GatheringRequest,
    GatheringServerDetail,
    MeetingAvailabilityRequest,
    MeetingInvite,
    OpportunityCloudOperator,
    OpportunityFinancial,
    OpportunityHistory,
    OpportunitySegment,
    OpportunityStatus,
    OpportunityUpdateTag,
    PartnerReferenceActivity,
    PartnerReferenceContact,
    PartnerReferenceOpportunity,
    User,
    db,
)
from app.services.email_service import EmailService
from app.services.macro_service import render_macros
from app.services.teams_service import TeamsService

_REGISTERED = False


def register_opportunity_core_routes(
    bp,
    *,
    actor_name,
    apply_financial_payload,
    build_financial_payload,
    build_template_macro_values_for_customer,
    derive_tag_from_action,
    ensure_default_cloud_operators,
    ensure_default_segments,
    ensure_default_statuses,
    financial_change_lines,
    is_valid_email,
    log_opportunity_history,
    parse_email_list,
    status_color_map,
    tag_color_map,
    user_color_map,
):
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @bp.route("/customers")
    @bp.route("/opportunities")
    def opportunity_list():
        ensure_default_statuses()
        ensure_default_segments()
        ensure_default_cloud_operators()
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
            page=page, per_page=per_page, error_out=False
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
            assign_colors=user_color_map(admin_users),
            status_colors=status_color_map(statuses),
            email_templates=email_templates,
            total_count=total_count,
        )

    @bp.route("/customers")
    def customer_list():
        return redirect(url_for("crm.opportunity_list", **request.args))

    @bp.route("/customers/new", methods=["GET", "POST"])
    @bp.route("/opportunities/new", methods=["GET", "POST"])
    def opportunity_new():
        ensure_default_statuses()
        ensure_default_segments()
        ensure_default_cloud_operators()
        status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
        segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
        cloud_options = OpportunityCloudOperator.query.filter_by(is_active=True).order_by(OpportunityCloudOperator.name.asc()).all()
        admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
        email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()

        if request.method == "POST":
            pending_form_data = request.form.to_dict(flat=True)
            email = (request.form.get("email") or "").strip()
            alternate_emails_raw = (request.form.get("alternate_emails") or "").strip()
            alternate_emails_list, invalid_alternate_emails, duplicate_alternate_emails = parse_email_list(alternate_emails_raw)
            customer_name = (request.form.get("customer_name") or "").strip()

            def _re_render(msg, category="error"):
                flash(msg, category)
                return render_template(
                    "customer_form.html",
                    customer=None,
                    is_edit=False,
                    status_options=status_options,
                    segment_options=segment_options,
                    cloud_options=cloud_options,
                    admin_users=admin_users,
                    email_templates=email_templates,
                    pending_form_data=pending_form_data,
                )

            if not email or not customer_name:
                return _re_render("Opportunity name and email are required.")
            if invalid_alternate_emails:
                return _re_render("Please enter valid alternate emails separated by comma.")
            if duplicate_alternate_emails:
                return _re_render("Duplicate alternate emails are not allowed.")
            if email and email.strip().lower() in set(alternate_emails_list):
                return _re_render("Alternate emails cannot be same as main email.")
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
            try:
                financial_payload = build_financial_payload(request.form, selected_segment)
            except ValueError as exc:
                return _re_render(str(exc))

            assigned_user_id = request.form.get("assign_to_user_id", type=int)
            send_welcome_email = bool(request.form.get("send_welcome_email"))
            welcome_template_id = request.form.get("welcome_template_id", type=int)
            assigned_user = None

            if selected_cloud and not OpportunityCloudOperator.query.filter_by(name=selected_cloud, is_active=True).first():
                return _re_render("Please select a valid cloud operator.")
            if assigned_user_id:
                assigned_user = User.query.filter_by(id=assigned_user_id, is_active_user=True).first()
                if not assigned_user:
                    return _re_render("Please select a valid admin user.")
            if send_welcome_email and not welcome_template_id:
                return _re_render("Please select a welcome email template.")

            customer = Customer(
                account_name=(request.form.get("account_name") or "").strip(),
                customer_name=customer_name,
                email=email,
                alternate_emails=", ".join(alternate_emails_list) if alternate_emails_list else None,
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

            apply_financial_payload(customer.id, financial_payload)
            db.session.commit()

            log_opportunity_history(
                customer.id,
                action="created",
                changes_summary="Opportunity created.",
                remark=(request.form.get("change_remark") or "").strip() or None,
            )
            db.session.commit()

            if send_welcome_email:
                template = EmailTemplate.query.get(welcome_template_id)
                if template:
                    from flask import current_app
                    macro_values = build_template_macro_values_for_customer(customer, template, recipient_email=customer.email)
                    rendered_subject = render_macros(template.subject_template, macro_values)
                    rendered_body = render_macros(template.body_template, macro_values)

                    email_service = EmailService(current_app)
                    result = email_service.send_html_email(customer.email, rendered_subject, rendered_body)

                    db.session.add(EmailLog(
                        customer_id=customer.id, template_id=template.id,
                        recipient_email=customer.email, email_type="welcome",
                        subject=rendered_subject, body=rendered_body,
                        status=result.status, error_message=result.error,
                    ))
                    log_opportunity_history(
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
                            customer_id=customer.id, template_id=template.id,
                            recipient_email=assigned_user.email, email_type="welcome-assigned",
                            subject=rendered_subject, body=rendered_body,
                            status=assign_result.status, error_message=assign_result.error,
                        ))
                        log_opportunity_history(
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
            pending_form_data=None,
        )

    @bp.route("/customers/new", methods=["GET", "POST"])
    def customer_new():
        return opportunity_new()

    @bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
    @bp.route("/opportunities/<int:customer_id>/edit", methods=["GET", "POST"])
    def opportunity_edit(customer_id):
        ensure_default_statuses()
        ensure_default_segments()
        ensure_default_cloud_operators()
        from flask import current_app
        customer = Customer.query.get_or_404(customer_id)
        status_options = OpportunityStatus.query.filter_by(is_active=True).order_by(OpportunityStatus.name.asc()).all()
        segment_options = OpportunitySegment.query.filter_by(is_active=True).order_by(OpportunitySegment.name.asc()).all()
        cloud_options = OpportunityCloudOperator.query.filter_by(is_active=True).order_by(OpportunityCloudOperator.name.asc()).all()
        admin_users = User.query.filter_by(is_active_user=True).order_by(User.username.asc()).all()
        email_templates = EmailTemplate.query.order_by(EmailTemplate.name.asc()).all()
        history_entries = OpportunityHistory.query.filter_by(customer_id=customer.id).order_by(OpportunityHistory.created_at.desc()).all()
        history_tag_colors = tag_color_map()
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

        pending_form_data = None

        if request.method == "POST":
            pending_form_data = request.form.to_dict(flat=True)
            email = (request.form.get("email") or "").strip()
            alternate_emails_raw = (request.form.get("alternate_emails") or "").strip()
            alternate_emails_list, invalid_alternate_emails, duplicate_alternate_emails = parse_email_list(alternate_emails_raw)
            customer_name = (request.form.get("customer_name") or "").strip()

            _common_ctx = dict(
                customer=customer, is_edit=True,
                status_options=status_options, segment_options=segment_options,
                cloud_options=cloud_options, admin_users=admin_users,
                email_templates=email_templates,
                history_entries=history_entries, history_tag_colors=history_tag_colors,
                update_tags=update_tags,
                gathering_entries=gathering_entries, file_nas_entries=file_nas_entries,
                block_storage_entries=block_storage_entries,
                documents=documents, gathering_requests=gathering_requests,
                reference_contacts=reference_contacts, ref_activity_map=ref_activity_map,
                all_reference_contacts=all_reference_contacts,
                assigned_reference_ids=assigned_reference_ids,
                active_tab="info",
                base_url=current_app.config.get("APP_BASE_URL", "http://127.0.0.1:5000"),
                pending_form_data=pending_form_data,
            )

            def _re_render(msg):
                flash(msg, "error")
                return render_template("customer_form.html", **_common_ctx)

            if not email or not customer_name:
                return _re_render("Opportunity name and email are required.")
            if invalid_alternate_emails:
                return _re_render("Please enter valid alternate emails separated by comma.")
            if duplicate_alternate_emails:
                return _re_render("Duplicate alternate emails are not allowed.")
            if email and email.strip().lower() in set(alternate_emails_list):
                return _re_render("Alternate emails cannot be same as main email.")
            if Customer.query.filter(Customer.email == email, Customer.id != customer.id).first():
                return _re_render("Another opportunity already uses this email.")

            new_values = {
                "account_name": (request.form.get("account_name") or "").strip(),
                "customer_name": customer_name,
                "email": email,
                "alternate_emails": ", ".join(alternate_emails_list),
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

            try:
                financial_payload = build_financial_payload(request.form, new_values["segment"])
            except ValueError as exc:
                return _re_render(str(exc))

            field_labels = {
                "account_name": "Account Name",
                "customer_name": "Customer Name",
                "email": "Email",
                "alternate_emails": "Alternate Emails",
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

            changed_lines.extend(financial_change_lines(customer.financial_profile, financial_payload))

            if not changed_lines:
                return _re_render("No changes detected.")

            change_remark = (request.form.get("change_remark") or "").strip()
            if not change_remark:
                return _re_render("Remark is required when making changes.")

            for field, new_val in new_values.items():
                setattr(customer, field, new_val)

            apply_financial_payload(customer.id, financial_payload)
            db.session.commit()

            log_opportunity_history(
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
            pending_form_data=None,
        )

    @bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
    @bp.route("/opportunities/<int:customer_id>/delete", methods=["POST"])
    def opportunity_delete(customer_id):
        customer = Customer.query.get_or_404(customer_id)
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
        OpportunityFinancial.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
        EmailLog.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
        db.session.delete(customer)
        db.session.commit()
        flash("Opportunity deleted.", "success")
        return redirect(url_for("crm.opportunity_list"))

    @bp.route("/opportunities/quick-add", methods=["POST"])
    @login_required
    def opportunity_quick_add():
        ensure_default_cloud_operators()
        customer_name = (request.form.get("customer_name") or "").strip()
        account_name = (request.form.get("account_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        cloud = (request.form.get("cloud") or "").strip()

        if not customer_name or not account_name or not email or not phone or not cloud:
            flash("Quick Add requires Customer Name, Company, Email, Phone Number, and Cloud.", "error")
            return redirect(url_for("crm.opportunity_list"))

        if not is_valid_email(email):
            flash("Please enter a valid email for Quick Add.", "error")
            return redirect(url_for("crm.opportunity_list"))

        if Customer.query.filter_by(email=email).first():
            flash("Opportunity with this email already exists.", "error")
            return redirect(url_for("crm.opportunity_list"))

        if not OpportunityCloudOperator.query.filter_by(name=cloud, is_active=True).first():
            flash("Please select a valid cloud operator.", "error")
            return redirect(url_for("crm.opportunity_list"))

        customer = Customer(
            customer_name=customer_name, account_name=account_name,
            email=email, phone=phone, cloud=cloud,
        )
        db.session.add(customer)
        db.session.commit()

        log_opportunity_history(
            customer.id,
            action="quick-created",
            changes_summary="Opportunity created from Quick Add form.",
            remark=(request.form.get("change_remark") or "").strip() or None,
        )
        db.session.commit()

        flash("Opportunity added successfully via Quick Add.", "success")
        return redirect(url_for("crm.opportunity_list"))

    @bp.route("/opportunities/<int:customer_id>/status", methods=["POST"])
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
        log_opportunity_history(
            customer.id, action="status-updated",
            changes_summary=f"Status: '{old_status}' -> '{status_name}'",
            remark=change_remark,
        )
        db.session.commit()
        flash("Opportunity status updated.", "success")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    @bp.route("/opportunities/<int:customer_id>/segment", methods=["POST"])
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
        log_opportunity_history(
            customer.id, action="segment-updated",
            changes_summary=f"Segment: '{old_segment}' -> '{segment_name}'",
            remark=change_remark,
        )
        db.session.commit()
        flash("Opportunity segment updated.", "success")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    @bp.route("/opportunities/<int:customer_id>/assign", methods=["POST"])
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
        log_opportunity_history(
            customer.id, action="assign-updated",
            changes_summary=f"Assign To: '{old_name}' -> '{new_name}'",
            remark=change_remark,
        )
        db.session.commit()
        flash("Opportunity assignee updated.", "success")
        return redirect(url_for("crm.opportunity_list", page=page, q=q, assigned_to=assigned_to))

    @bp.route("/opportunities/<int:customer_id>/history", methods=["GET"])
    def opportunity_history(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        change_entries = OpportunityHistory.query.filter_by(customer_id=customer.id).all()
        email_entries = EmailLog.query.filter_by(customer_id=customer.id).all()
        tag_colors = tag_color_map()

        timeline = []
        for h in change_entries:
            timeline.append({
                "_dt": h.created_at,
                "created_at": h.created_at.strftime("%Y-%m-%d %H:%M"),
                "changed_by": h.changed_by or "system",
                "action": h.action,
                "tag": (h.tag_name or derive_tag_from_action(h.action)).lower(),
                "tag_color": tag_colors.get((h.tag_name or derive_tag_from_action(h.action)).lower(), "#6b7280"),
                "changes_summary": h.changes_summary,
                "remark": h.remark or "",
            })

        for e in email_entries:
            template_name = e.template.name if e.template else "Custom Email"
            recipient = e.recipient_email or (e.customer.email if e.customer else "")
            summary = (
                f"Email to {recipient} | Template: {template_name} | "
                f"Status: {e.status} | Subject: {e.subject}"
            )
            timeline.append({
                "_dt": e.created_at,
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "changed_by": "system",
                "action": f"email-{e.email_type}",
                "tag": "email",
                "tag_color": tag_colors.get("email", "#1d4ed8"),
                "changes_summary": summary,
                "remark": e.error_message or "",
            })

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

    @bp.route("/opportunities/<int:customer_id>/history/add", methods=["POST"])
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

        log_opportunity_history(
            customer.id, action="manual-update",
            changes_summary=update_text,
            remark=remark or None,
            tag_name=selected_tag,
        )
        db.session.commit()
        return jsonify(success=True, message="Update added successfully.")

    @bp.route("/opportunities/<int:customer_id>/history/add-form", methods=["POST"])
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

        log_opportunity_history(
            customer.id, action="manual-update",
            changes_summary=update_text,
            remark=remark or None,
            tag_name=selected_tag,
        )
        db.session.commit()
        flash("Manual update added.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="history"))

    # ── Deprecated / Redirect stubs ──────────────────────────────────────────

    @bp.route("/opportunities/<int:customer_id>/sow", methods=["GET"])
    @login_required
    def opportunity_sow(customer_id):
        flash("SOW editor has been removed. Use Document Editor.", "info")
        return redirect(url_for("crm.opportunity_document_editor", customer_id=customer_id))

    @bp.route("/opportunities/<int:customer_id>/sow/save", methods=["POST"])
    @login_required
    def opportunity_sow_save(customer_id):
        return jsonify(success=False, message="SOW editor has been removed. Use Document Editor.")

    @bp.route("/opportunities/<int:customer_id>/sow/download-docx", methods=["POST"])
    @login_required
    def opportunity_sow_download_docx(customer_id):
        return jsonify(success=False, message="SOW editor has been removed. Use Document Editor.")

    @bp.route("/opportunities/<int:customer_id>/sow/download-pdf", methods=["POST"])
    @login_required
    def opportunity_sow_download_pdf(customer_id):
        return jsonify(success=False, message="SOW editor has been removed. Use Document Editor.")

    @bp.route("/opportunities/<int:customer_id>/sow/send-email", methods=["POST"])
    @login_required
    def opportunity_sow_send_email(customer_id):
        return jsonify(success=False, message="SOW editor has been removed. Use Document Editor.")

    @bp.route("/opportunities/<int:customer_id>/gathering-data/send-link", methods=["POST"])
    @login_required
    def opportunity_gathering_data_send_link(customer_id):
        return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))

    @bp.route("/opportunities/<int:customer_id>/gathering-data", methods=["GET", "POST"])
    def opportunity_gathering_data(customer_id):
        return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))

    @bp.route("/opportunities/<int:customer_id>/gathering-data/<int:entry_id>/delete", methods=["POST"])
    def opportunity_gathering_data_delete(customer_id, entry_id):
        return redirect(url_for("crm.opportunity_edit", customer_id=customer_id, tab="gathering"))
