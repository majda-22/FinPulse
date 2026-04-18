from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.filing_section
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from processing.chunker import chunk_filing, chunk_text


def _make_text(prefix: str, count: int) -> str:
    sentences = []
    for idx in range(1, count + 1):
        sentences.append(
            f"{prefix} sentence {idx} includes enough detail to exercise realistic "
            f"chunk sizing and boundary behavior for filing processing."
        )
    return " ".join(sentences)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_company(db_session):
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def sample_filing(db_session, sample_company):
    filing = Filing(
        company_id=sample_company.id,
        accession_number="0000320193-24-000123",
        form_type="10-K",
        filed_at=date(2024, 1, 15),
        period_of_report=date(2023, 12, 31),
        raw_s3_key="0000320193/10-K/0000320193-24-000123.txt",
        processing_status="extracted",
        is_extracted=True,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


@pytest.fixture
def sample_sections(db_session, sample_company, sample_filing):
    # Insert sections out of desired narrative order to verify stable ordering.
    rows = [
        FilingSection(
            filing_id=sample_filing.id,
            company_id=sample_company.id,
            section="mda",
            sequence_idx=0,
            text=_make_text("Management discussion", 8),
            extractor_version="1.0.0",
        ),
        FilingSection(
            filing_id=sample_filing.id,
            company_id=sample_company.id,
            section="risk_factors",
            sequence_idx=0,
            text=_make_text("Risk factor", 9),
            extractor_version="1.0.0",
        ),
        FilingSection(
            filing_id=sample_filing.id,
            company_id=sample_company.id,
            section="business",
            sequence_idx=0,
            text=_make_text("Business overview", 7),
            extractor_version="1.0.0",
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


class TestChunkText:
    def test_short_text_returns_one_chunk(self):
        text = "Apple designs phones. Services revenue grew. Margins remained strong."
        chunks = chunk_text(text, target_chars=120, max_chars=180, min_chars=40, overlap_chars=0)
        assert chunks == [text]

    def test_long_text_splits_under_max_chars(self):
        text = _make_text("Risk factor", 12)
        chunks = chunk_text(text, target_chars=220, max_chars=260, min_chars=80, overlap_chars=0)

        assert len(chunks) >= 3
        assert all(len(chunk) <= 260 for chunk in chunks)
        assert all(len(chunk) >= 80 for chunk in chunks[:-1])

    def test_overlap_carries_context_forward(self):
        text = " ".join(
            [
                "Sentence one explains the product strategy in detail.",
                "Sentence two explains the key market risks in detail.",
                "Sentence three explains the operating outlook in detail.",
                "Sentence four explains the liquidity position in detail.",
            ]
        )

        chunks = chunk_text(text, target_chars=110, max_chars=130, min_chars=50, overlap_chars=60)

        assert len(chunks) >= 2
        assert "Sentence two" in chunks[0]
        assert "Sentence two" in chunks[1] or "Sentence three" in chunks[1]


class TestChunkFiling:
    def test_chunk_filing_returns_metadata(self, db_session, sample_sections, sample_filing):
        result = chunk_filing(
            sample_filing.id,
            db=db_session,
            target_chars=220,
            max_chars=260,
            min_chars=80,
            overlap_chars=0,
        )

        assert result.filing_id == sample_filing.id
        assert result.accession_number == sample_filing.accession_number
        assert len(result.chunks) >= 6
        assert all(chunk.char_count == len(chunk.text) for chunk in result.chunks)
        assert all(chunk.approx_tokens > 0 for chunk in result.chunks)

    def test_chunk_filing_orders_sections_consistently(self, db_session, sample_sections, sample_filing):
        result = chunk_filing(
            sample_filing.id,
            db=db_session,
            target_chars=220,
            max_chars=260,
            min_chars=80,
            overlap_chars=0,
        )

        sections_in_order = [chunk.section for chunk in result.chunks]
        assert sections_in_order[0] == "business"
        assert "risk_factors" in sections_in_order
        assert sections_in_order.index("risk_factors") < sections_in_order.index("mda")

    def test_chunk_filing_warns_when_not_extracted(self, db_session, sample_company):
        filing = Filing(
            company_id=sample_company.id,
            accession_number="0000320193-24-000124",
            form_type="10-K",
            filed_at=date(2024, 1, 16),
            period_of_report=date(2023, 12, 31),
            raw_s3_key="0000320193/10-K/0000320193-24-000124.txt",
            processing_status="pending",
            is_extracted=False,
        )
        db_session.add(filing)
        db_session.flush()

        result = chunk_filing(filing.id, db=db_session)

        assert "filing_not_marked_extracted" in result.warnings
        assert result.chunks == []

    def test_chunk_filing_not_found_raises(self, db_session):
        with pytest.raises(RuntimeError, match="Filing id=99999 not found"):
            chunk_filing(99999, db=db_session)
