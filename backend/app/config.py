from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Ambifo CRM API"
    database_url: str = (
        "postgresql+psycopg2://crm_app:StrongPassword123@localhost:5432/ambifo_crm"
    )
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    engine_url: str = "http://127.0.0.1:8081"
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_mail_from: str | None = None

    public_base_url: str = "http://127.0.0.1:8000"
    email_csv_dir: str = "storage/email_csv"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()