from sqlalchemy import Date, ForeignKey, Integer, Numeric, SmallInteger, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class XbrlFact(Base):
    __tablename__ = "xbrl_facts"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "taxonomy",
            "concept",
            "period_type",
            "period_start",
            "period_end",
            "unit",
            "form_type",
            name="uq_xbrl_fact_business_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id", ondelete="SET NULL"), nullable=True)

    taxonomy: Mapped[str] = mapped_column(String, nullable=False, default="us-gaap")
    concept: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    decimals: Mapped[str | None] = mapped_column(String, nullable=True)

    period_type: Mapped[str | None] = mapped_column(String, nullable=True)
    period_start: Mapped[Date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[Date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    form_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
