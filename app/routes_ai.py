import html
import re

from flask import current_app, jsonify, request
from flask_login import login_required

from app.models import Customer, SOWMasterTemplate, SOWMasterTemplateSection
from app.services.ai_service import AIService


def register_ai_routes(bp, *, build_ai_customer_context, get_template_sections):
    if getattr(bp, "_ai_routes_registered", False):
        return
    setattr(bp, "_ai_routes_registered", True)

    @bp.route("/ai/generate/email-template", methods=["POST"])
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

    @bp.route("/ai/generate/sow-section-content", methods=["POST"])
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

        sections = get_template_sections(master)
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

    @bp.route("/opportunities/<int:customer_id>/ai/generate-document-content", methods=["POST"])
    @login_required
    def ai_generate_document_content(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json(silent=True) or {}
        objective = (data.get("objective") or "").strip()

        context_text = build_ai_customer_context(customer)
        svc = AIService(current_app)
        result = svc.generate_document_content(context_text, objective)
        if not result.get("success"):
            return jsonify(success=False, message=result.get("error") or "AI generation failed."), 400

        return jsonify(success=True, content_html=result.get("content_html") or "")

    @bp.route("/opportunities/<int:customer_id>/ai/generate-architecture-diagram", methods=["POST"])
    @login_required
    def ai_generate_architecture_diagram(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json(silent=True) or {}
        use_case = (data.get("use_case") or "").strip()

        context_text = build_ai_customer_context(customer)
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
