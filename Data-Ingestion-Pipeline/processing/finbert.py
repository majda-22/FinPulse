from __future__ import annotations

from typing import Any, Sequence


FINBERT_MODEL_NAME = "ProsusAI/finbert"

_finbert_pipeline = None


def get_finbert_pipeline():
    global _finbert_pipeline
    if _finbert_pipeline is None:
        from transformers import pipeline

        _finbert_pipeline = pipeline(
            task="text-classification",
            model=FINBERT_MODEL_NAME,
            tokenizer=FINBERT_MODEL_NAME,
            top_k=None,
            truncation=True,
            max_length=512,
            device=-1,
        )
    return _finbert_pipeline


def normalize_finbert_batch_results(
    raw_results: Any,
    *,
    expected_count: int,
) -> list[dict[str, float] | None]:
    if expected_count == 1 and isinstance(raw_results, list) and raw_results and isinstance(raw_results[0], dict):
        raw_results = [raw_results]
    if not isinstance(raw_results, list):
        return [None] * expected_count

    normalized: list[dict[str, float] | None] = []
    for raw_result in raw_results[:expected_count]:
        normalized.append(normalize_finbert_result(raw_result))

    if len(normalized) < expected_count:
        normalized.extend([None] * (expected_count - len(normalized)))
    return normalized


def normalize_finbert_result(raw_result: Any) -> dict[str, float] | None:
    if isinstance(raw_result, dict):
        entries = [raw_result]
    elif isinstance(raw_result, list):
        if not raw_result:
            return None
        if isinstance(raw_result[0], dict):
            entries = raw_result
        elif isinstance(raw_result[0], list) and raw_result[0] and isinstance(raw_result[0][0], dict):
            entries = raw_result[0]
        else:
            return None
    else:
        return None

    scores = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    for entry in entries:
        label = str(entry.get("label", "")).lower()
        if label in scores:
            scores[label] = float(entry.get("score", 0.0))
    return scores


def score_text_batch(
    texts: Sequence[str],
    *,
    batch_size: int = 8,
    max_chars: int = 1500,
) -> list[dict[str, float] | None]:
    if not texts:
        return []

    finbert = get_finbert_pipeline()
    scored_rows: list[dict[str, float] | None] = []

    for start in range(0, len(texts), batch_size):
        batch_texts = [text[:max_chars] for text in texts[start:start + batch_size]]
        raw_results = finbert(batch_texts)
        scored_rows.extend(
            normalize_finbert_batch_results(
                raw_results,
                expected_count=len(batch_texts),
            )
        )

    return scored_rows
