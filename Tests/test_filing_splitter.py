"""
Tests/test_filing_splitter.py

Tests for processing/filing_splitter.py.
Uses in-memory SQLite — no Docker required.

Run:
    pytest Tests/test_filing_splitter.py -v
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


from app.db.base import Base
import app.db.models.company          # register models
import app.db.models.filing
import app.db.models.filing_section
import app.db.models.pipeline_event

from app.db.models.company        import Company
from app.db.models.filing         import Filing
from app.db.models.filing_section import FilingSection
from app.db.models.pipeline_event import PipelineEvent

from processing.filing_splitter import (
    _extract_from_html,
    _extract_from_text,
    _looks_like_html,
    _clean_heading_text,
    _join_text,
    split_filing,
    EXTRACTOR_VERSION,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """In-memory SQLite session. No Docker needed."""
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
def sample_filing(db_session, sample_company, tmp_path):
    """Create a filing row pointing to a temp file."""
    # Write a fake raw file
    raw_dir = tmp_path / "0000320193" / "10-K"
    raw_dir.mkdir(parents=True)
    raw_file = raw_dir / "0000320193-24-000123.txt"
    raw_file.write_text(SAMPLE_HTML_10K, encoding="utf-8")

    filing = Filing(
        company_id       = sample_company.id,
        accession_number = "0000320193-24-000123",
        form_type        = "10-K",
        filed_at         = date(2024, 1, 15),
        period_of_report = date(2023, 12, 31),
        raw_s3_key       = f"0000320193/10-K/0000320193-24-000123.txt",
        processing_status = "pending",
        is_extracted     = False,
    )
    db_session.add(filing)
    db_session.flush()
    return filing, tmp_path


# ── Sample filing content ─────────────────────────────────────────────────────

SAMPLE_HTML_10K = """
<html><body>
<p><b>Item 1. Business</b></p>
<p>Apple Inc. designs, manufactures, and markets smartphones, personal computers,
tablets, wearables, and accessories. The Company sells its products worldwide
through its retail and online stores and direct sales force.</p>

<p><b>Item 1A. Risk Factors</b></p>
<p>The following risk factors may materially affect our business, financial condition,
and results of operations. You should consider carefully the risks described below,
together with all of the other information in this Annual Report on Form 10-K.</p>
<p>Global and regional economic conditions could materially adversely affect our
business. Our operations and performance depend significantly on global and regional
economic conditions. Adverse macroeconomic conditions, including slow growth or
recession, high unemployment, currency fluctuations, and credit tightening may
negatively affect our business and financial results.</p>
<p>We face intense competition. The markets for our products and services are highly
competitive and subject to rapid technological change. We may be unable to compete
effectively against competitors who have greater resources.</p>

<p><b>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</b></p>
<p>The following discussion should be read in conjunction with the consolidated
financial statements and accompanying notes. This section contains forward-looking
statements that involve risks and uncertainties.</p>
<p>Net sales increased 2% or $7.7 billion during fiscal 2023 compared to fiscal 2022.
iPhone net sales increased 2% or $3.6 billion during fiscal 2023 compared to
fiscal 2022, driven by higher net sales from the iPhone 14 lineup.</p>
<p>Services revenue reached an all-time record of $85.2 billion, reflecting strong
growth across all our service categories including App Store, Apple Music,
Apple TV+, and iCloud.</p>

<p><b>Item 8. Financial Statements</b></p>
<p>See consolidated financial statements beginning on page F-1.</p>
</body></html>
"""

SAMPLE_TEXT_10K = """
ANNUAL REPORT ON FORM 10-K

ITEM 1A. RISK FACTORS

The following risk factors are important considerations for our business.
Our products face significant competition from established companies.
Macroeconomic conditions may adversely affect demand for our products.
We rely on third-party suppliers for key components and materials.

ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

The following discussion should be read with our financial statements.
Revenue for the fiscal year was $394 billion, an increase of 8 percent.
Operating income increased to $119 billion compared to prior year.
We continue to invest heavily in research and development activities.

ITEM 8. FINANCIAL STATEMENTS

See attached financial statements and accompanying notes.
"""

SAMPLE_TEXT_10K_WITH_TOC = """
TABLE OF CONTENTS

ITEM 1. BUSINESS
ITEM 1A. RISK FACTORS
ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

ITEM 1. BUSINESS

Our business designs and sells products and services across multiple markets.
We operate through retail, online, enterprise, and partner channels worldwide.
We invest in hardware, software, and services ecosystems to support growth.
We depend on supply chain execution, customer demand, and product innovation.

