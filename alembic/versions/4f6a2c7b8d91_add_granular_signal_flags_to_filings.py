"""add granular signal flags to filings

Revision ID: 4f6a2c7b8d91
Revises: 9c6f6a2d1e4b
Create Date: 2026-04-16 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4f6a2c7b8d91"
down_revision: Union[str, None] = "9c6f6a2d1e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "filings",
        sa.Column("is_text_signal_scored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "filings",
        sa.Column("is_numeric_signal_scored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "filings",
        sa.Column("is_composite_signal_scored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.alter_column("filings", "is_text_signal_scored", server_default=None)
    op.alter_column("filings", "is_numeric_signal_scored", server_default=None)
    op.alter_column("filings", "is_composite_signal_scored", server_default=None)


def downgrade() -> None:
    op.drop_column("filings", "is_composite_signal_scored")
    op.drop_column("filings", "is_numeric_signal_scored")
    op.drop_column("filings", "is_text_signal_scored")
