import base64
from datetime import datetime
import json
import io
import re
from pathlib import Path
import urllib.request

from flask import current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.models import Customer, CustomerDiagram, CustomerDocument, SOWMasterTemplate, db
from app.services.storage_service import StorageService


def _editor_metadata_comment(meta):
    safe_meta = meta or {}
    return f"<!--AMBIFO_EDITOR_META:{json.dumps(safe_meta, ensure_ascii=True)}-->"


def _build_editor_document_html(content_html, meta, full_html=None):
    encoded_content = base64.b64encode((content_html or "").encode("utf-8")).decode("ascii")
    content_marker = f"<!--AMBIFO_EDITOR_CONTENT_B64:{encoded_content}-->"
    rendered_full_html = (full_html or "").strip()
    if not rendered_full_html:
        rendered_full_html = (content_html or "").strip()
    return f"{_editor_metadata_comment(meta)}\n{content_marker}\n{rendered_full_html}"


def _parse_editor_document_html(raw_text):
    text = raw_text or ""
    meta_match = re.search(r"<!--AMBIFO_EDITOR_META:(\{[\s\S]*?\})-->", text)
    meta = {}
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1))
        except Exception:
            meta = {}

    b64_match = re.search(r"<!--AMBIFO_EDITOR_CONTENT_B64:([A-Za-z0-9+/=]+)-->", text)
    content_html = ""
    if b64_match:
        try:
            content_html = base64.b64decode(b64_match.group(1)).decode("utf-8", errors="ignore")
        except Exception:
            content_html = ""

    full_html = text
    if meta_match:
        full_html = full_html.replace(meta_match.group(0), "", 1)
    if b64_match:
        full_html = full_html.replace(b64_match.group(0), "", 1)
    full_html = full_html.strip()

    if not content_html:
        content_html = full_html

    if not meta_match and not b64_match:
        return {}, text, ""

    return meta, content_html, full_html


def _read_customer_document_text(doc):
    if doc.file_path and Path(doc.file_path).exists():
        try:
            return Path(doc.file_path).read_text(encoding="utf-8")
        except Exception:
            return Path(doc.file_path).read_text(encoding="utf-8", errors="ignore")

    if doc.blob_url:
        with urllib.request.urlopen(doc.blob_url, timeout=8) as response:
            payload = response.read()
        return payload.decode("utf-8", errors="ignore")

    return ""


def _editor_document_payload_from_record(doc):
    raw_text = _read_customer_document_text(doc)
    meta, content_html, full_html = _parse_editor_document_html(raw_text)
    return {
        "doc_id": doc.id,
        "title": (meta.get("title") or doc.original_filename or "").replace(".html", ""),
        "ref_no": meta.get("ref_no") or "",
        "version": meta.get("version") or "1.0",
        "doc_date": meta.get("doc_date") or "",
        "expiry_days": meta.get("expiry_days") or 7,
        "content_html": content_html,
        "full_html": full_html,
    }


