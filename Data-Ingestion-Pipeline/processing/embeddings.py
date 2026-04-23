"""
processing/embeddings.py

Generate embeddings for extracted filing sections using Mistral's embeddings API
and persist one vector row per chunk.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.company import Company
from app.db.models.embedding import Embedding
from app.db.models.filing import Filing
from app.db.models.pipeline_event import PipelineEvent
from app.db.session import get_db
from processing.chunker import CHUNKER_VERSION, FilingChunk, chunk_filing

logger = logging.getLogger(__name__)

EMBEDDINGS_VERSION = "1.0.0"
MISTRAL_EMBEDDING_DIM = 1024
EMBEDDING_PROVIDER = "mistral"
EMBEDDING_REQUEST_MAX_RETRIES = 4
EMBEDDING_RETRY_BASE_DELAY_SEC = 2.0
EMBEDDING_RETRY_MAX_DELAY_SEC = 30.0


@dataclass
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    prompt_tokens: int


@dataclass
class EmbeddingResult:
    filing_id: int
    accession_number: str
    chunk_count: int
    stored_count: int
    provider: str
    model: str
    prompt_tokens: int
    warnings: list[str]


class MistralEmbeddingClient:
    """
    Minimal REST client for Mistral's /v1/embeddings endpoint.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        expected_dimension: int = MISTRAL_EMBEDDING_DIM,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        settings = get_settings()

        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_embedding_model
        self.base_url = (base_url or settings.mistral_api_base).rstrip("/")
        self.timeout_sec = timeout_sec or settings.embedding_request_timeout_sec
        self.expected_dimension = expected_dimension

        if not self.api_key:
            raise ValueError("Missing Mistral API key. Set MISTRAL_API_KEY in .env.")

        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=self.timeout_sec,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MistralEmbeddingClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=[], model=self.model, prompt_tokens=0)

        response = self._post_with_retries(
            f"{self.base_url}/v1/embeddings",
            json={
                "model": self.model,
                "input": list(texts),
            },
        )
        payload = response.json()

        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [[float(value) for value in item["embedding"]] for item in data]

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"Mistral returned {len(vectors)} embeddings for {len(texts)} inputs"
            )

        for vector in vectors:
            if len(vector) != self.expected_dimension:
                raise RuntimeError(
                    f"Expected {self.expected_dimension}-dim embeddings from Mistral, "
                    f"received {len(vector)}"
                )

        usage = payload.get("usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)

        return EmbeddingBatch(
            vectors=vectors,
            model=payload.get("model") or self.model,
            prompt_tokens=prompt_tokens,
        )

    def _post_with_retries(self, url: str, *, json: dict) -> httpx.Response:
        attempt = 0

        while True:
            try:
                response = self._client.post(url, json=json)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if not self._should_retry_http_status(exc.response, attempt):
                    raise

                delay_sec = _compute_retry_delay_sec(
                    attempt=attempt,
                    retry_after_header=exc.response.headers.get("Retry-After"),
                )
                logger.warning(
                    "Mistral embeddings request hit HTTP %s. Retry %d/%d in %.1fs.",
                    exc.response.status_code,
                    attempt + 1,
                    EMBEDDING_REQUEST_MAX_RETRIES,
                    delay_sec,
                )
                time.sleep(delay_sec)
                attempt += 1
            except httpx.TransportError as exc:
                if attempt >= EMBEDDING_REQUEST_MAX_RETRIES:
                    raise

                delay_sec = _compute_retry_delay_sec(attempt=attempt)
                logger.warning(
                    "Mistral embeddings transport error: %s. Retry %d/%d in %.1fs.",
                    exc,
                    attempt + 1,
                    EMBEDDING_REQUEST_MAX_RETRIES,
                    delay_sec,
                )
                time.sleep(delay_sec)
                attempt += 1

    def _should_retry_http_status(self, response: httpx.Response, attempt: int) -> bool:
        if attempt >= EMBEDDING_REQUEST_MAX_RETRIES:
            return False
        return response.status_code in {408, 429, 500, 502, 503, 504}


def embed_filing(
    filing_id: int,
    db: Optional[Session] = None,
    *,
    client: Optional[MistralEmbeddingClient] = None,
    force: bool = False,
    batch_size: Optional[int] = None,
    chunk_target_chars: int = 1_500,
    chunk_max_chars: int = 1_800,
    chunk_min_chars: int = 300,
    chunk_overlap_chars: int = 150,
) -> EmbeddingResult:
    own_client = client is None
    provider = client or MistralEmbeddingClient()

    try:
        if db is None:
            try:
                with get_db() as session:
                    return _embed_filing_inner(
                        filing_id=filing_id,
                        db=session,
                        client=provider,
                        force=force,
                        batch_size=batch_size,
                        chunk_target_chars=chunk_target_chars,
                        chunk_max_chars=chunk_max_chars,
                        chunk_min_chars=chunk_min_chars,
                        chunk_overlap_chars=chunk_overlap_chars,
                    )
            except Exception as exc:
                _mark_failed_in_new_session(filing_id, str(exc))
                raise

        try:
            return _embed_filing_inner(
                filing_id=filing_id,
                db=db,
                client=provider,
                force=force,
                batch_size=batch_size,
                chunk_target_chars=chunk_target_chars,
                chunk_max_chars=chunk_max_chars,
                chunk_min_chars=chunk_min_chars,
                chunk_overlap_chars=chunk_overlap_chars,
            )
        except Exception as exc:
            _mark_failed(db, filing_id, str(exc))
            raise
    finally:
        if own_client:
            provider.close()


def embed_all_pending(
    *,
    limit: int = 100,
    force: bool = False,
    batch_size: Optional[int] = None,
) -> dict:
    summary = {"processed": 0, "skipped": 0, "failed": 0, "stored_chunks": 0}

    with get_db() as db:
        filing_ids = db.scalars(
            select(Filing.id)
            .where(
                Filing.is_extracted == True,   # noqa: E712
                Filing.is_embedded == False,   # noqa: E712
            )
            .order_by(Filing.filed_at.desc())
            .limit(limit)
        ).all()

    with MistralEmbeddingClient() as client:
        for filing_id in filing_ids:
            try:
                result = embed_filing(
                    filing_id,
                    client=client,
                    force=force,
                    batch_size=batch_size,
                )
                if "already_embedded" in result.warnings:
                    summary["skipped"] += 1
                else:
                    summary["processed"] += 1
                    summary["stored_chunks"] += result.stored_count
            except Exception as exc:
                logger.error("Failed to embed filing %d: %s", filing_id, exc)
                summary["failed"] += 1

    return summary


def embed_by_ticker(
    ticker: str,
    *,
    form_type: str = "10-K",
    force: bool = False,
    batch_size: Optional[int] = None,
) -> dict:
    with get_db() as db:
        company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
        if company is None:
            raise ValueError(f"Company with ticker {ticker!r} not found in DB")

        filing_ids = db.scalars(
            select(Filing.id)
            .where(
                Filing.company_id == company.id,
                Filing.form_type == form_type,
                Filing.is_extracted == True,   # noqa: E712
            )
            .order_by(Filing.filed_at.desc())
        ).all()

    summary = {"ticker": ticker.upper(), "processed": 0, "failed": 0, "stored_chunks": 0}

    with MistralEmbeddingClient() as client:
        for filing_id in filing_ids:
            try:
                result = embed_filing(
                    filing_id,
                    client=client,
                    force=force,
                    batch_size=batch_size,
                )
                if "already_embedded" not in result.warnings:
                    summary["processed"] += 1
                    summary["stored_chunks"] += result.stored_count
            except Exception as exc:
                logger.error("Failed filing %d: %s", filing_id, exc)
                summary["failed"] += 1

    return summary


def _embed_filing_inner(
    *,
    filing_id: int,
    db: Session,
    client: MistralEmbeddingClient,
    force: bool,
    batch_size: Optional[int],
    chunk_target_chars: int,
    chunk_max_chars: int,
    chunk_min_chars: int,
    chunk_overlap_chars: int,
) -> EmbeddingResult:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    warnings: list[str] = []

    if filing.is_embedded and not force:
        return EmbeddingResult(
            filing_id=filing.id,
            accession_number=filing.accession_number,
            chunk_count=0,
            stored_count=0,
            provider=EMBEDDING_PROVIDER,
            model=client.model,
            prompt_tokens=0,
            warnings=["already_embedded"],
        )

    if not filing.is_extracted:
        raise RuntimeError(f"Filing id={filing_id} has not been extracted yet")

    t0 = time.monotonic()
    chunk_result = chunk_filing(
        filing_id=filing_id,
        db=db,
        target_chars=chunk_target_chars,
        max_chars=chunk_max_chars,
        min_chars=chunk_min_chars,
        overlap_chars=chunk_overlap_chars,
    )
    warnings.extend(chunk_result.warnings)

    if not chunk_result.chunks:
        raise RuntimeError(f"No chunks available for filing id={filing_id}")

    db.execute(delete(Embedding).where(Embedding.filing_id == filing_id))
    db.flush()

    effective_batch_size = batch_size or get_settings().batch_size
    stored_count = 0
    prompt_tokens = 0
    resolved_model = client.model

    for start in range(0, len(chunk_result.chunks), effective_batch_size):
        chunk_batch = chunk_result.chunks[start:start + effective_batch_size]
        texts = [chunk.text for chunk in chunk_batch]
        embed_batch = client.embed_texts(texts)
        prompt_tokens += embed_batch.prompt_tokens
        resolved_model = embed_batch.model
        _insert_embeddings(
            db=db,
            chunks=chunk_batch,
            vectors=embed_batch.vectors,
            provider=EMBEDDING_PROVIDER,
            model=resolved_model,
        )
        stored_count += len(chunk_batch)

    filing.is_embedded = True
    filing.processing_status = "embedded"
    filing.last_error_message = None
    db.flush()

    duration_ms = int((time.monotonic() - t0) * 1000)
    db.add(
        PipelineEvent(
            filing_id=filing.id,
            company_id=filing.company_id,
            layer="processing",
            event_type="embedded",
            duration_ms=duration_ms,
            detail={
                "provider": EMBEDDING_PROVIDER,
                "model": resolved_model,
                "chunk_count": len(chunk_result.chunks),
                "stored_count": stored_count,
                "prompt_tokens": prompt_tokens,
                "embedding_dim": MISTRAL_EMBEDDING_DIM,
                "chunker_version": CHUNKER_VERSION,
                "embeddings_version": EMBEDDINGS_VERSION,
                "force": force,
                "warnings": warnings,
                "accession": filing.accession_number,
            },
        )
    )
    db.flush()

    return EmbeddingResult(
        filing_id=filing.id,
        accession_number=filing.accession_number,
        chunk_count=len(chunk_result.chunks),
        stored_count=stored_count,
        provider=EMBEDDING_PROVIDER,
        model=resolved_model,
        prompt_tokens=prompt_tokens,
        warnings=warnings,
    )


def _insert_embeddings(
    *,
    db: Session,
    chunks: Sequence[FilingChunk],
    vectors: Sequence[Sequence[float]],
    provider: str,
    model: str,
) -> None:
    if len(chunks) != len(vectors):
        raise RuntimeError("Chunk/vector count mismatch while inserting embeddings")

    for chunk, vector in zip(chunks, vectors):
        db.add(
            Embedding(
                filing_section_id=chunk.filing_section_id,
                company_id=chunk.company_id,
                filing_id=chunk.filing_id,
                chunk_idx=chunk.chunk_idx,
                text=chunk.text,
                embedding=list(vector),
                provider=provider,
                embedding_model=model,
            )
        )

    db.flush()


def _mark_failed(db: Session, filing_id: int, error: str) -> None:
    filing = db.get(Filing, filing_id)
    if filing is None:
        return

    filing.processing_status = "failed"
    filing.last_error_message = error
    db.add(
        PipelineEvent(
            filing_id=filing.id,
            company_id=filing.company_id,
            layer="processing",
            event_type="failed",
            detail={"error": error, "step": "embeddings"},
        )
    )
    db.flush()


def _compute_retry_delay_sec(*, attempt: int, retry_after_header: str | None = None) -> float:
    retry_after_sec = _parse_retry_after_sec(retry_after_header)
    if retry_after_sec is not None:
        return max(0.0, min(retry_after_sec, EMBEDDING_RETRY_MAX_DELAY_SEC))

    backoff = EMBEDDING_RETRY_BASE_DELAY_SEC * (2 ** attempt)
    return max(0.0, min(backoff, EMBEDDING_RETRY_MAX_DELAY_SEC))


def _parse_retry_after_sec(value: str | None) -> float | None:
    if value is None:
        return None

    token = value.strip()
    if not token:
        return None

    try:
        return float(token)
    except ValueError:
        return None


def _mark_failed_in_new_session(filing_id: int, error: str) -> None:
    try:
        with get_db() as db:
            _mark_failed(db, filing_id, error)
    except Exception:
        logger.exception("Failed to persist embedding failure state for filing %d", filing_id)


def _parse_args():
    parser = argparse.ArgumentParser(description="Generate Mistral embeddings for filings")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--filing-id", type=int, help="Embed one specific filing by DB id")
    group.add_argument("--ticker", type=str, help="Embed all extracted filings for a ticker")
    group.add_argument("--all-pending", action="store_true", help="Embed all extracted but unembedded filings")
    parser.add_argument("--form", default="10-K", help="Form type filter when using --ticker")
    parser.add_argument("--limit", type=int, default=100, help="Max filings when using --all-pending")
    parser.add_argument("--batch-size", type=int, default=None, help="Texts per Mistral request")
    parser.add_argument("--force", action="store_true", help="Recompute and replace existing embeddings")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args()

    if args.filing_id:
        result = embed_filing(
            args.filing_id,
            force=args.force,
            batch_size=args.batch_size,
        )
        print(f"\nFiling {result.filing_id} ({result.accession_number})")
        print(f"  Stored embeddings: {result.stored_count}")
        print(f"  Provider/model: {result.provider} / {result.model}")
        print(f"  Prompt tokens: {result.prompt_tokens}")
        if result.warnings:
            print(f"  Warnings: {result.warnings}")

    elif args.ticker:
        summary = embed_by_ticker(
            args.ticker,
            form_type=args.form,
            force=args.force,
            batch_size=args.batch_size,
        )
        print(f"\n{summary['ticker']} - {args.form}")
        print(f"  Processed: {summary['processed']}  Failed: {summary['failed']}")
        print(f"  Stored chunks: {summary['stored_chunks']}")

    elif args.all_pending:
        summary = embed_all_pending(
            limit=args.limit,
            force=args.force,
            batch_size=args.batch_size,
        )
        print("\nAll pending extracted filings:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Skipped:   {summary['skipped']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Stored:    {summary['stored_chunks']}")


if __name__ == "__main__":
    main()
