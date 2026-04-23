"""add form4 parsed flag to filings

Revision ID: 1a3c5e7b9d22
Revises: 8e7d9f4c2a11
Create Date: 2026-04-16 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a3c5e7b9d22"
down_revision: Union[str, None] = "8e7d9f4c2a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "filings",
        sa.Column("is_form4_parsed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("filings", "is_form4_parsed", server_default=None)


def downgrade() -> None:
    op.drop_column("filings", "is_form4_parsed")