ITEM 1A. RISK FACTORS

Our business faces intense competition across hardware, software, and services.
Macroeconomic weakness, currency volatility, and supply constraints can hurt results.
Cybersecurity incidents, regulatory change, and supplier disruption create material risk.
Consumer demand may soften and international operations may be affected by geopolitics.

ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS

Revenue increased during the year as product demand and services adoption improved.
Operating margin benefited from mix, pricing, and disciplined expense management.
Cash flow remained strong and capital allocation continued through repurchases and dividends.
Management evaluates results in light of market demand, product cycles, and macro conditions.

ITEM 8. FINANCIAL STATEMENTS

See attached financial statements and accompanying notes.
"""

SAMPLE_TEXT_10Q = """
QUARTERLY REPORT ON FORM 10-Q

PART I. FINANCIAL INFORMATION

ITEM 1. FINANCIAL STATEMENTS

See condensed consolidated financial statements and accompanying notes.
These interim statements should be read with the prior annual report.

ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS

Revenue for the quarter was $68.9 million and revenue for the nine-month period was $110.4 million.
Gross profit remained negative while management focused on scaling production and reducing unit costs.
Liquidity continues to be monitored closely and capital raising remains important to operations.

PART II. OTHER INFORMATION

ITEM 1A. RISK FACTORS

Our business remains subject to supply chain, liquidity, and execution risk.
Additional financing may not be available on favorable terms.
Macroeconomic weakness, production delays, supplier concentration, and regulatory scrutiny
could materially affect operations, results of operations, financial condition, and access
to capital. Our ability to execute commercialization plans depends on funding, manufacturing
stability, customer adoption, and the timely resolution of operational bottlenecks.

