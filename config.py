import json
import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()


def _load_appsettings():
    settings_file = Path(__file__).with_name("appsettings.json")
    if not settings_file.exists():
        return {}

    try:
        with settings_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


APPSETTINGS = _load_appsettings()


def _get_json_setting(path, default=None):
    current = APPSETTINGS
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _get_setting(env_key, json_path, default=None):
    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value

    json_value = _get_json_setting(json_path, None)
    if json_value is None:
        return default
    return json_value


def _get_database_setting(env_key, json_path, default=None):
    # Database setup flow writes to appsettings.json at runtime; prioritize that value
    # so saved setup credentials are applied after restart.
    json_value = _get_json_setting(json_path, None)
    if json_value not in (None, ""):
        return json_value

    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value

    return default


def _build_database_url():
    explicit_url = str(_get_database_setting("DATABASE_URL", "Database.Url", "")).strip()
    if explicit_url:
        return explicit_url

    db_host = str(_get_database_setting("POSTGRES_HOST", "Database.Host", "localhost"))
    db_port = str(_get_database_setting("POSTGRES_PORT", "Database.Port", "5432"))
    db_name = str(_get_database_setting("POSTGRES_DB", "Database.Name", "ambifo_crm"))
    db_user = str(_get_database_setting("POSTGRES_USER", "Database.User", "postgres"))
    db_password = quote_plus(str(_get_database_setting("POSTGRES_PASSWORD", "Database.Password", "postgres")))
    ssl_mode = str(_get_database_setting("POSTGRES_SSLMODE", "Database.SSLMode", "prefer"))

    return (
        f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        f"?sslmode={ssl_mode}"
    )


class Config:
    SECRET_KEY = str(_get_setting("SECRET_KEY", "App.SecretKey", "dev-secret-key"))
    SQLALCHEMY_DATABASE_URI = _build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SMTP_HOST = str(_get_setting("SMTP_HOST", "SMTP.Host", ""))
    SMTP_PORT = int(_get_setting("SMTP_PORT", "SMTP.Port", 587))
    SMTP_USERNAME = str(_get_setting("SMTP_USERNAME", "SMTP.Username", ""))
    SMTP_PASSWORD = str(_get_setting("SMTP_PASSWORD", "SMTP.Password", ""))
    SMTP_USE_TLS = str(_get_setting("SMTP_USE_TLS", "SMTP.UseTLS", "true")).lower() == "true"
    MAIL_FROM = str(_get_setting("MAIL_FROM", "SMTP.MailFrom", "noreply@ambifo.com"))

    APP_BASE_URL = str(_get_setting("APP_BASE_URL", "App.BaseUrl", "http://127.0.0.1:5000"))
    UPLOAD_FOLDER = str(_get_setting("UPLOAD_FOLDER", "App.UploadFolder", "uploads"))
    MAX_CONTENT_LENGTH = int(_get_setting("MAX_CONTENT_LENGTH", "App.MaxContentLength", 25 * 1024 * 1024))

    # Document storage
    DOCUMENT_STORAGE = str(_get_setting("DOCUMENT_STORAGE", "Storage.Backend", "local"))
    DOCUMENTS_FOLDER = str(_get_setting("DOCUMENTS_FOLDER", "Storage.DocumentsFolder", "documents"))
    AZURE_CONNECTION_STRING = str(_get_setting("AZURE_CONNECTION_STRING", "Storage.Azure.ConnectionString", ""))
    AZURE_CONTAINER_NAME = str(_get_setting("AZURE_CONTAINER_NAME", "Storage.Azure.ContainerName", "ambifo-documents"))
    AWS_ACCESS_KEY_ID = str(_get_setting("AWS_ACCESS_KEY_ID", "Storage.AWS.AccessKeyId", ""))
    AWS_SECRET_ACCESS_KEY = str(_get_setting("AWS_SECRET_ACCESS_KEY", "Storage.AWS.SecretAccessKey", ""))
    AWS_S3_BUCKET = str(_get_setting("AWS_S3_BUCKET", "Storage.AWS.BucketName", ""))
    AWS_S3_REGION = str(_get_setting("AWS_S3_REGION", "Storage.AWS.Region", "us-east-1"))
    GCP_PROJECT_ID = str(_get_setting("GCP_PROJECT_ID", "Storage.GCP.ProjectId", ""))
    GCP_BUCKET_NAME = str(_get_setting("GCP_BUCKET_NAME", "Storage.GCP.BucketName", ""))
    GCP_CREDENTIALS_JSON = str(_get_setting("GCP_CREDENTIALS_JSON", "Storage.GCP.CredentialsJson", ""))

    TEAMS_TENANT_ID = str(_get_setting("TEAMS_TENANT_ID", "Teams.TenantId", ""))
    TEAMS_CLIENT_ID = str(_get_setting("TEAMS_CLIENT_ID", "Teams.ClientId", ""))
    TEAMS_CLIENT_SECRET = str(_get_setting("TEAMS_CLIENT_SECRET", "Teams.ClientSecret", ""))
    TEAMS_ORGANIZER_ID = str(_get_setting("TEAMS_ORGANIZER_ID", "Teams.OrganizerId", ""))
    TEAMS_DEFAULT_DURATION_MINUTES = int(_get_setting("TEAMS_DEFAULT_DURATION_MINUTES", "Teams.DefaultDurationMinutes", 60))

    DEFAULT_ADMIN_USERNAME = str(_get_setting("DEFAULT_ADMIN_USERNAME", "Auth.DefaultAdminUsername", "admin"))
    DEFAULT_ADMIN_PASSWORD = str(_get_setting("DEFAULT_ADMIN_PASSWORD", "Auth.DefaultAdminPassword", "admin123"))
