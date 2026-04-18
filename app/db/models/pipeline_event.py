from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


PIPELINE_EVENT_ID_TYPE = BigInteger().with_variant(Integer, "sqlite")
PIPELINE_EVENT_DETAIL_TYPE = JSON().with_variant(JSONB, "postgresql")


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(PIPELINE_EVENT_ID_TYPE, primary_key=True, autoincrement=True)

    filing_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("filings.id", ondelete="SET NULL")
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL")
    )

    # 🔥 THIS IS THE MISSING FIELD
    layer: Mapped[str] = mapped_column(Text, nullable=False)

    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)

    detail: Mapped[Optional[dict]] = mapped_column(PIPELINE_EVENT_DETAIL_TYPE)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    filing = relationship("Filing")
    company = relationship("Company")
