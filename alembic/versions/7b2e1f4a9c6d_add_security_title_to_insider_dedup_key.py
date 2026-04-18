"""add security title to insider transaction dedup key

Revision ID: 7b2e1f4a9c6d
Revises: 3c4d5e6f7a8b
Create Date: 2026-04-18 21:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b2e1f4a9c6d"
down_revision: Union[str, None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insider_transactions",
        sa.Column("security_title", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE insider_transactions
        SET security_title = COALESCE(raw_detail->>'security_title', '')
        WHERE security_title IS NULL
        """
    )
    op.alter_column(
        "insider_transactions",
        "security_title",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
    )
    op.drop_constraint("uq_insider_transaction_dedup", "insider_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_insider_transaction_dedup",
        "insider_transactions",
        [
            "accession_number",
            "insider_name",
            "transaction_date",
            "transaction_code",
            "shares",
            "price_per_share",
            "security_title",
            "ownership_nature",
            "acquired_disposed_code",
            "is_derivative",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_insider_transaction_dedup", "insider_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_insider_transaction_dedup",
        "insider_transactions",
        [
            "accession_number",
            "insider_name",
            "transaction_date",
            "transaction_code",
            "shares",
            "price_per_share",
            "ownership_nature",
            "acquired_disposed_code",
            "is_derivative",
        ],
    )
    op.drop_column("insider_transactions", "security_title")
