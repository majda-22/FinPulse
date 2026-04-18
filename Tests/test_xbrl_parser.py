from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.pipeline_event
import app.db.models.xbrl_fact

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.pipeline_event import PipelineEvent
from app.db.models.xbrl_fact import XbrlFact
from processing.xbrl_parser import (
    parse_company_xbrl_facts,
    parse_companyfacts_payload,
    persist_companyfacts_payload,
)


SAMPLE_INLINE_XBRL = """\
<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2023">
  <body>
    <div style="display:none">
      <ix:header>
        <ix:resources>
          <xbrli:context id="dur">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2023-01-01</xbrli:startDate>
              <xbrli:endDate>2023-12-31</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
          <xbrli:context id="inst">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:instant>2023-12-31</xbrli:instant>
            </xbrli:period>
          </xbrli:context>
          <xbrli:context id="seg">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">
                  us-gaap:ConsolidatedGroupMember
                </xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2023-01-01</xbrli:startDate>
              <xbrli:endDate>2023-12-31</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
          <xbrli:unit id="usd">
            <xbrli:measure>iso4217:USD</xbrli:measure>
          </xbrli:unit>
        </ix:resources>
      </ix:header>
    </div>
    <ix:nonFraction name="us-gaap:Revenues" contextRef="dur" unitRef="usd" decimals="-6" scale="6">250.0</ix:nonFraction>
    <ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="dur" unitRef="usd" decimals="-6" scale="6">(50.0)</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Assets" contextRef="inst" unitRef="usd" decimals="-6" scale="6">900.0</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Liabilities" contextRef="inst" unitRef="usd" decimals="-6" scale="6">500.0</ix:nonFraction>
    <ix:nonFraction name="us-gaap:Revenues" contextRef="seg" unitRef="usd" decimals="-6" scale="6">999.0</ix:nonFraction>
  </body>
</html>
"""


def _build_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_parse_companyfacts_payload_matches_filings_by_accession():
    db = _build_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db.add(company)
    db.flush()

    q3 = Filing(
        company_id=company.id,
        accession_number="0000320193-24-000090",
        form_type="10-Q",
        filed_at=date(2024, 11, 1),
        period_of_report=date(2024, 9, 28),
        raw_s3_key="q3",
    )
    annual = Filing(
        company_id=company.id,
        accession_number="0000320193-24-000120",
        form_type="10-K",
        filed_at=date(2025, 1, 31),
        period_of_report=date(2024, 9, 28),
        raw_s3_key="annual",
    )
    db.add_all([q3, annual])
    db.flush()

    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "val": 900.0,
                                "start": "2024-01-01",
                                "end": "2024-09-28",
                                "fy": 2024,
                                "fp": "Q3",
                                "form": "10-Q",
                                "filed": "2024-11-01",
                                "accn": "0000320193-24-000090",
                            },
                            {
                                "val": 1200.0,
                                "start": "2023-09-30",
                                "end": "2024-09-28",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-01-31",
                                "accn": "0000320193-24-000120",
                            },
                        ]
                    },
                }
            }
        }
    }

    filings_by_accession = {
        q3.accession_number: q3,
        annual.accession_number: annual,
    }
    filings_by_form_period = {
        (q3.form_type, q3.period_of_report): q3,
        (annual.form_type, annual.period_of_report): annual,
    }

    parsed_facts, warnings = parse_companyfacts_payload(
        payload,
        company_id=company.id,
        filings_by_accession=filings_by_accession,
        filings_by_form_period=filings_by_form_period,
    )

    assert warnings == []
    assert len(parsed_facts) == 2
    by_form = {fact.form_type: fact for fact in parsed_facts}
    assert by_form["10-Q"].filing_id == q3.id
    assert by_form["10-Q"].period_start == date(2024, 1, 1)
    assert by_form["10-K"].filing_id == annual.id
    assert by_form["10-K"].period_start == date(2023, 9, 30)

    db.close()


def test_persist_companyfacts_payload_stores_rows_and_marks_filings_parsed():
    db = _build_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db.add(company)
    db.flush()

    annual = Filing(
        company_id=company.id,
        accession_number="0000320193-24-000120",
        form_type="10-K",
        filed_at=date(2025, 1, 31),
        period_of_report=date(2024, 9, 28),
        raw_s3_key="annual",
        is_xbrl_parsed=False,
    )
    db.add(annual)
    db.flush()

    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "val": 1200.0,
                                "start": "2023-09-30",
                                "end": "2024-09-28",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-01-31",
                                "accn": "0000320193-24-000120",
                            }
                        ]
                    },
                },
                "NetIncomeLoss": {
                    "label": "Net income",
                    "units": {
                        "USD": [
                            {
                                "val": 250.0,
                                "start": "2023-09-30",
                                "end": "2024-09-28",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-01-31",
                                "accn": "0000320193-24-000120",
                            }
                        ]
                    },
                },
            }
        }
    }

    result = persist_companyfacts_payload(
        db,
        company_id=company.id,
        cik=company.cik,
        payload=payload,
        filing_id=annual.id,
    )

    rows = db.query(XbrlFact).filter_by(company_id=company.id).all()
    events = db.query(PipelineEvent).filter_by(filing_id=annual.id, event_type="xbrl_parsed").all()

    assert result.stored_count == 2
    assert result.inserted_count == 2
    assert result.updated_count == 0
    assert result.matched_filing_ids == [annual.id]
    assert len(rows) == 2
    assert annual.is_xbrl_parsed is True
    assert annual.processing_status == "xbrl_parsed"
    assert len(events) == 1

    db.close()


def test_parse_company_xbrl_facts_falls_back_to_inline_xbrl_when_companyfacts_fails():
    db = _build_session()
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db.add(company)
    db.flush()

    annual = Filing(
        company_id=company.id,
        accession_number="0000320193-24-000120",
        form_type="10-K",
        filed_at=date(2025, 1, 31),
        period_of_report=date(2023, 12, 31),
        raw_s3_key="annual",
        is_xbrl_parsed=False,
    )
    db.add(annual)
    db.flush()

    with patch(
        "processing.xbrl_parser._fetch_companyfacts_payload",
        side_effect=RuntimeError("network down"),
    ), patch("processing.xbrl_parser.FileStore") as MockStore:
        MockStore.return_value.get.return_value = SAMPLE_INLINE_XBRL

        result = parse_company_xbrl_facts(
            filing_id=annual.id,
            db=db,
        )

    rows = db.query(XbrlFact).filter_by(filing_id=annual.id).all()
    by_concept = {row.concept: row for row in rows}

    assert result.stored_count == 4
    assert result.inserted_count == 4
    assert result.updated_count == 0
    assert result.matched_filing_ids == [annual.id]
    assert "companyfacts_fetch_failed:RuntimeError" in result.warnings
    assert "inline_xbrl_fallback_used" in result.warnings
    assert sorted(by_concept) == ["Assets", "Liabilities", "NetIncomeLoss", "Revenues"]
    assert float(by_concept["Revenues"].value) == 250_000_000.0
    assert float(by_concept["NetIncomeLoss"].value) == -50_000_000.0
    assert by_concept["Revenues"].period_start == date(2023, 1, 1)
    assert by_concept["Revenues"].period_end == date(2023, 12, 31)
    assert by_concept["Assets"].period_start is None
    assert by_concept["Assets"].period_end == date(2023, 12, 31)
    assert by_concept["Assets"].unit == "USD"
    assert annual.is_xbrl_parsed is True
    assert annual.processing_status == "xbrl_parsed"

    db.close()
