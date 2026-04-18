from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.embedding import Embedding
from app.db.models.filing_section import FilingSection


@dataclass
class SectionSimilarityResult:
    section: str
    current_chunk_count: int
    previous_chunk_count: int
    average_best_similarity: float | None
    drift_score: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_drift_score(average_similarity: float) -> float:
    """Map cosine similarity from [-1, 1] into a business-friendly drift score in [0, 1]."""
    return float(np.clip((1.0 - average_similarity) / 2.0, 0.0, 1.0))


def cosine_similarity(vec1: list[float] | tuple[float, ...], vec2: list[float] | tuple[float, ...]) -> float:
    a = np.asarray(vec1, dtype=float)
    b = np.asarray(vec2, dtype=float)

    if a.ndim != 1 or b.ndim != 1:
        raise ValueError("cosine_similarity expects 1D vectors")
    if a.shape[0] != b.shape[0]:
        raise ValueError("cosine_similarity requires vectors with the same dimension")

    a_norm = float(np.linalg.norm(a))
    b_norm = float(np.linalg.norm(b))
    if a_norm == 0.0 or b_norm == 0.0:
        return 0.0

    similarity = float(np.dot(a, b) / (a_norm * b_norm))
    return max(-1.0, min(1.0, similarity))


def average_best_similarity(
    current_vectors: list[list[float]],
    previous_vectors: list[list[float]],
) -> float:
    if not current_vectors or not previous_vectors:
        raise ValueError("Both current_vectors and previous_vectors must be non-empty")

    current = np.asarray(current_vectors, dtype=float)
    previous = np.asarray(previous_vectors, dtype=float)

    if current.ndim != 2 or previous.ndim != 2:
        raise ValueError("average_best_similarity expects a list of 1D vectors")
    if current.shape[1] != previous.shape[1]:
        raise ValueError("Current and previous vectors must have the same dimension")

    current_norms = np.linalg.norm(current, axis=1, keepdims=True)
    previous_norms = np.linalg.norm(previous, axis=1, keepdims=True)

    current_norms[current_norms == 0.0] = 1.0
    previous_norms[previous_norms == 0.0] = 1.0

    current_unit = current / current_norms
    previous_unit = previous / previous_norms

    similarities = current_unit @ previous_unit.T
    best_matches = np.max(similarities, axis=1)
    return float(np.clip(best_matches.mean(), -1.0, 1.0))


def load_section_embeddings(
    db: Session,
    *,
    filing_id: int,
    section_name: str,
    provider: str | None = None,
    embedding_model: str | None = None,
) -> list[list[float]]:
    query = (
        select(Embedding.embedding)
        .join(FilingSection, FilingSection.id == Embedding.filing_section_id)
        .where(
            Embedding.filing_id == filing_id,
            FilingSection.section == section_name,
        )
        .order_by(FilingSection.sequence_idx.asc(), Embedding.chunk_idx.asc())
    )

    if provider is not None:
        query = query.where(Embedding.provider == provider)
    if embedding_model is not None:
        query = query.where(Embedding.embedding_model == embedding_model)

    rows = db.execute(query).all()

    return [list(row[0]) for row in rows]


def compute_section_similarity(
    db: Session,
    *,
    current_filing_id: int,
    previous_filing_id: int,
    section_name: str,
    provider: str | None = None,
    embedding_model: str | None = None,
) -> dict:
    current_vectors = load_section_embeddings(
        db,
        filing_id=current_filing_id,
        section_name=section_name,
        provider=provider,
        embedding_model=embedding_model,
    )
    previous_vectors = load_section_embeddings(
        db,
        filing_id=previous_filing_id,
        section_name=section_name,
        provider=provider,
        embedding_model=embedding_model,
    )

    if not current_vectors or not previous_vectors:
        result = SectionSimilarityResult(
            section=section_name,
            current_chunk_count=len(current_vectors),
            previous_chunk_count=len(previous_vectors),
            average_best_similarity=None,
            drift_score=None,
        )
        return result.to_dict()

    avg_similarity = average_best_similarity(current_vectors, previous_vectors)
    drift_score = normalize_drift_score(avg_similarity)

    result = SectionSimilarityResult(
        section=section_name,
        current_chunk_count=len(current_vectors),
        previous_chunk_count=len(previous_vectors),
        average_best_similarity=avg_similarity,
        drift_score=drift_score,
    )
    return result.to_dict()
