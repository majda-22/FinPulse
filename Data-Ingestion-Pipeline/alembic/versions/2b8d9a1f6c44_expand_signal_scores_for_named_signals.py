"""expand signal_scores for named signals

Revision ID: 2b8d9a1f6c44
Revises: f0b7f372f975
Create Date: 2026-04-15 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2b8d9a1f6c44"
down_revision: Union[str, None] = "f0b7f372f975"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("signal_scores", sa.Column("signal_name", sa.String(), nullable=True))
    op.add_column("signal_scores", sa.Column("signal_value", sa.Float(), nullable=True))
    op.add_column("signal_scores", sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.drop_constraint("uq_signal_scores_filing_id", "signal_scores", type_="unique")
    op.create_unique_constraint(
        "uq_signal_scores_filing_signal_name",
        "signal_scores",
        ["filing_id", "signal_name"],
    )
    op.create_index("idx_signal_name", "signal_scores", ["signal_name"], unique=False)
    op.create_index(
        "idx_signal_company_name",
        "signal_scores",
        ["company_id", "signal_name", "computed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_signal_company_name", table_name="signal_scores")
    op.drop_index("idx_signal_name", table_name="signal_scores")
    op.drop_constraint("uq_signal_scores_filing_signal_name", "signal_scores", type_="unique")
    op.create_unique_constraint("uq_signal_scores_filing_id", "signal_scores", ["filing_id"])
    op.drop_column("signal_scores", "detail")
    op.drop_column("signal_scores", "signal_value")
    op.drop_column("signal_scores", "signal_name")
