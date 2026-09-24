"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables are created by Base.metadata.create_all() at startup.
    # This migration marks the baseline so future Alembic heads work.
    # To stamp existing databases: alembic stamp head
    pass


def downgrade() -> None:
    pass
