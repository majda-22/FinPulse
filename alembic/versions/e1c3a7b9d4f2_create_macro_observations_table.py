"""create macro observations table

Revision ID: e1c3a7b9d4f2
Revises: d4a7f9e2c1b3
Create Date: 2026-04-18 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1c3a7b9d4f2"
down_revision: Union[str, None] = "d4a7f9e2c1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "macro_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column("units", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "series_id",
            "observation_date",
            "provider",
            name="uq_macro_observations_series_date_provider",
        ),
    )
    op.create_index(
        "idx_macro_observations_series_date",
        "macro_observations",
        ["series_id", "observation_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_macro_observations_series_date", table_name="macro_observations")
    op.drop_table("macro_observations")
