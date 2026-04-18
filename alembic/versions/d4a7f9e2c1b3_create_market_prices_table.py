"""create market prices table

Revision ID: d4a7f9e2c1b3
Revises: c8f4b2e1d9a7
Create Date: 2026-04-18 12:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a7f9e2c1b3"
down_revision: Union[str, None] = "c8f4b2e1d9a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=True),
        sa.Column("high", sa.Numeric(18, 6), nullable=True),
        sa.Column("low", sa.Numeric(18, 6), nullable=True),
        sa.Column("close", sa.Numeric(18, 6), nullable=True),
        sa.Column("adjusted_close", sa.Numeric(18, 6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "company_id",
            "trading_date",
            "provider",
            name="uq_market_prices_company_date_provider",
        ),
    )
    op.create_index(
        "idx_market_prices_company_trading_date",
        "market_prices",
        ["company_id", "trading_date"],
    )
    op.create_index(
        "idx_market_prices_ticker_trading_date",
        "market_prices",
        ["ticker", "trading_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_market_prices_ticker_trading_date", table_name="market_prices")
    op.drop_index("idx_market_prices_company_trading_date", table_name="market_prices")
    op.drop_table("market_prices")