ITEM 6. EXHIBITS
"""


# ── Utility function tests ────────────────────────────────────────────────────

class TestUtilities:

    def test_looks_like_html_true(self):
        assert _looks_like_html("<html><body>content</body></html>") is True

    def test_looks_like_html_div(self):
        assert _looks_like_html("<div class='section'>text</div>") is True

    def test_looks_like_html_false(self):
        assert _looks_like_html("ITEM 1A. RISK FACTORS\n\nPlain text content here.") is False

    def test_clean_heading_text_collapses_whitespace(self):
        result = _clean_heading_text("  Item   1A.   Risk   Factors  ")
        assert result == "Item 1A. Risk Factors"

    def test_clean_heading_text_strips_nonprintable(self):
        result = _clean_heading_text("Item\x001A\x01Risk")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_join_text_cleans_gaps(self):
        lines  = ["  hello  ", "", "  world  ", "  "]
        result = _join_text(lines)
        assert result == "hello world"

    def test_join_text_empty(self):
        assert _join_text([]) == ""
        assert _join_text(["", "  ", "\t"]) == ""


# ── HTML extraction tests ─────────────────────────────────────────────────────

class TestHTMLExtraction:

    def test_extracts_risk_factors(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        keys = [s.section for s in sections]
        assert "risk_factors" in keys

    def test_extracts_mda(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        keys = [s.section for s in sections]
        assert "mda" in keys

    def test_extracts_business(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        keys = [s.section for s in sections]
        assert "business" in keys

    def test_risk_factors_content(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        rf = next((s for s in sections if s.section == "risk_factors"), None)
        assert rf is not None
        assert "competition" in rf.text.lower() or "economic" in rf.text.lower()

    def test_mda_content(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        mda = next((s for s in sections if s.section == "mda"), None)
        assert mda is not None
        assert len(mda.text) > 100

    def test_section_sequence_idx_starts_at_zero(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        for s in sections:
            assert s.sequence_idx == 0   # only one of each in sample

    def test_empty_html_returns_no_sections(self):
        warnings = []
        sections = _extract_from_html("<html><body></body></html>", "10-K", warnings)
        assert sections == [] or all(s.char_count < 100 for s in sections)

    def test_char_count_matches_text_length(self):
        warnings = []
        sections = _extract_from_html(SAMPLE_HTML_10K, warnings)
        for s in sections:
            assert s.char_count == len(s.text)


# ── Plain-text extraction tests ───────────────────────────────────────────────

class TestTextExtraction:

    def test_extracts_risk_factors_from_text(self):
        warnings = []
        sections = _extract_from_text(SAMPLE_TEXT_10K, warnings)
        keys = [s.section for s in sections]
        assert "risk_factors" in keys

    def test_extracts_mda_from_text(self):
        warnings = []
        sections = _extract_from_text(SAMPLE_TEXT_10K, warnings)
        keys = [s.section for s in sections]
        assert "mda" in keys

    def test_text_risk_factors_content(self):
        warnings = []
        sections = _extract_from_text(SAMPLE_TEXT_10K, warnings)
        rf = next((s for s in sections if s.section == "risk_factors"), None)
        assert rf is not None
        assert len(rf.text) > 50

    def test_no_headings_returns_warning(self):
        warnings = []
        sections = _extract_from_text("just some random text with no headings", "10-K", warnings)
        assert "text_item_headings_not_found" in warnings

    def test_extracts_10q_mda_from_item_2(self):
        warnings = []
        sections = _extract_from_text(SAMPLE_TEXT_10Q, "10-Q", warnings)
        keys = [s.section for s in sections]

        assert "mda" in keys
        assert "risk_factors" in keys
        assert "business" not in keys
        assert "section_not_found:mda" not in warnings

    def test_toc_headings_do_not_block_real_sections(self):
        warnings = []
        sections = _extract_from_text(SAMPLE_TEXT_10K_WITH_TOC, warnings)
        keys = [s.section for s in sections]

        assert "business" in keys
        assert "risk_factors" in keys
        assert "mda" in keys
        assert not any(w.startswith("section_too_short:") for w in warnings)


# ── Full integration test (with mocked FileStore) ─────────────────────────────

class TestSplitFiling:

    def test_split_filing_writes_sections(self, db_session, sample_filing):
        filing, tmp_path = sample_filing

        # Patch FileStore.get to return our sample HTML
        with patch("processing.filing_splitter.FileStore") as MockStore:
            instance = MockStore.return_value
            instance.get.return_value = SAMPLE_HTML_10K

            result = split_filing(filing.id, db=db_session)

        assert len(result.sections) >= 2
        section_names = [s.section for s in result.sections]
        assert "risk_factors" in section_names
        assert "mda" in section_names

    def test_split_filing_sets_is_extracted(self, db_session, sample_filing):
        filing, tmp_path = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = SAMPLE_HTML_10K
            split_filing(filing.id, db=db_session)

        db_session.refresh(filing)
        assert filing.is_extracted is True

    def test_split_filing_sets_processing_status(self, db_session, sample_filing):
        filing, tmp_path = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = SAMPLE_HTML_10K
            split_filing(filing.id, db=db_session)

        db_session.refresh(filing)
        assert filing.processing_status == "extracted"

    def test_split_filing_idempotent(self, db_session, sample_filing):
        """Running twice should not duplicate sections or raise errors."""
        filing, _ = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = SAMPLE_HTML_10K
            result1 = split_filing(filing.id, db=db_session)

        # Mark as extracted so second call hits the "already extracted" path
        filing.is_extracted = True
        db_session.flush()

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = SAMPLE_HTML_10K
            result2 = split_filing(filing.id, db=db_session)

        assert "already_extracted" in result2.warnings

    def test_split_filing_logs_pipeline_event(self, db_session, sample_filing):
        filing, _ = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = SAMPLE_HTML_10K
            split_filing(filing.id, db=db_session)

        events = db_session.query(PipelineEvent).filter_by(
            filing_id=filing.id, event_type="extracted"
        ).all()
        assert len(events) == 1
        assert events[0].detail["extractor"] == EXTRACTOR_VERSION

    def test_split_filing_marks_failed_when_no_sections_found(self, db_session, sample_filing):
        filing, _ = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.return_value = "plain text without extractable sections"
            result = split_filing(filing.id, db=db_session)

        db_session.refresh(filing)
        assert result.sections == []
        assert "no_sections_found" in result.warnings
        assert filing.is_extracted is False
        assert filing.processing_status == "failed"
        assert filing.last_error_message == "no_sections_found"

        events = db_session.query(PipelineEvent).filter_by(
            filing_id=filing.id, event_type="failed"
        ).all()
        assert len(events) == 1
        assert events[0].detail["reason"] == "no_sections_found"
        assert events[0].detail["step"] == "filing_splitter"

    def test_split_filing_missing_file_raises(self, db_session, sample_filing):
        filing, _ = sample_filing

        with patch("processing.filing_splitter.FileStore") as MockStore:
            MockStore.return_value.get.side_effect = FileNotFoundError("not found")
            with pytest.raises(RuntimeError, match="Raw file not found"):
                split_filing(filing.id, db=db_session)

    def test_split_filing_not_found_raises(self, db_session):
        with pytest.raises(RuntimeError, match="Filing id=99999 not found"):
            split_filing(99999, db=db_session)
