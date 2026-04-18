from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models.company
import app.db.models.embedding
import app.db.models.filing
import app.db.models.filing_section
import app.db.models.pipeline_event

from app.db.models.company import Company
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.models.pipeline_event import PipelineEvent
from processing.embeddings import (
    EMBEDDING_REQUEST_MAX_RETRIES,
    EmbeddingBatch,
    MISTRAL_EMBEDDING_DIM,
    MistralEmbeddingClient,
    embed_filing,
)


def _make_text(prefix: str, count: int) -> str:
    sentences = []
    for idx in range(1, count + 1):
        sentences.append(
            f"{prefix} sentence {idx} contains enough narrative detail to test "
            f"chunking and downstream embedding persistence cleanly."
        )
    return " ".join(sentences)


def _vector(seed: float) -> list[float]:
    return [seed] * MISTRAL_EMBEDDING_DIM


class FakeMistralClient:
    def __init__(self, *, model: str = "mistral-embed") -> None:
        self.model = model
        self.calls: list[list[str]] = []

    def embed_texts(self, texts):
        batch = list(texts)
        self.calls.append(batch)
        return EmbeddingBatch(
            vectors=[_vector(float(idx + 1)) for idx, _ in enumerate(batch)],
            model=self.model,
            prompt_tokens=len(batch) * 10,
        )


class FailingMistralClient(FakeMistralClient):
    def embed_texts(self, texts):
        raise RuntimeError("provider boom")


class SequencedHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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
    rows = [
        FilingSection(
            filing_id=sample_filing.id,
            company_id=sample_company.id,
            section="risk_factors",
            sequence_idx=0,
            text=_make_text("Risk factor", 10),
            extractor_version="1.0.0",
        ),
        FilingSection(
            filing_id=sample_filing.id,
            company_id=sample_company.id,
            section="mda",
            sequence_idx=0,
            text=_make_text("Management discussion", 9),
            extractor_version="1.0.0",
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


class TestEmbedFiling:
    def test_embed_filing_persists_rows_and_marks_embedded(self, db_session, sample_filing, sample_sections):
        client = FakeMistralClient()

        result = embed_filing(
            sample_filing.id,
            db=db_session,
            client=client,
            batch_size=2,
            chunk_target_chars=220,
            chunk_max_chars=260,
            chunk_min_chars=80,
            chunk_overlap_chars=0,
        )

        rows = db_session.query(Embedding).filter_by(filing_id=sample_filing.id).all()
        db_session.refresh(sample_filing)

        assert result.stored_count == len(rows)
        assert len(rows) >= 4
        assert sample_filing.is_embedded is True
        assert sample_filing.processing_status == "embedded"
        assert client.calls
        assert all(len(row.embedding) == MISTRAL_EMBEDDING_DIM for row in rows)

    def test_embed_filing_logs_pipeline_event(self, db_session, sample_filing, sample_sections):
        result = embed_filing(
            sample_filing.id,
            db=db_session,
            client=FakeMistralClient(),
            batch_size=3,
            chunk_target_chars=220,
            chunk_max_chars=260,
            chunk_min_chars=80,
            chunk_overlap_chars=0,
        )

        event = db_session.query(PipelineEvent).filter_by(
            filing_id=sample_filing.id,
            event_type="embedded",
        ).one()

        assert event.detail["provider"] == "mistral"
        assert event.detail["model"] == result.model
        assert event.detail["stored_count"] == result.stored_count

    def test_embed_filing_already_embedded_returns_warning(self, db_session, sample_filing, sample_sections):
        sample_filing.is_embedded = True
        db_session.flush()

        client = FakeMistralClient()
        result = embed_filing(sample_filing.id, db=db_session, client=client)

        assert "already_embedded" in result.warnings
        assert client.calls == []

    def test_embed_filing_force_replaces_existing_rows(self, db_session, sample_company, sample_filing, sample_sections):
        stale = Embedding(
            filing_section_id=sample_sections[0].id,
            company_id=sample_company.id,
            filing_id=sample_filing.id,
            chunk_idx=99,
            text="stale",
            embedding=_vector(9.0),
            provider="mistral",
            embedding_model="stale-model",
        )
        db_session.add(stale)
        db_session.flush()

        result = embed_filing(
            sample_filing.id,
            db=db_session,
            client=FakeMistralClient(),
            force=True,
            batch_size=2,
            chunk_target_chars=220,
            chunk_max_chars=260,
            chunk_min_chars=80,
            chunk_overlap_chars=0,
        )

        rows = db_session.query(Embedding).filter_by(filing_id=sample_filing.id).all()

        assert result.stored_count == len(rows)
        assert all(row.chunk_idx != 99 for row in rows)

    def test_embed_filing_failure_marks_filing_failed(self, db_session, sample_filing, sample_sections):
        with pytest.raises(RuntimeError, match="provider boom"):
            embed_filing(sample_filing.id, db=db_session, client=FailingMistralClient())

        db_session.refresh(sample_filing)
        failed_event = db_session.query(PipelineEvent).filter_by(
            filing_id=sample_filing.id,
            event_type="failed",
        ).one()

        assert sample_filing.processing_status == "failed"
        assert "provider boom" in sample_filing.last_error_message
        assert failed_event.detail["step"] == "embeddings"


class TestMistralEmbeddingClient:
    def test_embed_texts_retries_rate_limit_then_succeeds(self, monkeypatch):
        request = httpx.Request("POST", "https://api.mistral.ai/v1/embeddings")
        rate_limited = httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        success = httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": _vector(1.0)}],
                "model": "mistral-embed",
                "usage": {"prompt_tokens": 7},
            },
            request=request,
        )
        http_client = SequencedHttpClient([rate_limited, success])
        sleep_calls: list[float] = []
        monkeypatch.setattr("processing.embeddings.time.sleep", sleep_calls.append)

        client = MistralEmbeddingClient(api_key="test-key", http_client=http_client)
        result = client.embed_texts(["hello world"])

        assert http_client.calls == 2
        assert sleep_calls == [0.0]
        assert result.prompt_tokens == 7
        assert result.model == "mistral-embed"
        assert len(result.vectors) == 1
        assert len(result.vectors[0]) == MISTRAL_EMBEDDING_DIM

    def test_embed_texts_raises_after_retry_budget_exhausted(self, monkeypatch):
        request = httpx.Request("POST", "https://api.mistral.ai/v1/embeddings")
        responses = [
            httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            for _ in range(EMBEDDING_REQUEST_MAX_RETRIES + 1)
        ]
        http_client = SequencedHttpClient(responses)
        sleep_calls: list[float] = []
        monkeypatch.setattr("processing.embeddings.time.sleep", sleep_calls.append)

        client = MistralEmbeddingClient(api_key="test-key", http_client=http_client)

        with pytest.raises(httpx.HTTPStatusError):
            client.embed_texts(["hello world"])

        assert http_client.calls == EMBEDDING_REQUEST_MAX_RETRIES + 1
        assert len(sleep_calls) == EMBEDDING_REQUEST_MAX_RETRIES
