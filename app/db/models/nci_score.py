from sqlalchemy import Boolean, ForeignKey, Float, Integer, JSON, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NciScore(Base):
    __tablename__ = "nci_scores"
    __table_args__ = (
        UniqueConstraint("company_id", "computed_at", name="uq_nci_company_computed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id", ondelete="SET NULL"), nullable=True)
    signal_score_id: Mapped[int | None] = mapped_column(ForeignKey("signal_scores.id", ondelete="SET NULL"), nullable=True)
    text_source_filing: Mapped[int | None] = mapped_column(ForeignKey("filings.id", ondelete="SET NULL"), nullable=True)
    xbrl_source_filing: Mapped[int | None] = mapped_column(ForeignKey("filings.id", ondelete="SET NULL"), nullable=True)

    event_type: Mapped[str] = mapped_column(String, nullable=False, default="annual_anchor")
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    nci_global: Mapped[float] = mapped_column(Float, nullable=False)
    nci_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    nci_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    convergence_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    layers_elevated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_fresh: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    staleness_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    top_anomalous_paragraphs: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    text_staleness_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    signal_text: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_mda: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_pessimism: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_fundamental: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_earnings: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_anomaly: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_insider: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_market: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)

    computed_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
