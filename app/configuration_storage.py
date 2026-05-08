import urllib.request
from pathlib import Path

from flask import current_app, flash, redirect, request, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.models import CustomerDocument, db
from app.services.storage_service import StorageService


DOCUMENT_STORAGE_ANCHOR = "#document-storage-config"


def _storage_redirect():
    return redirect(url_for("crm.configuration") + DOCUMENT_STORAGE_ANCHOR)


def handle_configuration_storage_action(action, persist_settings, apply_runtime, log_history):
    if action == "save_document_storage":
        backend = (request.form.get("document_storage_backend") or "local").strip().lower()
        if backend not in {"local", "azure", "aws", "gcp"}:
            flash("Document storage provider must be local, azure, aws, or gcp.", "error")
            return _storage_redirect()

        settings = {
            "backend": backend,
            "documents_folder": (request.form.get("documents_folder") or "documents").strip() or "documents",
            "azure_connection_string": (request.form.get("azure_connection_string") or "").strip(),
            "azure_container_name": (request.form.get("azure_container_name") or "ambifo-documents").strip() or "ambifo-documents",
            "aws_access_key_id": (request.form.get("aws_access_key_id") or "").strip(),
            "aws_secret_access_key": (request.form.get("aws_secret_access_key") or "").strip(),
            "aws_bucket_name": (request.form.get("aws_bucket_name") or "").strip(),
            "aws_region": (request.form.get("aws_region") or "us-east-1").strip() or "us-east-1",
            "gcp_project_id": (request.form.get("gcp_project_id") or "").strip(),
            "gcp_bucket_name": (request.form.get("gcp_bucket_name") or "").strip(),
            "gcp_credentials_json": (request.form.get("gcp_credentials_json") or "").strip(),
        }

        persist_settings(settings)
        apply_runtime(settings)
        flash(f"Document media storage updated. Active provider: {backend.upper()}.", "success")
        return _storage_redirect()

    if action == "sync_local_documents_to_active_cloud":
        active_backend = str(current_app.config.get("DOCUMENT_STORAGE", "local")).strip().lower()
        if active_backend not in {"azure", "aws", "gcp"}:
            flash("Active provider must be a cloud backend (AWS, Azure, or GCP) to run sync.", "error")
            return _storage_redirect()

        local_docs = CustomerDocument.query.filter_by(storage_backend="local").all()
        if not local_docs:
            flash("No local documents found to sync.", "success")
            return _storage_redirect()

        svc = StorageService(current_app._get_current_object())
        synced_count = 0
        skipped_count = 0
        failed_count = 0
        errors = []

        for doc in local_docs:
            local_path = (doc.file_path or "").strip()
            if not local_path:
                skipped_count += 1
                continue

            source = Path(local_path)
            if not source.exists() or not source.is_file():
                skipped_count += 1
                continue

            try:
                with source.open("rb") as f:
                    upload_file = FileStorage(
                        stream=f,
                        filename=(doc.original_filename or source.name),
                        content_type=doc.mime_type or "application/octet-stream",
                    )
                    result = svc.save_document(upload_file, upload_file.filename, doc.customer_id)
            except Exception as exc:
                failed_count += 1
                if len(errors) < 3:
                    errors.append(f"{doc.original_filename}: {exc}")
                continue

            if not result.success:
                failed_count += 1
                if len(errors) < 3:
                    errors.append(f"{doc.original_filename}: {result.error}")
                continue

            doc.stored_filename = result.stored_filename
            doc.blob_url = result.blob_url
            doc.storage_backend = result.storage_backend
            if doc.file_size_bytes is None:
                try:
                    doc.file_size_bytes = int(source.stat().st_size)
                except Exception:
                    pass
            log_history(
                doc.customer_id,
                action="document-storage-sync-to-cloud",
                changes_summary=(
                    f"Document '{doc.original_filename}' moved from local to {result.storage_backend.upper()} storage."
                ),
                tag_name="document",
            )
            synced_count += 1

        if synced_count:
            db.session.commit()

        flash(
            f"Local-to-{active_backend.upper()} sync completed. Synced: {synced_count}, Skipped: {skipped_count}, Failed: {failed_count}.",
            "success" if failed_count == 0 else "error",
        )
        for message in errors:
            flash(f"Sync error: {message}", "error")
        return _storage_redirect()

    if action == "sync_active_cloud_documents_to_local":
        active_backend = str(current_app.config.get("DOCUMENT_STORAGE", "local")).strip().lower()
        if active_backend not in {"azure", "aws", "gcp"}:
            flash("Active provider must be a cloud backend (AWS, Azure, or GCP) to run reverse sync.", "error")
            return _storage_redirect()

        cloud_docs = CustomerDocument.query.filter_by(storage_backend=active_backend).all()
        if not cloud_docs:
            flash(f"No {active_backend.upper()} documents found to sync back to local.", "success")
            return _storage_redirect()

        docs_path = Path(current_app.config.get("DOCUMENTS_FOLDER") or (Path(current_app.root_path).parent / "documents"))
        docs_path.mkdir(parents=True, exist_ok=True)

        synced_count = 0
        skipped_count = 0
        failed_count = 0
        errors = []

        for doc in cloud_docs:
            if not doc.blob_url:
                skipped_count += 1
                continue

            local_name = (doc.stored_filename or secure_filename(doc.original_filename) or f"doc_{doc.id}.bin").strip()
            if not local_name:
                local_name = f"doc_{doc.id}.bin"
            local_dest = docs_path / local_name

            try:
                with urllib.request.urlopen(doc.blob_url, timeout=20) as response:
                    payload = response.read()
                local_dest.write_bytes(payload)
            except Exception as exc:
                failed_count += 1
                if len(errors) < 3:
                    errors.append(f"{doc.original_filename}: {exc}")
                continue

            doc.file_path = str(local_dest)
            doc.storage_backend = "local"
            doc.blob_url = None
            if doc.file_size_bytes is None:
                doc.file_size_bytes = len(payload)
            log_history(
                doc.customer_id,
                action="document-storage-sync-to-local",
                changes_summary=(
                    f"Document '{doc.original_filename}' moved from {active_backend.upper()} to local storage."
                ),
                tag_name="document",
            )
            synced_count += 1

        if synced_count:
            db.session.commit()

        flash(
            f"{active_backend.upper()}-to-local sync completed. Synced: {synced_count}, Skipped: {skipped_count}, Failed: {failed_count}.",
            "success" if failed_count == 0 else "error",
        )
        for message in errors:
            flash(f"Reverse sync error: {message}", "error")
        return _storage_redirect()

    return None
