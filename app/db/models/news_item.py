from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


NEWS_ITEM_JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "dedupe_hash",
            name="uq_news_items_company_dedupe_hash",
        ),
        Index("idx_news_items_company_published_at", "company_id", "published_at"),
        Index("idx_news_items_ticker_published_at", "ticker", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    publisher: Mapped[Optional[str]] = mapped_column(String)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sentiment_label: Mapped[Optional[str]] = mapped_column(String)
    raw_json: Mapped[Optional[dict]] = mapped_column(NEWS_ITEM_JSON_TYPE)
