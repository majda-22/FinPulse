from sqlalchemy import ForeignKey, SmallInteger, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FilingSection(Base):
    __tablename__ = "filing_sections"
    __table_args__ = (
        UniqueConstraint("filing_id", "section", "sequence_idx", name="uq_filing_sections_filing_section_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    section: Mapped[str] = mapped_column(String, nullable=False)
    sequence_idx: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)