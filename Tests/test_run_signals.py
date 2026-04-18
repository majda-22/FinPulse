from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.filing
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.filing import Filing
from pipelines.signals_pipeline import run_all_signals


def test_run_all_signals_rejects_non_10k_10q_filings():
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
        processing_status="pending",
    )
    session.add(filing)
    session.flush()

    with pytest.raises(RuntimeError, match="run_signals should target a 10-K or 10-Q"):
        run_all_signals(filing.id, db=session)

    session.refresh(filing)
    assert filing.processing_status == "failed"
    assert "10-K or 10-Q" in str(filing.last_error_message)

    session.close()
