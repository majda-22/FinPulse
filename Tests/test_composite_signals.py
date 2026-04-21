from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.nci_score
import app.db.models.pipeline_event
import app.db.models.signal_score

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.nci_score import NciScore
from app.db.models.pipeline_event import PipelineEvent
from app.db.models.signal_score import SignalScore
from signals.composite_repo import load_signal_rows_by_name, load_signal_values_by_name
from signals.composite_signals import compute_and_store_composite_signals, compute_composite_signals
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
def sample_filing(db_session):
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(company)
    db_session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-25-000079",
        form_type="10-K",
        filed_at=date(2026, 1, 31),
        period_of_report=date(2025, 9, 30),
        raw_s3_key="aapl-2025-10k",
        is_signal_scored=False,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _signal_row(
    filing: Filing,
    signal_name: str,
    signal_value: float | None,
    *,
    kind: str,
    confidence: float = 0.8,
    model_version: str = "stable",
) -> dict:
    return {
        "filing_id": filing.id,
        "company_id": filing.company_id,
        "signal_name": signal_name,
        "signal_value": signal_value,
        "detail": {
            "signal_category": kind,
            "signal_role": "base",
            "confidence": confidence,
            "coverage_ratio": 1.0,
            "history_depth": 4,
        },
        "model_version": model_version,
    }


@pytest.fixture
def stored_low_level_signals(db_session, sample_filing):
    rows = [
        _signal_row(sample_filing, "rlds", 0.70, kind="text"),
        _signal_row(sample_filing, "mda_drift", 0.40, kind="text"),
        _signal_row(sample_filing, "forward_pessimism", 0.60, kind="text"),
        _signal_row(sample_filing, "text_sentiment", 0.90, kind="text"),
        _signal_row(sample_filing, "fundamental_deterioration", 0.80, kind="numbers"),
        _signal_row(sample_filing, "balance_sheet_stress", 0.30, kind="numbers"),
        _signal_row(sample_filing, "revenue_growth_deceleration", 0.50, kind="numbers"),
        _signal_row(sample_filing, "earnings_quality", 0.20, kind="numbers"),
        _signal_row(sample_filing, "numeric_anomaly", 0.10, kind="numbers"),
        _signal_row(sample_filing, "ita", 0.80, kind="behavior"),
        _signal_row(sample_filing, "insider_concentration", 0.75, kind="behavior"),
        _signal_row(sample_filing, "insider_signal", 0.785, kind="behavior"),
        _signal_row(sample_filing, "market_signal", 0.65, kind="market"),
        _signal_row(sample_filing, "sentiment_signal", 0.55, kind="sentiment"),
    ]
    upsert_signal_scores(db_session, rows)
    return rows


def test_load_signal_values_by_name_supports_latest_lookup(db_session, stored_low_level_signals, sample_filing):
    values = load_signal_values_by_name(db_session, filing_id=sample_filing.id)
    rows = load_signal_rows_by_name(db_session, filing_id=sample_filing.id)

    assert values["rlds"] == pytest.approx(0.70)
    assert rows["insider_signal"].signal_value == pytest.approx(0.785)


