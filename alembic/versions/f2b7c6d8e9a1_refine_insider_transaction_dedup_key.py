"""refine insider transaction dedup key

Revision ID: f2b7c6d8e9a1
Revises: e1c3a7b9d4f2
Create Date: 2026-04-18 17:25:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f2b7c6d8e9a1"
down_revision: Union[str, None] = "e1c3a7b9d4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        ],
    )
