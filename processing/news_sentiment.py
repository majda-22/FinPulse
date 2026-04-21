from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from processing.finbert import FINBERT_MODEL_NAME, score_text_batch


def enrich_news_items_with_sentiment(
    items: Sequence[Mapping[str, Any]],
    *,
    batch_size: int = 8,
) -> list[dict[str, Any]]:
    scored_items = [dict(item) for item in items]
    prepared_indices: list[int] = []
    prepared_texts: list[str] = []

    for index, item in enumerate(scored_items):
        article_text = _build_article_text(item)
        if article_text is None:
            continue
        prepared_indices.append(index)
        prepared_texts.append(article_text)

    if not prepared_texts:
        return scored_items

    try:
        results = score_text_batch(
            prepared_texts,
            batch_size=batch_size,
            max_chars=1200,
        )
    except Exception:
        # News ingestion should remain resilient even if the local FinBERT model
        # is unavailable or inference fails.
        return scored_items

    for item_index, result in zip(prepared_indices, results):
        if result is None:
            continue

        positive = float(result["positive"])
        negative = float(result["negative"])
        neutral = float(result["neutral"])
        sentiment_score = max(-1.0, min(1.0, positive - negative))
        label = max(
            (("positive", positive), ("negative", negative), ("neutral", neutral)),
            key=lambda entry: entry[1],
        )[0]

        item = scored_items[item_index]
        raw_json = dict(item.get("raw_json") or {}) if isinstance(item.get("raw_json"), dict) else {}
        raw_json.update(
            {
                "sentiment_score": round(sentiment_score, 6),
                "finbert_positive": round(positive, 6),
                "finbert_negative": round(negative, 6),
                "finbert_neutral": round(neutral, 6),
                "sentiment_model": FINBERT_MODEL_NAME,
            }
        )
        item["raw_json"] = raw_json
        item["sentiment_label"] = label

    return scored_items


def _build_article_text(item: Mapping[str, Any]) -> str | None:
    headline = _clean_text(item.get("headline"))
    summary = _clean_text(item.get("summary"))

    if headline is None and summary is None:
        return None
    if headline and summary and summary != headline:
        return f"{headline}. {summary}"
    return headline or summary


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None
