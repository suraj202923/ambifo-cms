"""
StorageService: abstract file storage for customer documents.
Supports local filesystem, Azure Blob Storage, AWS S3, and GCP Cloud Storage.
Configure via appsettings.json Storage.Backend ("local" | "azure" | "aws" | "gcp").
"""

import json
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename


class StorageResult:
    def __init__(self, success, file_path=None, blob_url=None, stored_filename=None,
                 storage_backend="local", error=None):
        self.success = success
        self.file_path = file_path
        self.blob_url = blob_url
        self.stored_filename = stored_filename
        self.storage_backend = storage_backend
        self.error = error


class StorageService:
    def __init__(self, app):
        self.app = app
        self.backend = str(app.config.get("DOCUMENT_STORAGE", "local")).strip().lower()

    def save_document(self, file_obj, original_filename, customer_id):
        """Save file_obj to the configured backend. Returns StorageResult."""
        safe_name = secure_filename(original_filename)
        unique_name = f"cust{customer_id}_{uuid.uuid4().hex[:10]}_{safe_name}"

        if self.backend == "azure":
            return self._save_azure(file_obj, unique_name)
        elif self.backend == "aws":
            return self._save_aws(file_obj, unique_name)
        elif self.backend == "gcp":
            return self._save_gcp(file_obj, unique_name)
        return self._save_local(file_obj, unique_name)

    # ── Local ──────────────────────────────────────────────────────────────────

    def _save_local(self, file_obj, filename):
        try:
            docs_path = Path(self.app.config["DOCUMENTS_FOLDER"])
            docs_path.mkdir(parents=True, exist_ok=True)
            dest = docs_path / filename
            file_obj.save(str(dest))
            return StorageResult(
                success=True,
                file_path=str(dest),
                stored_filename=filename,
                storage_backend="local",
            )
        except Exception as exc:
            return StorageResult(success=False, error=str(exc), storage_backend="local")

    # ── Azure Blob ─────────────────────────────────────────────────────────────

    def _save_azure(self, file_obj, filename):
        try:
            from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
        except ImportError:
            return StorageResult(
                success=False,
                error="azure-storage-blob is not installed. Run: pip install azure-storage-blob",
                storage_backend="azure",
            )
        try:
            conn_str = self.app.config.get("AZURE_CONNECTION_STRING", "")
            container = self.app.config.get("AZURE_CONTAINER_NAME", "ambifo-documents")
            if not conn_str:
                return StorageResult(
                    success=False,
                    error="Azure connection string is not configured (Storage.Azure.ConnectionString).",
                    storage_backend="azure",
                )
            client = BlobServiceClient.from_connection_string(conn_str)
            blob_client = client.get_blob_client(container=container, blob=filename)
            file_obj.seek(0)
            blob_client.upload_blob(file_obj.read(), overwrite=True)
            return StorageResult(
                success=True,
                blob_url=blob_client.url,
                stored_filename=filename,
                storage_backend="azure",
            )
        except Exception as exc:
            return StorageResult(success=False, error=str(exc), storage_backend="azure")

    # ── AWS S3 ─────────────────────────────────────────────────────────────────

    def _save_aws(self, file_obj, filename):
        try:
            import boto3  # noqa: PLC0415
        except ImportError:
            return StorageResult(
                success=False,
                error="boto3 is not installed. Run: pip install boto3",
                storage_backend="aws",
            )
        try:
            access_key = self.app.config.get("AWS_ACCESS_KEY_ID", "")
            secret_key = self.app.config.get("AWS_SECRET_ACCESS_KEY", "")
            bucket = self.app.config.get("AWS_S3_BUCKET", "")
            region = self.app.config.get("AWS_S3_REGION", "us-east-1")
            if not access_key or not bucket:
                return StorageResult(
                    success=False,
                    error="AWS credentials or bucket not configured (Storage.AWS).",
                    storage_backend="aws",
                )
            s3 = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
            file_obj.seek(0)
            s3.upload_fileobj(file_obj, bucket, filename)
            blob_url = f"https://{bucket}.s3.{region}.amazonaws.com/{filename}"
            return StorageResult(
                success=True,
                blob_url=blob_url,
                stored_filename=filename,
                storage_backend="aws",
            )
        except Exception as exc:
            return StorageResult(success=False, error=str(exc), storage_backend="aws")

    # ── GCP Cloud Storage ─────────────────────────────────────────────────────

    def _save_gcp(self, file_obj, filename):
        try:
            from google.cloud import storage  # noqa: PLC0415
            from google.oauth2 import service_account  # noqa: PLC0415
        except ImportError:
            return StorageResult(
                success=False,
                error="google-cloud-storage is not installed. Run: pip install google-cloud-storage",
                storage_backend="gcp",
            )

        try:
            bucket_name = (self.app.config.get("GCP_BUCKET_NAME", "") or "").strip()
            project_id = (self.app.config.get("GCP_PROJECT_ID", "") or "").strip()
            credentials_json = (self.app.config.get("GCP_CREDENTIALS_JSON", "") or "").strip()

            if not bucket_name:
                return StorageResult(
                    success=False,
                    error="GCP bucket is not configured (Storage.GCP.BucketName).",
                    storage_backend="gcp",
                )

            client = None
            if credentials_json:
                info = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(info)
                client = storage.Client(credentials=credentials, project=project_id or info.get("project_id"))
            else:
                client = storage.Client(project=project_id or None)

            bucket = client.bucket(bucket_name)
            blob = bucket.blob(filename)

            file_obj.seek(0)
            blob.upload_from_file(file_obj)

            blob_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
            return StorageResult(
                success=True,
                blob_url=blob_url,
                stored_filename=filename,
                storage_backend="gcp",
            )
        except Exception as exc:
            return StorageResult(success=False, error=str(exc), storage_backend="gcp")

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete_document(self, doc):
        """Delete a stored document. Accepts a CustomerDocument model instance."""
        if doc.storage_backend == "local" and doc.file_path:
            try:
                path = Path(doc.file_path)
                if path.exists():
                    path.unlink()
            except Exception:
                pass

        elif doc.storage_backend == "azure" and doc.blob_url:
            try:
                from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
                conn_str = self.app.config.get("AZURE_CONNECTION_STRING", "")
                container = self.app.config.get("AZURE_CONTAINER_NAME", "ambifo-documents")
                client = BlobServiceClient.from_connection_string(conn_str)
                blob_name = (doc.stored_filename or doc.blob_url.split("/")[-1])
                client.get_blob_client(container=container, blob=blob_name).delete_blob()
            except Exception:
                pass

        elif doc.storage_backend == "aws" and doc.blob_url:
            try:
                import boto3  # noqa: PLC0415
                bucket = self.app.config.get("AWS_S3_BUCKET", "")
                region = self.app.config.get("AWS_S3_REGION", "us-east-1")
                key = doc.stored_filename or doc.blob_url.split(".amazonaws.com/")[-1]
                s3 = boto3.client(
                    "s3",
                    aws_access_key_id=self.app.config.get("AWS_ACCESS_KEY_ID", ""),
                    aws_secret_access_key=self.app.config.get("AWS_SECRET_ACCESS_KEY", ""),
                    region_name=region,
                )
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass

        elif doc.storage_backend == "gcp" and doc.blob_url:
            try:
                from google.cloud import storage  # noqa: PLC0415
                from google.oauth2 import service_account  # noqa: PLC0415

                bucket_name = (self.app.config.get("GCP_BUCKET_NAME", "") or "").strip()
                credentials_json = (self.app.config.get("GCP_CREDENTIALS_JSON", "") or "").strip()
                project_id = (self.app.config.get("GCP_PROJECT_ID", "") or "").strip()

                if not bucket_name:
                    return

                if credentials_json:
                    info = json.loads(credentials_json)
                    credentials = service_account.Credentials.from_service_account_info(info)
                    client = storage.Client(credentials=credentials, project=project_id or info.get("project_id"))
                else:
                    client = storage.Client(project=project_id or None)

                key = doc.stored_filename or doc.blob_url.split(f"/{bucket_name}/")[-1]
                bucket = client.bucket(bucket_name)
                bucket.blob(key).delete()
            except Exception:
                pass
