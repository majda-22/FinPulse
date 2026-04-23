"""
news_normalizer.py

Clean raw news articles, normalize dates and text fields, compute a stable
dedupe hash, and reject empty or low-signal entries before storage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

UNRELIABLE_DEDUPE_HOSTS = {
    "google.com",
    "www.google.com",
    "news.google.com",
}
TRACKING_QUERY_KEYS = {
    "guccounter",
    "guce_referrer",
    "guce_referrer_sig",
    "oc",
}


def normalize_news_items(
    raw_items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for raw_item in raw_items:
        clean = normalize_news_item(raw_item)
        if clean is not None:
            normalized.append(clean)

    return normalized


def normalize_news_item(
    raw_item: Mapping[str, Any],
) -> dict[str, Any] | None:
    ticker = _clean_text(raw_item.get("ticker"))
    headline = _clean_text(raw_item.get("headline"))
    summary = _clean_text(_strip_html(raw_item.get("summary")))
    url = _canonicalize_url(raw_item.get("url"))
    publisher = _clean_text(raw_item.get("publisher"))
    published_at = _normalize_datetime(raw_item.get("published_at"))
    source_name = _clean_text(raw_item.get("source_name")) or "rss"
    retrieved_at = _normalize_datetime(raw_item.get("retrieved_at")) or datetime.now(
        timezone.utc
    )

    if ticker is None or headline is None or url is None or published_at is None:
        return None
    if _is_garbage_article(headline=headline, summary=summary):
        return None

    if summary == headline:
        summary = None

    dedupe_hash = build_news_dedupe_hash(
        url=url,
        publisher=publisher,
        headline=headline,
        published_at=published_at,
    )

    return {
        "ticker": ticker.upper(),
        "headline": headline,
        "summary": summary,
        "url": url,
        "publisher": publisher,
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "source_name": source_name,
        "dedupe_hash": dedupe_hash,
        "sentiment_label": _clean_text(raw_item.get("sentiment_label")),
        "raw_json": raw_item.get("raw_json")
        if isinstance(raw_item.get("raw_json"), dict)
        else None,
    }


def build_news_dedupe_hash(
    *,
    url: str,
    publisher: str | None,
    headline: str,
    published_at: datetime,
) -> str:
    host = urlsplit(url).netloc.lower()
    if host and host not in UNRELIABLE_DEDUPE_HOSTS:
        basis = f"url:{url.lower()}"
    else:
        basis = "|".join(
            [
                (publisher or "").strip().lower(),
                headline.strip().lower(),
                published_at.astimezone(timezone.utc).isoformat(),
            ]
        )

    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _is_garbage_article(
    *,
    headline: str,
    summary: str | None,
) -> bool:
    clean_headline = headline.strip()
    if len(clean_headline) < 8:
        return True

    lowered = clean_headline.lower()
    if lowered in {"untitled", "no title", "rss"}:
        return True

    if summary is None:
        return False

    return clean_headline.lower() == summary.strip().lower() and len(clean_headline) < 20


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = _clean_text(value)
        if text is None:
            return None

        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _canonicalize_url(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None

    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return None

    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_pairs), doseq=True)

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "",
            query,
            "",
        )
    )


def _strip_html(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    return BeautifulSoup(html.unescape(text), "lxml").get_text(" ", strip=True)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value)
    text = html.unescape(text)
    text = " ".join(text.split())
    return text or None
