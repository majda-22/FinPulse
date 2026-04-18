from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Float, ForeignKey, Integer, JSON, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


EMBEDDING_ID_TYPE = BigInteger().with_variant(Integer, "sqlite")
EMBEDDING_VECTOR_TYPE = JSON().with_variant(Vector(1024), "postgresql")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("filing_section_id", "chunk_idx", name="uq_embeddings_section_chunk"),
    )

    id: Mapped[int] = mapped_column(EMBEDDING_ID_TYPE, primary_key=True, autoincrement=True)
    filing_section_id: Mapped[int] = mapped_column(
        ForeignKey("filing_sections.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"),
        nullable=False,
    )

    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EMBEDDING_VECTOR_TYPE, nullable=False)

    provider: Mapped[str] = mapped_column(String, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)

    reconstruction_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
