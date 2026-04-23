from datetime import date
import asyncio
from unittest.mock import AsyncMock, patch

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
from pipelines.form4_pipeline import parse_pending_form4_filings


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
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_pending_form4_filings_processes_stored_filings():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    session.add(company)
    session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-26-000001",
        form_type="4",
        filed_at=date(2026, 1, 21),
        period_of_report=date(2026, 1, 20),
        raw_s3_key="0000320193/4/0000320193-26-000001.txt",
        is_form4_parsed=False,
    )
    session.add(filing)
    session.flush()

    with patch("pipelines.form4_pipeline.FileStore") as MockStore:
        MockStore.return_value.get.return_value = SAMPLE_FORM4_XML

        summary = parse_pending_form4_filings(
            ticker="AAPL",
            limit=10,
            db=session,
        )

    session.refresh(filing)
    rows = session.query(InsiderTransaction).filter_by(filing_id=filing.id).all()

    assert summary["selected"] == 1
    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["stored_transactions"] == 1
    assert len(summary["results"]) == 1
    assert len(rows) == 1
    assert filing.is_form4_parsed is True
    assert filing.processing_status == "form4_parsed"

    session.close()


def test_parse_pending_form4_filings_repairs_html_raw_files():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    company = Company(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    session.add(company)
    session.flush()

    filing = Filing(
        company_id=company.id,
        accession_number="0000320193-26-000002",
        form_type="4",
        filed_at=date(2026, 1, 22),
        period_of_report=date(2026, 1, 21),
        raw_s3_key="0000320193/4/0000320193-26-000002.txt",
        is_form4_parsed=False,
    )
    session.add(filing)
    session.flush()

    class AsyncForm4ClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_form4_xml(self, *, accession_number, cik, primary_document=None):
            return SAMPLE_FORM4_XML

    with patch("pipelines.form4_pipeline.FileStore") as MockStore, patch(
        "pipelines.form4_pipeline.Form4Client",
        return_value=AsyncForm4ClientStub(),
    ):
        MockStore.return_value.get.return_value = "<html><body>SEC Form 4</body></html>"

        summary = parse_pending_form4_filings(
            ticker="AAPL",
            limit=10,
            db=session,
        )

    session.refresh(filing)
    rows = session.query(InsiderTransaction).filter_by(filing_id=filing.id).all()

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["repaired_raw_files"] == 1
    assert len(rows) == 1
    assert filing.is_form4_parsed is True
    assert MockStore.return_value.put.call_count == 1

    session.close()


def test_pipeline_download_uses_form4_xml_for_form4_filings():
    from ingestion.edgar_client import FilingMeta
    from pipelines.ingestion_pipeline import _download_filing_text

    meta = FilingMeta(
        accession_number="0000320193-26-000003",
        cik="0000320193",
        ticker="AAPL",
        form_type="4",
        filed_at=date(2026, 1, 23),
        period_of_report=date(2026, 1, 22),
        primary_document="primary_doc.html",
        document_url="https://example.com/primary_doc.html",
    )

    class DummyClient:
        async def get_filing_text(self, filing):
            return "html content"

    with patch("pipelines.ingestion_pipeline.Form4Client") as MockForm4Client:
        MockForm4Client.return_value.get_form4_xml = AsyncMock(return_value=SAMPLE_FORM4_XML)
        result = asyncio.run(_download_filing_text(DummyClient(), meta))

    assert result == SAMPLE_FORM4_XML
    MockForm4Client.return_value.get_form4_xml.assert_called_once()
