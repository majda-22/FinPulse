"""create news items table

Revision ID: c8f4b2e1d9a7
Revises: 1a3c5e7b9d22
Create Date: 2026-04-18 11:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c8f4b2e1d9a7"
down_revision: Union[str, None] = "1a3c5e7b9d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEWS_ITEM_JSON_TYPE = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dedupe_hash", sa.String(length=64), nullable=False),
        sa.Column("sentiment_label", sa.String(), nullable=True),
        sa.Column("raw_json", NEWS_ITEM_JSON_TYPE, nullable=True),
        sa.UniqueConstraint(
            "company_id",
            "dedupe_hash",
            name="uq_news_items_company_dedupe_hash",
        ),
    )
    op.create_index(
        "idx_news_items_company_published_at",
        "news_items",
        ["company_id", "published_at"],
    )
    op.create_index(
        "idx_news_items_ticker_published_at",
        "news_items",
        ["ticker", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_news_items_ticker_published_at", table_name="news_items")
    op.drop_index("idx_news_items_company_published_at", table_name="news_items")
    op.drop_table("news_items")
