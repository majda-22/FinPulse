"""expand nci scores for multi-layer snapshots

Revision ID: 3c4d5e6f7a8b
Revises: f2b7c6d8e9a1
Create Date: 2026-04-18 19:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, None] = "f2b7c6d8e9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "nci_scores",
        sa.Column("text_source_filing", sa.Integer(), nullable=True),
    )
    op.add_column(
        "nci_scores",
        sa.Column("xbrl_source_filing", sa.Integer(), nullable=True),
    )
    op.add_column(
        "nci_scores",
        sa.Column("event_type", sa.String(), nullable=False, server_default="annual_anchor"),
    )
    op.add_column("nci_scores", sa.Column("fiscal_year", sa.Integer(), nullable=True))
    op.add_column("nci_scores", sa.Column("fiscal_quarter", sa.Integer(), nullable=True))
    op.add_column("nci_scores", sa.Column("convergence_tier", sa.String(), nullable=True))
    op.add_column("nci_scores", sa.Column("layers_elevated", sa.Integer(), nullable=True))
    op.add_column("nci_scores", sa.Column("confidence", sa.String(), nullable=True))
    op.add_column("nci_scores", sa.Column("coverage_ratio", sa.Float(), nullable=True))
    op.add_column("nci_scores", sa.Column("text_staleness_days", sa.Integer(), nullable=True))

    for column_name in (
        "signal_text",
        "signal_mda",
        "signal_pessimism",
        "signal_fundamental",
        "signal_balance",
        "signal_growth",
        "signal_earnings",
        "signal_anomaly",
        "signal_insider",
        "signal_market",
        "signal_sentiment",
    ):
        op.add_column("nci_scores", sa.Column(column_name, sa.Float(), nullable=True))

    op.create_foreign_key(
        "fk_nci_scores_text_source_filing",
        "nci_scores",
        "filings",
        ["text_source_filing"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_nci_scores_xbrl_source_filing",
        "nci_scores",
        "filings",
        ["xbrl_source_filing"],
        ["id"],
        ondelete="SET NULL",
    )

    op.alter_column("nci_scores", "event_type", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_nci_scores_xbrl_source_filing", "nci_scores", type_="foreignkey")
    op.drop_constraint("fk_nci_scores_text_source_filing", "nci_scores", type_="foreignkey")

    for column_name in (
        "signal_sentiment",
        "signal_market",
        "signal_insider",
        "signal_anomaly",
        "signal_earnings",
        "signal_growth",
        "signal_balance",
        "signal_fundamental",
        "signal_pessimism",
        "signal_mda",
        "signal_text",
        "text_staleness_days",
        "coverage_ratio",
        "confidence",
        "layers_elevated",
        "convergence_tier",
        "fiscal_quarter",
        "fiscal_year",
        "event_type",
        "xbrl_source_filing",
        "text_source_filing",
    ):
        op.drop_column("nci_scores", column_name)
