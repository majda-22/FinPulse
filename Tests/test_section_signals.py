from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.embedding
import app.db.models.filing
import app.db.models.filing_section
import app.db.models.pipeline_event
import app.db.models.signal_score

from app.db.models.company import Company
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.models.signal_score import SignalScore
from signals import text_signals
from signals.section_signals import compute_and_store_section_signals, compute_section_drift_signals
from signals.signal_repo import upsert_signal_scores


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
def sample_filings(db_session, sample_company):
    previous = Filing(
        company_id=sample_company.id,
        accession_number="0000320193-24-000123",
        form_type="10-K",
        filed_at=date(2024, 1, 15),
        period_of_report=date(2023, 12, 31),
        fiscal_year=2023,
        raw_s3_key="prev",
        processing_status="embedded",
        is_extracted=True,
        is_embedded=True,
    )
    current = Filing(
        company_id=sample_company.id,
        accession_number="0000320193-25-000079",
        form_type="10-K",
        filed_at=date(2025, 1, 15),
        period_of_report=date(2024, 12, 31),
        fiscal_year=2024,
        raw_s3_key="curr",
        processing_status="embedded",
        is_extracted=True,
        is_embedded=True,
    )
    db_session.add_all([previous, current])
    db_session.flush()
    return previous, current


@pytest.fixture
def sample_sections_and_embeddings(db_session, sample_company, sample_filings):
    previous, current = sample_filings

    section_rows = {}
    texts = {
        previous.id: {
            "risk_factors": "supply chain demand inflation operations",
            "mda": "operations were mixed and cash needs increased",
        },
        current.id: {
            "risk_factors": "supply chain demand inflation operations",
            "mda": "strong revenue growth improved profitability and momentum",
        },
    }
    vectors = {
        (previous.id, "risk_factors"): [[1.0, 0.0], [0.0, 1.0]],
        (current.id, "risk_factors"): [[0.99, 0.01], [0.01, 0.99]],
        (previous.id, "mda"): [[0.0, 1.0], [0.0, 1.0]],
        (current.id, "mda"): [[1.0, 0.0], [0.8, 0.2]],
    }

    for filing in (previous, current):
        for section_name in ("risk_factors", "mda"):
            section_row = FilingSection(
                filing_id=filing.id,
                company_id=sample_company.id,
                section=section_name,
                sequence_idx=0,
                text=texts[filing.id][section_name],
                extractor_version="1.0.0",
            )
            db_session.add(section_row)
            db_session.flush()
            section_rows[(filing.id, section_name)] = section_row

    for (filing_id, section_name), chunk_vectors in vectors.items():
        section_row = section_rows[(filing_id, section_name)]
        for idx, vector in enumerate(chunk_vectors):
            db_session.add(
                Embedding(
                    filing_section_id=section_row.id,
                    company_id=sample_company.id,
                    filing_id=filing_id,
                    chunk_idx=idx,
                    text=f"{section_name}-chunk-{idx}",
                    embedding=vector,
                    provider="mistral",
                    embedding_model="mistral-embed",
                )
            )

    db_session.flush()
    return previous, current


def test_compute_section_drift_signals_uses_rlds_and_mda_drift(
    db_session,
    sample_sections_and_embeddings,
):
    _, current = sample_sections_and_embeddings

    signals = compute_section_drift_signals(
        db_session,
        current_filing_id=current.id,
    )
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert set(by_name) == {"rlds", "mda_drift"}
    assert by_name["rlds"]["signal_value"] < 0.05
    assert by_name["mda_drift"]["signal_value"] > 0.25
    assert by_name["mda_drift"]["signal_value"] > by_name["rlds"]["signal_value"]
    assert by_name["mda_drift"]["detail"]["comparison_filing_id"] is not None


def test_compute_section_drift_signals_without_previous_returns_not_available(
    db_session,
    sample_company,
):
    current = Filing(
        company_id=sample_company.id,
        accession_number="0000320193-25-000079",
        form_type="10-K",
        filed_at=date(2025, 1, 15),
        period_of_report=date(2024, 12, 31),
        raw_s3_key="curr",
        processing_status="embedded",
        is_extracted=True,
        is_embedded=True,
    )
    db_session.add(current)
    db_session.flush()

    signals = compute_section_drift_signals(db_session, current_filing_id=current.id)

    assert len(signals) == 2
    for signal in signals:
        assert signal["signal_value"] is None
        assert signal["detail"]["availability_reason"] == "no_previous_comparable_filing"


def test_compute_and_store_section_signals_stores_text_sentiment_and_marks_stage(
    db_session,
    sample_sections_and_embeddings,
    monkeypatch,
):
    _, current = sample_sections_and_embeddings
    monkeypatch.setattr(text_signals, "_anchor_embedding", lambda: (1.0, 0.0))
    monkeypatch.setattr(text_signals, "_optimistic_anchor_embedding", lambda: (1.0, 0.0))
    monkeypatch.setattr(text_signals, "_pessimistic_anchor_embedding", lambda: (0.0, 1.0))

    first = compute_and_store_section_signals(current.id, db=db_session)
    second = compute_and_store_section_signals(current.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=current.id).all()
    by_name = {row.signal_name: row for row in rows}

    assert len(first) == 4
    assert len(second) == 4
    assert set(by_name) == {"rlds", "mda_drift", "text_sentiment", "forward_pessimism"}
    assert by_name["text_sentiment"].signal_value > 0.85
    assert by_name["forward_pessimism"].signal_value < 0.20
    assert current.is_text_signal_scored is True
    assert current.processing_status == "text_signal_scored"


def test_upsert_signal_scores_rejects_company_mismatch(db_session, sample_sections_and_embeddings):
    _, current = sample_sections_and_embeddings

    compute_and_store_section_signals(current.id, db=db_session)
    existing = db_session.query(SignalScore).filter_by(
        filing_id=current.id,
        signal_name="rlds",
    ).one()

    with pytest.raises(ValueError, match="already belongs to company_id"):
        upsert_signal_scores(
            db_session,
            [
                {
                    "filing_id": current.id,
                    "company_id": existing.company_id + 999,
                    "signal_name": "rlds",
                    "signal_value": 0.5,
                    "detail": {"bad": True},
                    "model_version": "test",
                }
            ],
        )
