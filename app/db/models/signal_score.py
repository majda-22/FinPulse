from sqlalchemy import Boolean, ForeignKey, Float, JSON, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SIGNAL_SCORE_DETAIL_TYPE = JSON().with_variant(JSONB, "postgresql")


class SignalScore(Base):
    __tablename__ = "signal_scores"
    __table_args__ = (
        UniqueConstraint("filing_id", "signal_name", name="uq_signal_scores_filing_signal_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    signal_name: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict | list | None] = mapped_column(SIGNAL_SCORE_DETAIL_TYPE, nullable=True)

    rlds: Mapped[float | None] = mapped_column(Float, nullable=True)
    gce: Mapped[float | None] = mapped_column(Float, nullable=True)
    ita: Mapped[float | None] = mapped_column(Float, nullable=True)

    convergence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    convergence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)

    computed_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
