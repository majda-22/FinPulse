"""
news_client.py

Fetch company news from a free RSS source and return a standard raw article
shape for downstream normalization and storage.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
DEFAULT_NEWS_SOURCE_NAME = "google_news_rss"


class NewsClient:
    """
    Thin async client for free RSS-based company news collection.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout_sec: float = 20.0,
    ) -> None:
        self._provided_client = http_client
        self._client = http_client
        self._timeout_sec = timeout_sec

    async def __aenter__(self) -> "NewsClient":
        if self._client is None:
            settings = get_settings()
            self._client = httpx.AsyncClient(
                headers={"User-Agent": settings.edgar_user_agent},
                timeout=self._timeout_sec,
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client is not None and self._provided_client is None:
            await self._client.aclose()
        self._client = self._provided_client

    async def fetch_company_news(
        self,
        *,
        ticker: str,
        company_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        client = self._require_client()
        query = self._build_search_query(
            ticker=ticker,
            company_name=company_name,
        )
        response = await client.get(
            GOOGLE_NEWS_RSS_URL,
            params={
                "q": query,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
        )
        response.raise_for_status()

        items = self._parse_google_news_rss(
            response.text,
            ticker=ticker,
            query=query,
        )
        return items[:limit]

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use NewsClient as an async context manager")
        return self._client

    @staticmethod
    def _build_search_query(
        *,
        ticker: str,
        company_name: str | None,
    ) -> str:
        clean_ticker = ticker.strip().upper()
        clean_name = (company_name or "").strip()
        if clean_name:
            return f"\"{clean_ticker}\" OR \"{clean_name}\""
        return f"\"{clean_ticker}\""

    @staticmethod
    def _parse_google_news_rss(
        xml_text: str,
        *,
        ticker: str,
        query: str,
    ) -> list[dict[str, Any]]:
        root = ET.fromstring(xml_text)
        items: list[dict[str, Any]] = []

        for item in root.iter():
            if _local_name(item.tag) != "item":
                continue

            title = _find_child_text(item, "title")
            link = _find_child_text(item, "link")
            description = _find_child_text(item, "description")
            guid = _find_child_text(item, "guid")
            pub_date = _find_child_text(item, "pubDate")
            source_el = _find_child(item, "source")
            source_name = _text_or_none(source_el.text if source_el is not None else None)
            source_url = (
                source_el.attrib.get("url")
                if source_el is not None and isinstance(source_el.attrib, dict)
                else None
            )

            headline, publisher = _split_headline_and_publisher(title, source_name)
            items.append(
                {
                    "ticker": ticker.upper().strip(),
                    "headline": headline,
                    "summary": description,
                    "url": link,
                    "publisher": publisher,
                    "published_at": pub_date,
                    "source_name": DEFAULT_NEWS_SOURCE_NAME,
                    "raw_json": {
                        "query": query,
                        "title": title,
                        "link": link,
                        "description": description,
                        "guid": guid,
                        "pubDate": pub_date,
                        "source": {
                            "name": source_name,
                            "url": source_url,
                        },
                    },
                }
            )

        logger.info("Fetched %d raw RSS item(s) for %s", len(items), ticker.upper())
        return items


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_child(parent: ET.Element, name: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _find_child_text(parent: ET.Element, name: str) -> str | None:
    child = _find_child(parent, name)
    if child is None:
        return None
    return _text_or_none(child.text)


def _text_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _split_headline_and_publisher(
    title: str | None,
    publisher: str | None,
) -> tuple[str | None, str | None]:
    clean_title = _text_or_none(title)
    clean_publisher = _text_or_none(publisher)

    if clean_title is None:
        return None, clean_publisher
    if clean_publisher is not None:
        return clean_title, clean_publisher
    if " - " not in clean_title:
        return clean_title, None

    headline, inferred_publisher = clean_title.rsplit(" - ", 1)
    return headline.strip(), inferred_publisher.strip() or None
