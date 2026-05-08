from datetime import datetime

from flask import flash, redirect, request, url_for
from flask_login import login_required

from app.models import Customer, CustomerDiagram, db


def register_opportunity_diagram_routes(bp, *, actor_name, log_history, normalize_macro_key):
    if getattr(bp, "_opportunity_diagram_routes_registered", False):
        return
    setattr(bp, "_opportunity_diagram_routes_registered", True)

    @bp.route("/opportunities/<int:customer_id>/diagrams/add", methods=["POST"])
    @login_required
    def opportunity_diagram_add(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        diagram_name = (request.form.get("diagram_name") or "").strip()
        macro_key = normalize_macro_key(request.form.get("macro_key") or "")
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
            created_by=actor_name(),
        )
        db.session.add(diagram)
        log_history(
            customer.id,
            action="diagram-added",
            changes_summary=f"Diagram '{diagram_name}' added with macro {{{{{macro_key}}}}}.",
            tag_name="update",
        )
        db.session.commit()
        flash("Diagram added.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    @bp.route("/opportunities/<int:customer_id>/diagrams/<int:diagram_id>/update", methods=["POST"])
    @login_required
    def opportunity_diagram_update(customer_id, diagram_id):
        customer = Customer.query.get_or_404(customer_id)
        diagram = CustomerDiagram.query.get_or_404(diagram_id)
        if diagram.customer_id != customer.id:
            flash("Diagram not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

        diagram_name = (request.form.get("diagram_name") or "").strip()
        macro_key = normalize_macro_key(request.form.get("macro_key") or "")
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
        log_history(
            customer.id,
            action="diagram-updated",
            changes_summary=f"Diagram '{diagram_name}' updated. Macro: {{{{{old_macro}}}}} -> {{{{{macro_key}}}}}.",
            tag_name="update",
        )
        db.session.commit()
        flash("Diagram updated.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))

    @bp.route("/opportunities/<int:customer_id>/diagrams/<int:diagram_id>/delete", methods=["POST"])
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
        log_history(
            customer.id,
            action="diagram-deleted",
            changes_summary=f"Diagram '{name}' with macro {{{{{macro_key}}}}} deleted.",
            tag_name="update",
        )
        db.session.commit()
        flash("Diagram deleted.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="diagrams"))
