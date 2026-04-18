"""add embeddings table

Revision ID: f0b7f372f975
Revises: 425d135dbfab
Create Date: 2026-04-15 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "f0b7f372f975"
down_revision: Union[str, None] = "425d135dbfab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "embeddings",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("filing_section_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("filing_id", sa.Integer(), nullable=False),
        sa.Column("chunk_idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=1024), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("reconstruction_error", sa.Float(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["filing_id"], ["filings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["filing_section_id"], ["filing_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filing_section_id", "chunk_idx", name="uq_embeddings_section_chunk"),
    )

    op.create_index("idx_embeddings_filing_section", "embeddings", ["filing_section_id"], unique=False)
    op.create_index("idx_embeddings_company", "embeddings", ["company_id"], unique=False)
    op.create_index("idx_embeddings_filing", "embeddings", ["filing_id"], unique=False)
    op.create_index("idx_embeddings_reconstruction", "embeddings", ["reconstruction_error"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_embeddings_reconstruction", table_name="embeddings")
    op.drop_index("idx_embeddings_filing", table_name="embeddings")
    op.drop_index("idx_embeddings_company", table_name="embeddings")
    op.drop_index("idx_embeddings_filing_section", table_name="embeddings")
    op.drop_table("embeddings")
