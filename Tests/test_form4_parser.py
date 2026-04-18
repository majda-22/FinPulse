from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.insider_transaction
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.insider_transaction import InsiderTransaction
from app.db.models.pipeline_event import PipelineEvent
from processing.form4_parser import normalize_transaction_type, parse_and_store_form4_xml, parse_form4_xml


SAMPLE_FORM4_XML = """\
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214156</rptOwnerCik>
      <rptOwnerName>Cook Tim D</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-01-15</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>185.25</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>3200000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-01-20</value></transactionDate>
      <transactionCoding>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>190.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>3199500</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Stock Option</value></securityTitle>
      <conversionOrExercisePrice><value>120.00</value></conversionOrExercisePrice>
      <transactionDate><value>2026-01-18</value></transactionDate>
      <transactionCoding>
        <transactionCode>M</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>250</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>250</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>I</value></directOrIndirectOwnership>
      </ownershipNature>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""


SAMPLE_FORM4_XML_WITH_DERIVATIVE_PAIR = """\
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214156</rptOwnerCik>
      <rptOwnerName>Cook Tim D</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-02-01</value></transactionDate>
      <transactionCoding>
        <transactionCode>M</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>0.0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>100</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Stock Option</value></securityTitle>
      <transactionDate><value>2026-02-01</value></transactionDate>
      <transactionCoding>
        <transactionCode>M</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>0.0</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def form4_filing(db_session):
    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db_session.add(company)
    db_session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-26-000001",
        form_type="4",
        filed_at=date(2026, 1, 21),
        period_of_report=date(2026, 1, 20),
        raw_s3_key="aapl/form4/0000320193-26-000001.xml",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def test_normalize_transaction_type_maps_primary_codes():
    assert normalize_transaction_type("P") == "open_market_buy"
    assert normalize_transaction_type("S") == "open_market_sell"
    assert normalize_transaction_type("M", is_derivative=True) == "option_exercise"
    assert normalize_transaction_type("X", acquired_disposed_code="D") == "other_disposition"


def test_parse_form4_xml_extracts_normalized_transactions(form4_filing):
    rows = parse_form4_xml(
        SAMPLE_FORM4_XML,
        company_id=form4_filing.company_id,
        filing_id=form4_filing.id,
        accession_number=form4_filing.accession_number,
        cik="0000320193",
        ticker="AAPL",
        issuer_name="Apple Inc.",
        filed_at=form4_filing.filed_at,
        form_type="4",
        source_url="https://www.sec.gov/example.xml",
    )

    assert len(rows) == 3
    by_code = {row["transaction_code"]: row for row in rows}

    assert by_code["P"]["transaction_type_normalized"] == "open_market_buy"
    assert by_code["P"]["transaction_value"] == pytest.approx(185250.0)
    assert by_code["P"]["ownership_nature"] == "direct"
    assert by_code["P"]["is_officer"] is True
    assert by_code["S"]["transaction_type_normalized"] == "open_market_sell"
    assert by_code["S"]["shares_owned_after"] == pytest.approx(3199500.0)
    assert by_code["M"]["transaction_type_normalized"] == "option_exercise"
    assert by_code["M"]["is_derivative"] is True
    assert by_code["M"]["ownership_nature"] == "indirect"
    assert by_code["M"]["transaction_uid"]


def test_parse_and_store_form4_xml_upserts_rows_and_logs_event(db_session, form4_filing):
    first = parse_and_store_form4_xml(
        filing_id=form4_filing.id,
        xml_text=SAMPLE_FORM4_XML,
        db=db_session,
        source_url="https://www.sec.gov/example.xml",
    )
    second = parse_and_store_form4_xml(
        filing_id=form4_filing.id,
        xml_text=SAMPLE_FORM4_XML,
        db=db_session,
        source_url="https://www.sec.gov/example.xml",
    )

    rows = db_session.query(InsiderTransaction).filter_by(filing_id=form4_filing.id).all()
    events = db_session.query(PipelineEvent).filter_by(
        filing_id=form4_filing.id,
        event_type="form4_parsed",
    ).all()

    assert first.stored_count == 3
    assert first.inserted_count == 3
    assert second.updated_count == 3
    assert len(rows) == 3
    assert form4_filing.is_form4_parsed is True
    assert form4_filing.processing_status == "form4_parsed"
    assert len(events) == 2


def test_parse_and_store_form4_xml_keeps_derivative_and_non_derivative_pairs(
    db_session,
    form4_filing,
):
    result = parse_and_store_form4_xml(
        filing_id=form4_filing.id,
        xml_text=SAMPLE_FORM4_XML_WITH_DERIVATIVE_PAIR,
        db=db_session,
    )

    rows = (
        db_session.query(InsiderTransaction)
        .filter_by(filing_id=form4_filing.id)
        .order_by(InsiderTransaction.is_derivative.asc())
        .all()
    )

    assert result.stored_count == 2
    assert result.inserted_count == 2
    assert len(rows) == 2
    assert rows[0].is_derivative is False
    assert rows[0].security_title == "Common Stock"
    assert rows[1].is_derivative is True
    assert rows[1].security_title == "Stock Option"
