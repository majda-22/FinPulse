from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


MARKET_PRICE_VOLUME_TYPE = BigInteger().with_variant(BigInteger, "postgresql")


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "trading_date",
            "provider",
            name="uq_market_prices_company_date_provider",
        ),
        Index("idx_market_prices_company_trading_date", "company_id", "trading_date"),
        Index("idx_market_prices_ticker_trading_date", "ticker", "trading_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    volume: Mapped[int | None] = mapped_column(MARKET_PRICE_VOLUME_TYPE)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
