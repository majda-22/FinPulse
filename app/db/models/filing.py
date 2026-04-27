from sqlalchemy import Boolean, Date, ForeignKey, Integer, SmallInteger, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)   
    company = relationship("Company")
    accession_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    form_type: Mapped[str] = mapped_column(String, nullable=False)
    filed_at: Mapped[Date] = mapped_column(Date, nullable=False)
    period_of_report: Mapped[Date | None] = mapped_column(Date, nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_quarter: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    raw_s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    raw_size_bytes: Mapped[int | None] = mapped_column(nullable=True)

    is_extracted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_form4_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_xbrl_parsed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_embedded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_text_signal_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_numeric_signal_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_insider_signal_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_composite_signal_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_signal_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_anomaly_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    processing_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
