from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from .config import settings
from .database import Base, SessionLocal, engine, ensure_column
from .routers import (
    admin,
    ai,
    auth,
    config,
    customers,
    dashboard,
    diagrams,
    documents,
    email,
    gathering,
    imports,
    leads,
    meetings,
)
from .schemas.dashboard import DashboardOut  # noqa: F401  (register response models)

limiter = Limiter(key_func=get_remote_address)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Serialize startup across worker processes with a Postgres advisory lock.
    # Without this, multi-worker uvicorn (see deploy/nginx) can race create_all,
    # ALTER TABLE and seeding on a fresh database (duplicate-key / DDL errors).
    lock_conn = engine.connect()
    try:
        lock_conn.execute(text("SELECT pg_advisory_lock(746201)"))
    except Exception:  # noqa: BLE001  (non-Postgres DB or not reachable yet)
        lock_conn.close()
        lock_conn = None
    try:
        Base.metadata.create_all(bind=engine)
        ensure_column("customer_diagrams", "aws_calculator_link", "VARCHAR(500)")
        ensure_column("customers", "designation", "VARCHAR(120)")
        db = SessionLocal()
        try:
            seed_lookups(db)
            from .routers.email import seed_default_templates
            seed_default_templates(db)
            from .security import ensure_default_admin
            ensure_default_admin(db)
            from .services.email_worker import normalize_pending
            normalize_pending(db)
        finally:
            db.close()
    finally:
        if lock_conn is not None:
            try:
                lock_conn.execute(text("SELECT pg_advisory_unlock(746201)"))
            finally:
                lock_conn.close()
    yield


def seed_lookups(db) -> None:
    from .models.crm import (
        OpportunityCloudOperator,
        OpportunitySegment,
        OpportunityStatus,
        OpportunityUpdateTag,
    )

    if db.query(OpportunityStatus).count() == 0:
        defaults = [
            ("New", "#3b82f6"),
            ("Qualified", "#8b5cf6"),
            ("Proposal", "#f59e0b"),
            ("Negotiation", "#06b6d4"),
            ("Won", "#10b981"),
            ("Lost", "#ef4444"),
        ]
        for name, color in defaults:
            db.add(OpportunityStatus(name=name, color=color))

    if db.query(OpportunitySegment).count() == 0:
        for name in ["Enterprise", "SMB", "Mid-Market", "Startup"]:
            db.add(OpportunitySegment(name=name, credit_basis_mrr=True))

    if db.query(OpportunityCloudOperator).count() == 0:
        for name in ["AWS", "Azure", "GCP", "Private Cloud", "Hybrid"]:
            db.add(OpportunityCloudOperator(name=name))

    if db.query(OpportunityUpdateTag).count() == 0:
        for name, color in [
            ("update", "#3b82f6"),
            ("important", "#ef4444"),
            ("note", "#6b7280"),
            ("meeting", "#10b981"),
        ]:
            db.add(OpportunityUpdateTag(name=name, color=color))

    db.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(config.router)
    app.include_router(customers.router)
    app.include_router(leads.router)
    app.include_router(dashboard.router)
    app.include_router(imports.router)
    app.include_router(email.router)
    app.include_router(email.public_router)
    app.include_router(documents.router)
    app.include_router(diagrams.router)
    app.include_router(ai.router)
    app.include_router(meetings.router)
    app.include_router(meetings.public_router)
    app.include_router(gathering.router)
    app.include_router(gathering.public_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/engine/health")
    def engine_health():
        from .services.engine_client import engine_client
        return {"engine_ok": engine_client.health()}

    return app


app = create_app()