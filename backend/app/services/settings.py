from datetime import datetime, timezone
from typing import Any

from ..config import settings as app_settings
from ..models.config_model import SystemSetting


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_setting(db, key: str, default: str = "") -> str:
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if row is None:
        return default
    return row.setting_value


def set_setting(db, key: str, value: Any) -> str:
    normalized = SystemSetting.normalize_value(value)
    row = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
    if row is None:
        row = SystemSetting(setting_key=key, setting_value=normalized, updated_at=now())
        db.add(row)
    else:
        row.setting_value = normalized
        row.updated_at = now()
    db.commit()
    return normalized


def get_smtp_settings(db) -> dict:
    return {
        "smtp_host": get_setting(db, "smtp.host", app_settings.smtp_host or ""),
        "smtp_port": int(get_setting(db, "smtp.port", str(app_settings.smtp_port))),
        "smtp_username": get_setting(db, "smtp.username", app_settings.smtp_username or ""),
        "smtp_password": get_setting(db, "smtp.password", app_settings.smtp_password or ""),
        "smtp_use_tls": get_setting(
            db, "smtp.use_tls", str(app_settings.smtp_use_tls)
        ).lower() in ("true", "1", "yes", "on"),
        "smtp_mail_from": get_setting(db, "smtp.mail_from", app_settings.smtp_mail_from or ""),
    }


def save_smtp_settings(db, data: dict) -> dict:
    for key, value in (data or {}).items():
        if value is None:
            continue
        set_setting(db, f"smtp.{key.replace('smtp_', '', 1)}" if key.startswith("smtp_") else f"smtp.{key}", value)
    return get_smtp_settings(db)


def get_app_base_url(db) -> str:
    default = app_settings.public_base_url or "http://127.0.0.1:8000"
    base = get_setting(db, "app.base_url", default).strip().rstrip("/")
    return base or default


def set_app_base_url(db, value: str) -> str:
    return set_setting(db, "app.base_url", value)