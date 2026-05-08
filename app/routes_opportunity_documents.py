import base64
from datetime import datetime
import hashlib
import hmac
import json
import io
import re
from pathlib import Path
import urllib.request

from flask import Response, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
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
        "docusign_status": doc.docusign_status,
        "docusign_envelope_id": doc.docusign_envelope_id,
        "docusign_completed_at": (doc.docusign_completed_at.isoformat() if doc.docusign_completed_at else None),
        "signed_pdf_path": doc.signed_pdf_path,
    }


def _extract_docusign_webhook_event(raw_body, content_type):
    """Parse DocuSign Connect webhook payload (JSON or XML-ish) and extract event.

    Returns tuple: (envelope_id, status, completed_at_iso_or_empty)
    """
    body_text = (raw_body or b"").decode("utf-8", errors="ignore")
    lower_ct = (content_type or "").lower()

    envelope_id = ""
    status = ""
    completed_at = ""

    if "json" in lower_ct or body_text.lstrip().startswith("{"):
        try:
            payload = json.loads(body_text)
        except Exception:
            payload = {}

        envelope_id = str(
            payload.get("envelopeId")
            or payload.get("envelope_id")
            or (payload.get("data") or {}).get("envelopeId")
            or (payload.get("data") or {}).get("envelope_id")
            or ""
        ).strip()
        status = str(
            payload.get("status")
            or payload.get("envelopeStatus")
            or (payload.get("data") or {}).get("status")
            or (payload.get("data") or {}).get("envelopeStatus")
            or ""
        ).strip().lower()
        completed_at = str(
            payload.get("completedDateTime")
            or payload.get("completed_at")
            or (payload.get("data") or {}).get("completedDateTime")
            or ""
        ).strip()
        return envelope_id, status, completed_at

    envelope_match = re.search(r"<envelopeId>([^<]+)</envelopeId>", body_text, flags=re.IGNORECASE)
    if envelope_match:
        envelope_id = envelope_match.group(1).strip()

    status_match = re.search(r"<status>([^<]+)</status>", body_text, flags=re.IGNORECASE)
    if status_match:
        status = status_match.group(1).strip().lower()

    completed_match = re.search(r"<completedDateTime>([^<]+)</completedDateTime>", body_text, flags=re.IGNORECASE)
    if completed_match:
        completed_at = completed_match.group(1).strip()

    return envelope_id, status, completed_at


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

    @bp.route("/opportunities/<int:customer_id>/sign-requests/upload-and-send", methods=["POST"])
    @login_required
    def opportunity_sign_request_upload_and_send(customer_id):
        customer = Customer.query.get_or_404(customer_id)

        upload = request.files.get("document_file")
        if not upload or not upload.filename:
            flash("Please choose a file to upload for sign request.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        signer_name = (request.form.get("signer_name") or customer.customer_name or "").strip()
        signer_email = (request.form.get("signer_email") or customer.email or "").strip()
        if not signer_name or not signer_email or "@" not in signer_email:
            flash("Valid signer name and signer email are required.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        email_subject = (request.form.get("email_subject") or "").strip()
        email_body = (request.form.get("email_body") or "").strip()
        description = (request.form.get("doc_description") or "").strip()

        raw_bytes = upload.read()
        if not raw_bytes:
            flash("Uploaded file is empty.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        import mimetypes  # noqa: PLC0415

        detected_mime = upload.mimetype or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"
        ext = Path(upload.filename).suffix.lower()

        # Step 1: Save uploaded source document as a normal opportunity document.
        svc = StorageService(current_app._get_current_object())
        upload_file = FileStorage(
            stream=io.BytesIO(raw_bytes),
            filename=upload.filename,
            content_type=detected_mime,
        )
        save_result = svc.save_document(upload_file, upload.filename, customer.id)
        if not save_result.success:
            flash(f"Upload failed: {save_result.error}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        doc = CustomerDocument(
            customer_id=customer.id,
            original_filename=upload.filename,
            stored_filename=save_result.stored_filename,
            file_path=save_result.file_path,
            blob_url=save_result.blob_url,
            storage_backend=save_result.storage_backend,
            file_size_bytes=len(raw_bytes),
            mime_type=detected_mime,
            description=(description or "[Sign Request] Uploaded for DocuSign"),
            uploaded_by=actor_name(),
        )
        db.session.add(doc)
        db.session.flush()

        log_history(
            customer.id,
            action="docusign-sign-request-uploaded",
            changes_summary=(
                f"Document '{doc.original_filename}' uploaded for DocuSign sign request. "
                f"Signer: {signer_name} <{signer_email}>."
            ),
            tag_name="docusign",
        )

        # Step 2: Build PDF bytes for DocuSign (supports PDF and HTML upload).
        file_title = (Path(upload.filename).stem or "document").strip()
        if detected_mime == "application/pdf" or ext == ".pdf":
            pdf_bytes = raw_bytes
        elif detected_mime.startswith("text/html") or ext in {".html", ".htm"}:
            html_text = raw_bytes.decode("utf-8", errors="ignore")
            try:
                pdf_bytes = generate_html_like_pdf(file_title, html_text)
            except Exception as exc:
                db.session.commit()
                flash(f"Document uploaded, but PDF conversion failed for signing: {exc}", "error")
                return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))
        else:
            db.session.commit()
            flash("Document uploaded, but only PDF or HTML files can be sent for DocuSign from this form.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        # Step 3: Send envelope to DocuSign.
        from app.services.docusign_service import DocuSignService

        ds = DocuSignService(current_app._get_current_object())
        send_result = ds.send_envelope(
            pdf_bytes=pdf_bytes,
            document_name=(file_title + ".pdf"),
            signer_name=signer_name,
            signer_email=signer_email,
            email_subject=(email_subject or None),
            email_body=(email_body or None),
        )

        if not send_result.success:
            db.session.commit()
            flash(f"Document uploaded, but DocuSign send failed: {send_result.error}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        doc.docusign_envelope_id = (send_result.envelope_id or "").strip() or None
        doc.docusign_status = "sent"
        doc.docusign_sent_at = datetime.utcnow()
        doc.docusign_signer_name = signer_name
        doc.docusign_signer_email = signer_email

        log_history(
            customer.id,
            action="docusign-sent",
            changes_summary=(
                f"Sign request sent via DocuSign for '{doc.original_filename}' to "
                f"{signer_name} <{signer_email}>. Envelope ID: {send_result.envelope_id}."
            ),
            tag_name="docusign",
        )
        db.session.commit()

        flash(f"Sign request sent successfully. Envelope ID: {send_result.envelope_id}", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

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

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/preview")
    @login_required
    def opportunity_document_preview(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab="sign-requests"))

        # For editor HTML documents, return rendered full HTML inline.
        try:
            if (doc.description or "").startswith("[Document Editor]"):
                payload = _editor_document_payload_from_record(doc)
                html_body = (payload.get("full_html") or payload.get("content_html") or "").strip()
                if html_body:
                    return Response(html_body, mimetype="text/html")
        except Exception:
            pass

        # For non-editor HTML documents stored locally, preview as text/html.
        if (doc.mime_type or "").startswith("text/html") and doc.file_path and Path(doc.file_path).exists():
            try:
                html_body = Path(doc.file_path).read_text(encoding="utf-8")
            except Exception:
                html_body = Path(doc.file_path).read_text(encoding="utf-8", errors="ignore")
            return Response(html_body, mimetype="text/html")

        # Cloud-hosted assets can be previewed directly via blob URL.
        if doc.blob_url and doc.storage_backend in {"azure", "aws", "gcp"}:
            return redirect(doc.blob_url)

        # Fallback to normal file download route.
        return redirect(url_for("crm.opportunity_document_download", customer_id=customer.id, doc_id=doc.id))

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

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/docusign/signed-download")
    @login_required
    def download_signed_docusign_pdf(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_document_editor", customer_id=customer.id))

        signed_path = (doc.signed_pdf_path or "").strip()
        if not signed_path:
            flash("Signed PDF is not available yet.", "error")
            return redirect(url_for("crm.opportunity_document_editor", customer_id=customer.id))

        if signed_path.startswith("http://") or signed_path.startswith("https://"):
            return redirect(signed_path)

        fpath = Path(signed_path)
        if not fpath.exists() or not fpath.is_file():
            flash("Signed PDF file was not found in storage.", "error")
            return redirect(url_for("crm.opportunity_document_editor", customer_id=customer.id))

        download_name = (doc.original_filename or f"document_{doc.id}.html").replace(".html", "") + "_signed.pdf"
        return send_file(fpath, as_attachment=True, download_name=download_name, mimetype="application/pdf")

    @bp.route("/opportunities/<int:customer_id>/documents/<int:doc_id>/docusign/refresh", methods=["POST"])
    @login_required
    def refresh_document_docusign_status(customer_id, doc_id):
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.get_or_404(doc_id)
        return_tab = (request.form.get("return_tab") or request.args.get("return_tab") or "documents").strip() or "documents"
        if return_tab not in {"documents", "sign-requests"}:
            return_tab = "documents"
        if doc.customer_id != customer.id:
            flash("Document not found.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab=return_tab))

        envelope_id = (doc.docusign_envelope_id or "").strip()
        if not envelope_id:
            flash("This document is not linked to a DocuSign envelope yet.", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab=return_tab))

        from app.services.docusign_service import DocuSignService

        ds = DocuSignService(current_app._get_current_object())
        live_status = ds.get_envelope_status(envelope_id)
        if str(live_status).startswith("error:"):
            flash(f"DocuSign status fetch failed: {live_status}", "error")
            return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab=return_tab))

        normalized = str(live_status).strip().lower() or "unknown"
        previous = (doc.docusign_status or "").strip().lower()
        doc.docusign_status = normalized

        if normalized == "completed" and not doc.docusign_completed_at:
            doc.docusign_completed_at = datetime.utcnow()
            try:
                signed_pdf = ds.download_signed_document(envelope_id)
                signed_name = (doc.original_filename or f"document_{doc.id}.html").replace(".html", "") + "_signed.pdf"
                upload_file = FileStorage(
                    stream=io.BytesIO(signed_pdf),
                    filename=signed_name,
                    content_type="application/pdf",
                )
                storage = StorageService(current_app._get_current_object())
                saved = storage.save_document(upload_file, signed_name, customer.id)
                if saved.success:
                    doc.signed_pdf_path = (saved.blob_url or saved.file_path or "").strip() or None
            except Exception:
                pass

        if previous != normalized:
            log_history(
                customer.id,
                action="docusign-status-refresh",
                changes_summary=(
                    f"DocuSign status changed for '{doc.original_filename}': "
                    f"{previous or 'none'} -> {normalized}."
                ),
                tag_name="docusign",
            )

        db.session.commit()
        flash(f"DocuSign status updated: {normalized}.", "success")
        return redirect(url_for("crm.opportunity_edit", customer_id=customer.id, tab=return_tab))

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

    @bp.route("/opportunities/<int:customer_id>/docusign/send", methods=["POST"])
    @login_required
    def opportunity_docusign_send(customer_id):
        """Send a saved CustomerDocument to the customer for e-signature via DocuSign.

        DocuSign emails the signer automatically — Ambifo does not send the email.
        """
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json(silent=True) or {}

        doc_id = data.get("doc_id")
        try:
            doc_id = int(doc_id)
        except (TypeError, ValueError):
            return jsonify(success=False, error="doc_id is required."), 400

        doc = CustomerDocument.query.filter_by(id=doc_id, customer_id=customer.id).first()
        if not doc:
            return jsonify(success=False, error="Document not found."), 404

        signer_name  = (data.get("signer_name") or customer.customer_name or "").strip()
        signer_email = (data.get("signer_email") or customer.email or "").strip()
        if not signer_name or not signer_email or "@" not in signer_email:
            return jsonify(success=False, error="Valid signer name and email are required."), 400

        # Generate PDF from the saved HTML document.
        try:
            raw_html = _read_customer_document_text(doc)
            _meta, _content_html, full_html = _parse_editor_document_html(raw_html)
            pdf_bytes = generate_html_like_pdf(full_html or _content_html)
        except Exception as exc:
            return jsonify(success=False, error=f"PDF generation failed: {exc}"), 500

        # Send via DocuSign.
        from app.services.docusign_service import DocuSignService
        ds = DocuSignService(current_app._get_current_object())
        doc_name = doc.original_filename.replace(".html", ".pdf")
        result = ds.send_envelope(
            pdf_bytes=pdf_bytes,
            document_name=doc_name,
            signer_name=signer_name,
            signer_email=signer_email,
            email_subject=data.get("email_subject") or None,
            email_body=data.get("email_body") or None,
        )

        if not result.success:
            return jsonify(success=False, error=result.error), 500

        doc.docusign_envelope_id = (result.envelope_id or "").strip() or None
        doc.docusign_status = "sent"
        doc.docusign_sent_at = datetime.utcnow()
        doc.docusign_completed_at = None
        doc.docusign_signer_name = signer_name
        doc.docusign_signer_email = signer_email

        log_history(
            customer.id,
            action="docusign-sent",
            changes_summary=(
                f"Document '{doc_name}' sent for e-signature via DocuSign to {signer_name} <{signer_email}>. "
                f"Envelope ID: {result.envelope_id}."
            ),
            tag_name="docusign",
        )
        db.session.commit()

        return jsonify(success=True, envelope_id=result.envelope_id)

    @bp.route("/opportunities/<int:customer_id>/docusign/status/<int:doc_id>", methods=["GET"])
    @login_required
    def opportunity_docusign_status(customer_id, doc_id):
        """Return the current DocuSign envelope status for a document (JSON)."""
        customer = Customer.query.get_or_404(customer_id)
        doc = CustomerDocument.query.filter_by(id=doc_id, customer_id=customer.id).first()
        if not doc:
            return jsonify(success=False, error="Document not found."), 404

        envelope_id = (doc.docusign_envelope_id or "").strip()
        if not envelope_id:
            return jsonify(success=False, error="No DocuSign envelope linked to this document."), 400

        from app.services.docusign_service import DocuSignService
        ds = DocuSignService(current_app._get_current_object())
        live_status = ds.get_envelope_status(envelope_id)
        if str(live_status).startswith("error:"):
            return jsonify(success=False, error=live_status), 502

        normalized = str(live_status).strip().lower() or "unknown"
        previous = (doc.docusign_status or "").strip().lower()
        doc.docusign_status = normalized

        if normalized == "completed" and not doc.docusign_completed_at:
            doc.docusign_completed_at = datetime.utcnow()
            try:
                signed_pdf = ds.download_signed_document(envelope_id)
                signed_name = (doc.original_filename or f"document_{doc.id}.html").replace(".html", "") + "_signed.pdf"
                upload_file = FileStorage(
                    stream=io.BytesIO(signed_pdf),
                    filename=signed_name,
                    content_type="application/pdf",
                )
                storage = StorageService(current_app._get_current_object())
                saved = storage.save_document(upload_file, signed_name, customer.id)
                if saved.success:
                    doc.signed_pdf_path = (saved.blob_url or saved.file_path or "").strip() or None
            except Exception:
                pass

        if previous != normalized:
            log_history(
                customer.id,
                action="docusign-status",
                changes_summary=(
                    f"DocuSign status changed for '{doc.original_filename}': "
                    f"{previous or 'none'} -> {normalized}."
                ),
                tag_name="docusign",
            )

        db.session.commit()

        return jsonify(
            success=True,
            doc_id=doc_id,
            envelope_id=envelope_id,
            status=doc.docusign_status,
            completed_at=(doc.docusign_completed_at.isoformat() if doc.docusign_completed_at else None),
            signed_pdf_path=doc.signed_pdf_path,
        )

    @bp.route("/docusign/webhook", methods=["POST"])
    def docusign_webhook():
        """DocuSign Connect webhook endpoint.

        Validates optional HMAC signature and updates document status by envelope ID.
        """
        raw_body = request.get_data(cache=False, as_text=False) or b""
        configured_secret = (current_app.config.get("DOCUSIGN_WEBHOOK_HMAC") or "").strip()
        if not configured_secret:
            from app.models import SystemSetting
            configured_secret = (SystemSetting.get_value("docusign.webhook_hmac", "") or "").strip()

        incoming_sig = (request.headers.get("X-DocuSign-Signature-1") or "").strip()
        if configured_secret:
            digest = hmac.new(configured_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
            expected_sig = base64.b64encode(digest).decode("ascii")
            if not incoming_sig or not hmac.compare_digest(incoming_sig, expected_sig):
                return jsonify(success=False, error="Invalid webhook signature."), 401

        envelope_id, status, completed_at = _extract_docusign_webhook_event(
            raw_body,
            request.headers.get("Content-Type") or "",
        )
        if not envelope_id:
            return jsonify(success=True, message="Ignored webhook: envelope_id missing."), 200

        doc = CustomerDocument.query.filter_by(docusign_envelope_id=envelope_id).first()
        if not doc:
            return jsonify(success=True, message="Envelope not linked to any document."), 200

        customer = Customer.query.get(doc.customer_id)
        prev_status = (doc.docusign_status or "").strip().lower()
        new_status = (status or prev_status or "unknown").strip().lower()
        doc.docusign_status = new_status

        if new_status == "completed" and not doc.docusign_completed_at:
            doc.docusign_completed_at = datetime.utcnow()

            # Pull combined signed PDF and store to active document storage.
            try:
                from app.services.docusign_service import DocuSignService
                ds = DocuSignService(current_app._get_current_object())
                signed_pdf = ds.download_signed_document(envelope_id)

                signed_name = (doc.original_filename or f"document_{doc.id}.html").replace(".html", "") + "_signed.pdf"
                upload_file = FileStorage(
                    stream=io.BytesIO(signed_pdf),
                    filename=signed_name,
                    content_type="application/pdf",
                )
                storage = StorageService(current_app._get_current_object())
                saved = storage.save_document(upload_file, signed_name, doc.customer_id)
                if saved.success:
                    doc.signed_pdf_path = (saved.blob_url or saved.file_path or "").strip() or None
            except Exception:
                pass

        if customer and prev_status != new_status:
            log_history(
                customer.id,
                action="docusign-webhook",
                changes_summary=(
                    f"DocuSign webhook update for '{doc.original_filename}': "
                    f"{prev_status or 'none'} -> {new_status}."
                ),
                tag_name="docusign",
            )

        db.session.commit()

        return jsonify(
            success=True,
            envelope_id=envelope_id,
            status=new_status,
            completed_at=(doc.docusign_completed_at.isoformat() if doc.docusign_completed_at else completed_at or None),
        )
