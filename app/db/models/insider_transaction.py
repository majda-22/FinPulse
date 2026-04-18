from sqlalchemy import Boolean, Date, ForeignKey, JSON, Numeric, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

INSIDER_RAW_DETAIL_TYPE = JSON().with_variant(JSONB, "postgresql")


class InsiderTransaction(Base):
    __tablename__ = "insider_transactions"
    __table_args__ = (
        UniqueConstraint(
            "transaction_uid",
            name="uq_insider_transaction_uid",
        ),
        UniqueConstraint(
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
            name="uq_insider_transaction_dedup",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"), nullable=True)
    transaction_uid: Mapped[str] = mapped_column(Text, nullable=False)

    accession_number: Mapped[str] = mapped_column(Text, nullable=False)
    cik: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    insider_name: Mapped[str] = mapped_column(Text, nullable=False)
    insider_cik: Mapped[str | None] = mapped_column(String, nullable=True)
    is_director: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_ten_percent_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_other: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    officer_title: Mapped[str | None] = mapped_column(Text, nullable=True)

    transaction_date: Mapped[Date] = mapped_column(Date, nullable=False)
    transaction_code: Mapped[str] = mapped_column(String, nullable=False)
    transaction_type_normalized: Mapped[str] = mapped_column(String, nullable=False)

    shares: Mapped[float] = mapped_column(Numeric, nullable=False)
    price_per_share: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    transaction_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares_owned_after: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    ownership_nature: Mapped[str | None] = mapped_column(String, nullable=True)
    acquired_disposed_code: Mapped[str | None] = mapped_column(String, nullable=True)
    is_derivative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    form_type: Mapped[str] = mapped_column(String, nullable=False, default="4")
    filed_at: Mapped[Date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_detail: Mapped[dict | list | None] = mapped_column(INSIDER_RAW_DETAIL_TYPE, nullable=True)

    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
