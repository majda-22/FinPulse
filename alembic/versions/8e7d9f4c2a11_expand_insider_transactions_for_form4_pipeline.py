"""expand insider transactions for form4 pipeline

Revision ID: 8e7d9f4c2a11
Revises: 4f6a2c7b8d91
Create Date: 2026-04-16 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8e7d9f4c2a11"
down_revision: Union[str, None] = "4f6a2c7b8d91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "filings",
        sa.Column("is_insider_signal_scored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("filings", "is_insider_signal_scored", server_default=None)

    op.add_column("insider_transactions", sa.Column("transaction_uid", sa.Text(), nullable=True))
    op.add_column("insider_transactions", sa.Column("accession_number", sa.Text(), nullable=True))
    op.add_column("insider_transactions", sa.Column("cik", sa.String(), nullable=True))
    op.add_column("insider_transactions", sa.Column("ticker", sa.String(), nullable=True))
    op.add_column("insider_transactions", sa.Column("issuer_name", sa.Text(), nullable=True))
    op.add_column(
        "insider_transactions",
        sa.Column("insider_cik", sa.String(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("is_director", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("is_officer", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("is_ten_percent_owner", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("is_other", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("insider_transactions", sa.Column("officer_title", sa.Text(), nullable=True))
    op.add_column(
        "insider_transactions",
        sa.Column("transaction_type_normalized", sa.String(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("shares_owned_after", sa.Numeric(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("ownership_nature", sa.String(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("acquired_disposed_code", sa.String(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("form_type", sa.String(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("filed_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "insider_transactions",
        sa.Column("raw_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.alter_column("insider_transactions", "filing_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column(
        "insider_transactions",
        "total_value",
        new_column_name="transaction_value",
        existing_type=sa.Numeric(),
        existing_nullable=True,
    )

    op.execute(
        """
        UPDATE insider_transactions AS it
        SET accession_number = f.accession_number,
            cik = c.cik,
            ticker = c.ticker,
            issuer_name = c.name,
            form_type = f.form_type,
            filed_at = f.filed_at
        FROM filings AS f
        JOIN companies AS c ON c.id = f.company_id
        WHERE f.id = it.filing_id
        """
    )
    op.execute(
        """
        UPDATE insider_transactions
        SET transaction_type_normalized = CASE upper(transaction_code)
            WHEN 'P' THEN 'open_market_buy'
            WHEN 'S' THEN 'open_market_sell'
            WHEN 'M' THEN 'option_exercise'
            WHEN 'A' THEN 'equity_award'
            WHEN 'F' THEN 'tax_withholding'
            WHEN 'G' THEN 'gift'
            WHEN 'C' THEN 'conversion'
            WHEN 'D' THEN 'issuer_transaction'
            ELSE 'other'
        END
        """
    )
    op.execute(
        """
        UPDATE insider_transactions
        SET ownership_nature = 'direct'
        WHERE ownership_nature IS NULL
        """
    )
    op.execute(
        """
        UPDATE insider_transactions
        SET transaction_uid = md5(
            concat_ws(
                '|',
                coalesce(accession_number, ''),
                coalesce(insider_name, ''),
                coalesce(to_char(transaction_date, 'YYYY-MM-DD'), ''),
                coalesce(transaction_code, ''),
                coalesce(shares::text, ''),
                coalesce(price_per_share::text, ''),
                coalesce(ownership_nature, ''),
                coalesce(acquired_disposed_code, ''),
                coalesce(is_derivative::text, '')
            )
        )
        """
    )

    op.alter_column("insider_transactions", "transaction_uid", nullable=False)
    op.alter_column("insider_transactions", "accession_number", nullable=False)
    op.alter_column("insider_transactions", "cik", nullable=False)
    op.alter_column("insider_transactions", "transaction_type_normalized", nullable=False)
    op.alter_column("insider_transactions", "form_type", nullable=False)

    op.alter_column("insider_transactions", "is_director", server_default=None)
    op.alter_column("insider_transactions", "is_officer", server_default=None)
    op.alter_column("insider_transactions", "is_ten_percent_owner", server_default=None)
    op.alter_column("insider_transactions", "is_other", server_default=None)

    op.drop_constraint("uq_insider_transaction_dedup", "insider_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_insider_transaction_uid",
        "insider_transactions",
        ["transaction_uid"],
    )
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
    op.create_index(
        "idx_insider_company_type",
        "insider_transactions",
        ["company_id", "transaction_type_normalized", "transaction_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_insider_company_type", table_name="insider_transactions")
    op.drop_constraint("uq_insider_transaction_uid", "insider_transactions", type_="unique")
    op.drop_constraint("uq_insider_transaction_dedup", "insider_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_insider_transaction_dedup",
        "insider_transactions",
        ["company_id", "insider_name", "transaction_date", "transaction_code", "shares", "price_per_share"],
    )

    op.alter_column(
        "insider_transactions",
        "transaction_value",
        new_column_name="total_value",
        existing_type=sa.Numeric(),
        existing_nullable=True,
    )
    op.alter_column("insider_transactions", "filing_id", existing_type=sa.Integer(), nullable=False)

    op.drop_column("insider_transactions", "raw_detail")
    op.drop_column("insider_transactions", "source_url")
    op.drop_column("insider_transactions", "filed_at")
    op.drop_column("insider_transactions", "form_type")
    op.drop_column("insider_transactions", "acquired_disposed_code")
    op.drop_column("insider_transactions", "ownership_nature")
    op.drop_column("insider_transactions", "shares_owned_after")
    op.drop_column("insider_transactions", "transaction_type_normalized")
    op.drop_column("insider_transactions", "officer_title")
    op.drop_column("insider_transactions", "is_other")
    op.drop_column("insider_transactions", "is_ten_percent_owner")
    op.drop_column("insider_transactions", "is_officer")
    op.drop_column("insider_transactions", "is_director")
    op.drop_column("insider_transactions", "insider_cik")
    op.drop_column("insider_transactions", "issuer_name")
    op.drop_column("insider_transactions", "ticker")
    op.drop_column("insider_transactions", "cik")
    op.drop_column("insider_transactions", "accession_number")
    op.drop_column("insider_transactions", "transaction_uid")

    op.drop_column("filings", "is_insider_signal_scored")
