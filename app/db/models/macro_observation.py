from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "observation_date",
            "provider",
            name="uq_macro_observations_series_date_provider",
        ),
        Index(
            "idx_macro_observations_series_date",
            "series_id",
            "observation_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[str] = mapped_column(String, nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    provider: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    frequency: Mapped[str | None] = mapped_column(String)
    units: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(Text)
