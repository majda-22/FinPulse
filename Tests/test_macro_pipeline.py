from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from app.db.base import Base
import app.db.models.macro_observation
import app.db.models.pipeline_event

from app.db.models.macro_observation import MacroObservation
from app.db.models.pipeline_event import PipelineEvent
from ingestion.fred_client import FredClient
from ingestion.macro_repo import upsert_macro_observations
from pipelines.run_macro_pipeline import run_macro_pipeline


def _make_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_fred_client_parses_metadata_and_observations():
    metadata = FredClient._parse_series_metadata(
        {
            "seriess": [
                {
                    "id": "CPIAUCSL",
                    "title": "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
                    "frequency": "Monthly",
                    "units": "Index 1982-1984=100",
                }
            ]
        },
        series_id="CPIAUCSL",
    )

    rows = FredClient._parse_observations_response(
        {
            "observations": [
                {"date": "2024-01-01", "value": "308.417"},
                {"date": "2024-02-01", "value": "."},
                {"date": "2024-03-01", "value": "312.230"},
            ]
        },
        provider="fred",
        metadata=metadata,
    )

    assert len(rows) == 2
    assert rows[0]["series_id"] == "CPIAUCSL"
    assert rows[0]["observation_date"] == date(2024, 1, 1)
    assert rows[0]["value"] == 308.417
    assert rows[0]["frequency"] == "Monthly"
    assert rows[1]["observation_date"] == date(2024, 3, 1)


def test_upsert_macro_observations_is_rerun_safe():
    session = _make_session()

    first = upsert_macro_observations(
        session,
        rows=[
            {
                "series_id": "FEDFUNDS",
                "observation_date": date(2024, 1, 1),
                "value": 5.33,
                "provider": "fred",
                "frequency": "Monthly",
                "units": "Percent",
                "title": "Effective Federal Funds Rate",
            }
        ],
    )
    second = upsert_macro_observations(
        session,
        rows=[
            {
                "series_id": "FEDFUNDS",
                "observation_date": date(2024, 1, 1),
                "value": 5.35,
                "provider": "fred",
                "frequency": "Monthly",
                "units": "Percent",
                "title": "Effective Federal Funds Rate",
            }
        ],
    )

    rows = session.query(MacroObservation).all()

    assert first["inserted"] == 1
    assert second["updated"] == 1
    assert len(rows) == 1
    assert float(rows[0].value) == 5.35

    session.close()


def test_run_macro_pipeline_fetches_and_logs_observations():
    session = _make_session()

    class AsyncFredClientStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def fetch_series_observations(self, *, series_id, start=None, end=None, provider="fred"):
            return [
                {
                    "series_id": series_id,
                    "observation_date": date(2024, 1, 1),
                    "value": 100.0,
                    "provider": provider,
                    "frequency": "Monthly",
                    "units": "Index",
                    "title": f"{series_id} title",
                }
            ]

    @contextmanager
    def fake_get_db():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    with patch(
        "pipelines.run_macro_pipeline.FredClient",
        return_value=AsyncFredClientStub(),
    ), patch(
        "pipelines.run_macro_pipeline.get_db",
        fake_get_db,
    ):
        summary = asyncio.run(
            run_macro_pipeline(
                series_ids=["CPIAUCSL", "FEDFUNDS"],
                start=date(2024, 1, 1),
                end=date(2024, 12, 31),
            )
        )

    rows = session.query(MacroObservation).all()
    events = session.query(PipelineEvent).filter_by(
        event_type="macro_observations_ingested",
    ).all()

    assert summary["fetched"] == 2
    assert summary["inserted"] == 2
    assert len(rows) == 2
    assert len(events) == 1

    session.close()


def test_upsert_macro_observations_handles_large_single_series_batches():
    session = _make_session()
    start = date(2020, 1, 1)

    rows = [
        {
            "series_id": "DGS10",
            "observation_date": start + timedelta(days=offset),
            "value": 1.0 + (offset / 1000),
            "provider": "fred",
            "frequency": "Daily",
            "units": "Percent",
            "title": "10-Year Treasury Constant Maturity Rate",
        }
        for offset in range(2500)
    ]

    summary = upsert_macro_observations(session, rows=rows)
    stored = session.query(MacroObservation).filter_by(series_id="DGS10").count()

    assert summary["inserted"] == 2500
    assert summary["updated"] == 0
    assert stored == 2500

    session.close()
