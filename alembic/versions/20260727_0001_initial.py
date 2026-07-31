"""Initial Kalibr Reports schema.

Revision ID: 20260727_0001
Revises:
Create Date: 2026-07-27
"""
from alembic import op

from app.core.database import Base
from app.core import models  # noqa: F401

revision = "20260727_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
