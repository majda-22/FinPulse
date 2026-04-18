"""refine xbrl fact business key

Revision ID: 9c6f6a2d1e4b
Revises: 2b8d9a1f6c44
Create Date: 2026-04-15 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9c6f6a2d1e4b"
down_revision: Union[str, None] = "2b8d9a1f6c44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_xbrl_fact_business_key", "xbrl_facts", type_="unique")
    op.create_unique_constraint(
        "uq_xbrl_fact_business_key",
        "xbrl_facts",
        [
            "company_id",
            "taxonomy",
            "concept",
            "period_type",
            "period_start",
            "period_end",
            "unit",
            "form_type",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_xbrl_fact_business_key", "xbrl_facts", type_="unique")
    op.create_unique_constraint(
        "uq_xbrl_fact_business_key",
        "xbrl_facts",
        ["company_id", "taxonomy", "concept", "period_end", "unit"],
    )