def test_compute_composite_signals_uses_expected_nci_formula(
    db_session,
    stored_low_level_signals,
    sample_filing,
):
    signals = compute_composite_signals(db_session, filing_id=sample_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    expected_divergence = abs(0.60 - 0.80)
    expected_nci_raw = (
        0.20 * 0.70
        + 0.08 * 0.40
        + 0.07 * 0.60
        + 0.18 * 0.80
        + 0.07 * 0.30
        + 0.05 * 0.50
        + 0.05 * 0.20
        + 0.10 * 0.785
        + 0.10 * 0.65
        + 0.10 * 0.55
    )
    expected_nci = min(1.0, expected_nci_raw + 0.20)

    assert set(by_name) == {
        "narrative_numeric_divergence",
        "convergence_signal",
        "nci_global",
        "composite_filing_risk",
    }
    assert by_name["narrative_numeric_divergence"]["signal_value"] == pytest.approx(expected_divergence)
    assert by_name["narrative_numeric_divergence"]["detail"]["tone_basis"] == "forward_pessimism"
    assert by_name["narrative_numeric_divergence"]["detail"]["forward_pessimism"] == pytest.approx(0.60)
    assert by_name["narrative_numeric_divergence"]["detail"]["numeric_risk"] == pytest.approx(0.80)
    assert by_name["convergence_signal"]["signal_value"] == pytest.approx(0.20)
    assert by_name["convergence_signal"]["detail"]["tier"] == "full"
    assert by_name["nci_global"]["signal_value"] == pytest.approx(expected_nci)
    assert by_name["nci_global"]["detail"]["normalization_method"] == "identity"
    assert by_name["composite_filing_risk"]["signal_value"] == pytest.approx(expected_nci)
    assert by_name["composite_filing_risk"]["detail"]["alias_of"] == "nci_global"


def test_compute_composite_signals_with_low_coverage_returns_not_available(db_session, sample_filing):
    upsert_signal_scores(
        db_session,
        [
            _signal_row(sample_filing, "mda_drift", 0.4, kind="text"),
            _signal_row(sample_filing, "text_sentiment", 0.8, kind="text"),
            _signal_row(sample_filing, "balance_sheet_stress", 0.7, kind="numbers"),
        ],
    )

    signals = compute_composite_signals(db_session, filing_id=sample_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}

    assert by_name["narrative_numeric_divergence"]["signal_value"] is None
    assert by_name["nci_global"]["signal_value"] is None
    assert by_name["nci_global"]["detail"]["availability_reason"] == "insufficient_signal_coverage"
    assert by_name["nci_global"]["detail"]["coverage_ratio"] == pytest.approx(2 / 10)
    assert by_name["nci_global"]["detail"]["confidence_label"] == "low"
    assert by_name["nci_global"]["detail"]["available_signal_count"] == 2
    assert by_name["nci_global"]["detail"]["missing_critical_layers"] == ["behavior"]


def test_compute_composite_signals_carries_forward_recent_missing_inputs(
    db_session,
    sample_filing,
    stored_low_level_signals,
):
    previous = Filing(
        company_id=sample_filing.company_id,
        accession_number="0000320193-24-000001",
        form_type="10-Q",
        filed_at=date(2025, 10, 31),
        period_of_report=date(2025, 9, 30),
        raw_s3_key="aapl-2025-q3",
        is_signal_scored=True,
    )
    db_session.add(previous)
    db_session.flush()

    upsert_signal_scores(
        db_session,
        [
            {
                "filing_id": sample_filing.id,
                "company_id": sample_filing.company_id,
                "signal_name": "market_signal",
                "signal_value": None,
                "detail": {
                    "availability_reason": "missing_market_prices",
                    "signal_category": "market",
                    "signal_role": "composite_layer",
                    "coverage_ratio": 0.0,
                    "confidence": 0.0,
                },
                "model_version": "test",
            },
            {
                "filing_id": sample_filing.id,
                "company_id": sample_filing.company_id,
                "signal_name": "sentiment_signal",
                "signal_value": None,
                "detail": {
                    "availability_reason": "missing_news_items",
                    "signal_category": "sentiment",
                    "signal_role": "composite_layer",
                    "coverage_ratio": 0.0,
                    "confidence": 0.0,
                },
                "model_version": "test",
            },
            _signal_row(previous, "market_signal", 0.80, kind="market"),
            _signal_row(previous, "sentiment_signal", 0.50, kind="sentiment"),
        ],
    )

    signals = compute_composite_signals(db_session, filing_id=sample_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}
    nci_detail = by_name["nci_global"]["detail"]

    assert nci_detail["effective_inputs"]["market_signal"] == pytest.approx(0.76)
    assert nci_detail["effective_inputs"]["sentiment_signal"] == pytest.approx(0.475)
    assert nci_detail["carried_forward_inputs"]["market_signal"]["source_filing_id"] == previous.id
    assert nci_detail["carried_forward_inputs"]["market_signal"]["staleness_penalty"] == pytest.approx(0.95)
    assert nci_detail["carried_forward_inputs"]["sentiment_signal"]["adjusted_value"] == pytest.approx(0.475)
    assert by_name["convergence_signal"]["detail"]["layer_scores"]["market"] == pytest.approx(0.76)


def test_compute_composite_signals_keeps_missing_sentiment_missing(db_session, sample_filing, stored_low_level_signals):
    upsert_signal_scores(
        db_session,
        [
            {
                "filing_id": sample_filing.id,
                "company_id": sample_filing.company_id,
                "signal_name": "sentiment_signal",
                "signal_value": None,
                "detail": {
                    "availability_reason": "missing_news_items",
                    "signal_category": "sentiment",
                    "signal_role": "composite_layer",
                    "coverage_ratio": 0.0,
                    "confidence": 0.0,
                },
                "model_version": "test",
            },
        ],
    )

    signals = compute_composite_signals(db_session, filing_id=sample_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}
    nci_detail = by_name["nci_global"]["detail"]

    expected = (
        (
            (0.20 * 0.70)
            + (0.08 * 0.40)
            + (0.07 * 0.60)
            + (0.18 * 0.80)
            + (0.07 * 0.30)
            + (0.05 * 0.50)
            + (0.05 * 0.20)
            + (0.10 * 0.785)
            + (0.10 * 0.65)
        )
        / 0.90
    ) + 0.15

    assert by_name["nci_global"]["signal_value"] == pytest.approx(expected)
    assert nci_detail["coverage_ratio"] == pytest.approx(9 / 10)
    assert "sentiment_signal" not in nci_detail["effective_inputs"]
    assert nci_detail["missing_signal_names"] == ["sentiment_signal"]


def test_compute_composite_signals_downgrades_confidence_when_critical_layer_is_missing(
    db_session,
    sample_filing,
    stored_low_level_signals,
):
    upsert_signal_scores(
        db_session,
        [
            {
                "filing_id": sample_filing.id,
                "company_id": sample_filing.company_id,
                "signal_name": "insider_signal",
                "signal_value": None,
                "detail": {
                    "availability_reason": "no_insider_transactions",
                    "signal_category": "behavior",
                    "signal_role": "composite_layer",
                    "coverage_ratio": 0.0,
                    "confidence": 0.0,
                },
                "model_version": "test",
            },
        ],
    )

    signals = compute_composite_signals(db_session, filing_id=sample_filing.id)
    by_name = {signal["signal_name"]: signal for signal in signals}
    nci_detail = by_name["nci_global"]["detail"]

    assert by_name["nci_global"]["signal_value"] is not None
    assert nci_detail["coverage_ratio"] == pytest.approx(9 / 10)
    assert nci_detail["confidence_label"] == "medium"
    assert nci_detail["missing_critical_layers"] == ["behavior"]


def test_compute_and_store_composite_signals_upserts_nci_and_marks_complete(
    db_session,
    stored_low_level_signals,
    sample_filing,
):
    sample_filing.is_text_signal_scored = True
    sample_filing.is_numeric_signal_scored = True
    sample_filing.is_insider_signal_scored = True

    first = compute_and_store_composite_signals(sample_filing.id, db=db_session)
    second = compute_and_store_composite_signals(sample_filing.id, db=db_session)

    rows = db_session.query(SignalScore).filter_by(filing_id=sample_filing.id).all()
    nci_rows = db_session.query(NciScore).filter_by(
        company_id=sample_filing.company_id,
        filing_id=sample_filing.id,
    ).all()
    events = db_session.query(PipelineEvent).filter_by(
        filing_id=sample_filing.id,
        event_type="composite_scored",
    ).all()

    stored_names = {row.signal_name for row in rows}

    assert len(first) == 4
    assert len(second) == 4
    assert {"nci_global", "composite_filing_risk", "convergence_signal", "narrative_numeric_divergence"} <= stored_names
    assert len(nci_rows) == 1
    assert nci_rows[0].event_type == "annual_anchor"
    assert nci_rows[0].convergence_tier == "full"
    assert nci_rows[0].coverage_ratio == pytest.approx(1.0)
    assert nci_rows[0].signal_text == pytest.approx(0.70)
    assert nci_rows[0].signal_market == pytest.approx(0.65)
    assert nci_rows[0].signal_sentiment == pytest.approx(0.55)
    assert sample_filing.is_composite_signal_scored is True
    assert sample_filing.is_signal_scored is True
    assert sample_filing.processing_status == "composite_scored"
    assert len(events) == 2
