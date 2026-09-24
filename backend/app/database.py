from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_column(table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table if it is missing (no-alembic fallback)."""
    with engine.begin() as conn:
        inspector = inspect(conn)
        if table not in inspector.get_table_names():
            return
        names = {c["name"] for c in inspector.get_columns(table)}
        if column not in names:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()