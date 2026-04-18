from sqlalchemy import Date, ForeignKey, Numeric, String, Text, TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GuidanceStatement(Base):
    __tablename__ = "guidance_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(String, nullable=True)
    guided_point: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String, nullable=True)
    guidance_period_end: Mapped[Date | None] = mapped_column(Date, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)