def register_opportunity_document_routes(
    bp,
    *,
    actor_name,
    log_history,
    sanitize_sow_export_html,
    generate_sow_docx,
    generate_html_like_pdf,
    get_sow_brand_config,
    next_document_editor_ref_no,
    compose_master_template_html,
    render_sow_template_for_customer,
):
    if getattr(bp, "_opportunity_document_routes_registered", False):
        return
    setattr(bp, "_opportunity_document_routes_registered", True)

    @bp.route("/document-editor")
    @login_required
    def document_editor():
        templates = SOWMasterTemplate.query.order_by(SOWMasterTemplate.created_at.asc()).all()
        initial_doc_ref_no = next_document_editor_ref_no()
        return render_template(
            "document_editor.html",
            sow_brand_cfg=get_sow_brand_config(),
            brand_logo_url=url_for("static", filename="ambifologo.png"),
            document_templates=templates,
            initial_doc_ref_no=initial_doc_ref_no,
            back_url=url_for("crm.dashboard"),
            opportunity_customer=None,
            opportunity_documents=[],
            initial_editor_document=None,
        )

    @bp.route("/document-editor/ref-no", methods=["POST"])
    @login_required
    def document_editor_ref_no():
        return jsonify({"ref_no": next_document_editor_ref_no()})

    @bp.route("/document-editor/templates/<int:template_id>", methods=["GET"])
    @login_required
    def document_editor_template_load(template_id):
        master = SOWMasterTemplate.query.get_or_404(template_id)
        html_content = compose_master_template_html(master)

        customer_id = request.args.get("customer_id", type=int)
        if customer_id:
            customer = Customer.query.get_or_404(customer_id)
            selected_diagrams = (
                CustomerDiagram.query
                .filter_by(customer_id=customer.id, is_active=True)
                .order_by(CustomerDiagram.created_at.asc())
                .all()
            )
            html_content = render_sow_template_for_customer(
                html_content,
                customer,
                selected_diagrams=selected_diagrams,
                sow=None,
            )

        return jsonify(
            {
                "template_id": master.id,
                "template_name": master.template_name,
                "content_html": html_content,
            }
        )

    @bp.route("/opportunities/<int:customer_id>/documents/upload", methods=["POST"])
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
            uploaded_by=actor_name(),
        )
        db.session.add(doc)
        log_history(
            customer.id,
            action="document-uploaded",
            changes_summary=f"Document '{upload.filename}' uploaded (backend: {result.storage_backend}).",
            tag_name="document",
        )
        db.session.commit()
        flash(f"Document '{upload.filename}' uploaded.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/download")
    @login_required
    def opportunity_document_download(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        if doc.storage_backend in ("azure", "aws", "gcp") and doc.blob_url:
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

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/download-docx")
    @login_required
    def opportunity_document_download_docx(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        try:
            payload = _editor_document_payload_from_record(doc)
        except Exception as exc:
            flash(f"Unable to load editor document: {exc}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        content_html = sanitize_sow_export_html(payload.get("content_html") or "")
        if not content_html:
            flash("Document content is empty.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        title = (payload.get("title") or doc.original_filename or "Opportunity Document").strip()
        version = (payload.get("version") or "1.0").strip()
        doc_date = (payload.get("doc_date") or "").strip()
        ref_no = (payload.get("ref_no") or "").strip()

        try:
            file_bytes = generate_sow_docx(
                customer,
                title,
                doc_date,
                version,
                content_html,
                document_title_label="Opportunity Document",
                doc_ref_no=ref_no,
            )
        except Exception as exc:
            flash(f"DOC generation failed: {exc}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", title)[:60] or "opportunity_document"
        filename = f"{safe_title}_v{version}.docx"
        return send_file(
            io.BytesIO(file_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/download-pdf")
    @login_required
    def opportunity_document_download_pdf(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        try:
            payload = _editor_document_payload_from_record(doc)
        except Exception as exc:
            flash(f"Unable to load editor document: {exc}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        content_html = sanitize_sow_export_html(payload.get("content_html") or "")
        saved_full_html = (payload.get("full_html") or "").strip()
        if not content_html:
            flash("Document content is empty.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        title = (payload.get("title") or doc.original_filename or "Opportunity Document").strip()
        version = (payload.get("version") or "1.0").strip()

        try:
            if "<html" in saved_full_html.lower():
                file_bytes = generate_html_like_pdf(title, saved_full_html)
            else:
                file_bytes = generate_html_like_pdf(title, content_html)
        except Exception as exc:
            flash(f"PDF generation failed: {exc}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        safe_title = re.sub(r"[^a-zA-Z0-9_\-]", "_", title)[:60] or "opportunity_document"
        filename = f"{safe_title}_v{version}.pdf"
        return send_file(
            io.BytesIO(file_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="application/pdf",
        )

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/delete", methods=["POST"])
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
        log_history(
            customer.id,
            action="document-deleted",
            changes_summary=f"Document '{fname}' deleted.",
            tag_name="document",
        )
        db.session.commit()
        flash(f"Document '{fname}' deleted.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

    @bp.route("/opportunities/<int:customer_id>/document-editor", methods=["GET"])
    @login_required
    def opportunity_document_editor(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        templates = SOWMasterTemplate.query.order_by(SOWMasterTemplate.created_at.asc()).all()
        documents = (
            CustomerDocument.query
            .filter_by(customer_id=customer.id)
            .order_by(CustomerDocument.created_at.desc())
            .all()
        )

        doc_id = request.args.get("doc_id", type=int)
        selected_doc = None
        initial_editor_document = None

        if doc_id:
            selected_doc = CustomerDocument.query.filter_by(id=doc_id, customer_id=customer.id).first_or_404()
            try:
                initial_editor_document = _editor_document_payload_from_record(selected_doc)
            except Exception as exc:
                flash(f"Unable to load document for editing: {exc}", "error")
                return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"))

        initial_doc_ref_no = (
            initial_editor_document.get("ref_no")
            if initial_editor_document and initial_editor_document.get("ref_no")
            else next_document_editor_ref_no()
        )

        return render_template(
            "document_editor.html",
            sow_brand_cfg=get_sow_brand_config(),
            brand_logo_url=url_for("static", filename="ambifologo.png"),
            document_templates=templates,
            initial_doc_ref_no=initial_doc_ref_no,
            back_url=url_for("crm.opportunity_edit", customer_id=customer.id, tab="documents"),
            opportunity_customer=customer,
            opportunity_documents=documents,
            initial_editor_document=initial_editor_document,
        )

    @bp.route("/opportunities/<int:customer_id>/document-editor/save", methods=["POST"])
    @login_required
    def opportunity_document_editor_save(customer_id):
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json(silent=True) or {}

        title = (data.get("title") or "").strip() or f"Opportunity Document - {customer.customer_name}"
        ref_no = (data.get("ref_no") or "").strip()
        version = (data.get("version") or "1.0").strip() or "1.0"
        doc_date = (data.get("doc_date") or "").strip()
        content_html = (data.get("content_html") or "").strip()
        full_html = (data.get("full_html") or "").strip()

        try:
            expiry_days = int(data.get("expiry_days") or 7)
        except (TypeError, ValueError):
            expiry_days = 7
        expiry_days = max(1, min(expiry_days, 3650))

        if not content_html:
            return jsonify(success=False, message="Document content is empty."), 400

        doc_id = data.get("doc_id")
        try:
            doc_id = int(doc_id) if doc_id is not None else None
        except (TypeError, ValueError):
            doc_id = None

        doc = CustomerDocument.query.filter_by(id=doc_id, customer_id=customer.id).first() if doc_id else None
        if not doc:
            doc = CustomerDocument(customer_id=customer.id, uploaded_by=actor_name())
            db.session.add(doc)

        safe_title = secure_filename(title) or f"opportunity_document_{customer.id}"
        original_filename = f"{safe_title}.html"
        metadata = {
            "title": title,
            "ref_no": ref_no,
            "version": version,
            "doc_date": doc_date,
            "expiry_days": expiry_days,
            "customer_id": customer.id,
            "saved_at": datetime.utcnow().isoformat(),
        }
        combined_html = _build_editor_document_html(content_html, metadata, full_html=full_html)
        payload = combined_html.encode("utf-8")

        svc = StorageService(current_app._get_current_object())
        if doc.id and (doc.file_path or doc.blob_url):
            svc.delete_document(doc)

        upload_file = FileStorage(
            stream=io.BytesIO(payload),
            filename=original_filename,
            content_type="text/html",
        )
        result = svc.save_document(upload_file, original_filename, customer.id)
        if not result.success:
            return jsonify(success=False, message=f"Save failed: {result.error}"), 500

        doc.original_filename = original_filename
        doc.stored_filename = result.stored_filename
        doc.file_path = result.file_path
        doc.blob_url = result.blob_url
        doc.storage_backend = result.storage_backend
        doc.file_size_bytes = len(payload)
        doc.mime_type = "text/html"
        doc.description = f"[Document Editor] Ref: {ref_no or 'N/A'} | Ver: {version}"
        doc.uploaded_by = actor_name()

        log_history(
            customer.id,
            action="document-editor-saved",
            changes_summary=f"Document editor saved '{original_filename}' (Ref: {ref_no or 'N/A'}, Ver: {version}).",
            tag_name="document",
        )
        db.session.commit()

        return jsonify(
            success=True,
            message="Document saved.",
            doc_id=doc.id,
            filename=doc.original_filename,
            ref_no=ref_no,
        )

    @bp.route("/opportunities/<int:customer_id>/document-editor/documents/<int:doc_id>", methods=["GET"])
    @login_required
    def opportunity_document_editor_load(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.filter_by(id=doc_id, customer_id=customer.id).first_or_404()

        try:
            payload = _editor_document_payload_from_record(doc)
        except Exception as exc:
            return jsonify(success=False, message=f"Unable to read document: {exc}"), 500

        return jsonify(success=True, document=payload)
