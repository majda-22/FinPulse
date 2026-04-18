"""
ingestion/edgar_client.py

Async EDGAR client for FinPulse.

Primary filing source:
- SEC company_tickers.json for ticker -> CIK
- SEC submissions JSON for recent filings
- SEC companyfacts JSON for XBRL facts

This version is aligned with:
- app.core.config
- pipeline.py using get_recent_filings(...)
- pipeline.py using get_filing_text(...)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions"
XBRL_URL = "https://data.sec.gov/api/xbrl/companyfacts"

SUPPORTED_FORMS = {"10-K", "10-Q", "8-K", "4", "4/A", "DEF 14A", "SC 13G", "SC 13D"}

_ticker_to_cik_cache: dict[str, str] = {}


@dataclass(slots=True)
class CompanyMeta:
    cik: str                 # zero-padded 10-digit CIK
    ticker: str
    name: str
    sic_code: Optional[str]
    sic_description: Optional[str]
    exchange: Optional[str]


@dataclass(slots=True)
class FilingMeta:
    accession_number: str
    cik: str                 # zero-padded 10-digit CIK
    ticker: str
    form_type: str
    filed_at: date
    period_of_report: Optional[date]
    primary_document: Optional[str]
    document_url: Optional[str]
    file_size_bytes: Optional[int] = None


class _TokenBucket:
    def __init__(self, rate: float = 8.0) -> None:
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class EdgarClient:
    def __init__(
        self,
        user_agent: Optional[str] = None,
        rate: Optional[float] = None,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()

        ua = user_agent or settings.edgar_user_agent
        request_rate = rate if rate is not None else settings.edgar_rate_limit

        self._headers = {
            "User-Agent": ua,
            "Accept-Encoding": "gzip, deflate",
        }
        self._bucket = _TokenBucket(request_rate)
        self._max_retries = max_retries
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "EdgarClient":
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client is not None:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve_cik(self, ticker: str) -> str:
        """
        Resolve a ticker to a 10-digit zero-padded CIK string.
        Example: AAPL -> 0000320193
        """
        ticker_upper = ticker.upper().strip()

        if ticker_upper in _ticker_to_cik_cache:
            return _ticker_to_cik_cache[ticker_upper]

        data = await self._get_json(TICKERS_URL)

        for entry in data.values():
            entry_ticker = str(entry.get("ticker", "")).upper().strip()
            cik_raw = str(entry.get("cik_str", "")).strip()

            if entry_ticker and cik_raw:
                _ticker_to_cik_cache[entry_ticker] = cik_raw.zfill(10)

        cik = _ticker_to_cik_cache.get(ticker_upper)
        if not cik:
            raise ValueError(f"Ticker {ticker!r} not found in SEC ticker map")

        return cik

    async def get_company_meta(self, ticker: str) -> CompanyMeta:
        """
        Fetch company metadata from SEC submissions JSON.
        """
        cik = await self.resolve_cik(ticker)
        return await self.get_company_meta_by_cik(cik, ticker=ticker)

    async def get_company_meta_by_cik(
        self,
        cik: str,
        *,
        ticker: Optional[str] = None,
    ) -> CompanyMeta:
        """
        Fetch company metadata directly from SEC submissions JSON using a known CIK.
        """
        cik = str(cik).strip().zfill(10)
        data = await self._get_json(f"{SUBMISSIONS_URL}/CIK{cik}.json")

        exchanges = data.get("exchanges") or []
        exchange = exchanges[0] if exchanges else None

        sic = data.get("sic")
        resolved_ticker = (ticker or _first_ticker(data) or cik).upper().strip()
        return CompanyMeta(
            cik=cik,
            ticker=resolved_ticker,
            name=str(data.get("name", "")).strip(),
            sic_code=str(sic) if sic is not None else None,
            sic_description=data.get("sicDescription"),
            exchange=exchange,
        )

    async def get_recent_filings(
        self,
        ticker: str,
        forms: Optional[set[str]] = None,
        limit: int = 20,
    ) -> list[FilingMeta]:
        """
        Fetch recent filings for a company from SEC submissions JSON.
        This is the main ingestion path for the project.
        """
        if limit <= 0:
            return []

        cik = await self.resolve_cik(ticker)
        return await self.get_recent_filings_by_cik(
            cik,
            ticker=ticker,
            forms=forms,
            limit=limit,
        )

    async def get_recent_filings_by_cik(
        self,
        cik: str,
        *,
        ticker: Optional[str] = None,
        forms: Optional[set[str]] = None,
        limit: int = 20,
    ) -> list[FilingMeta]:
        """
        Fetch recent filings using a known CIK.
        """
        if limit <= 0:
            return []

        padded_cik = str(cik).strip().zfill(10)
        data = await self._get_json(f"{SUBMISSIONS_URL}/CIK{padded_cik}.json")

        recent = data.get("filings", {}).get("recent", {})
        if not recent:
            return []

        accession_numbers = recent.get("accessionNumber", [])
        form_types = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])
        size_values = recent.get("size", [])

        n = min(
            len(accession_numbers),
            len(form_types),
            len(filing_dates),
        )

        requested_forms = {f.upper() for f in forms} if forms else None
        resolved_ticker = (ticker or _first_ticker(data) or "").upper().strip()
        results: list[FilingMeta] = []

        for i in range(n):
            accession = accession_numbers[i]
            form_type = str(form_types[i]).strip().upper()

            if requested_forms and form_type not in requested_forms:
                continue

            if form_type not in SUPPORTED_FORMS:
                continue

            if not accession:
                continue

            filed_at = _safe_date(filing_dates[i])
            if filed_at is None:
                logger.warning("Skipping filing with invalid filingDate: %s", accession)
                continue

            period_of_report = None
            if i < len(report_dates):
                period_of_report = _safe_date(report_dates[i])

            primary_document = None
            if i < len(primary_docs):
                primary_document = str(primary_docs[i]).strip() or None

            file_size_bytes = None
            if i < len(size_values):
                file_size_bytes = _safe_int(size_values[i])

            results.append(
                FilingMeta(
                    accession_number=accession,
                    cik=padded_cik,
                    ticker=resolved_ticker,
                    form_type=form_type,
                    filed_at=filed_at,
                    period_of_report=period_of_report,
                    primary_document=primary_document,
                    document_url=build_sec_document_url(
                        cik=padded_cik,
                        accession=accession,
                        primary_document=primary_document,
                    ),
                    file_size_bytes=file_size_bytes,
                )
            )

            if len(results) >= limit:
                break

        return results

    async def get_filing_text(self, filing: FilingMeta) -> str:
        """
        Download the raw primary filing document and return decoded text.
        """
        if not filing.document_url:
            raise ValueError(
                f"No document URL available for accession {filing.accession_number}"
            )

        return await self.get_document_text(filing.document_url)

    async def get_document_text(self, url: str) -> str:
        raw = await self._fetch_bytes(url)
        return raw.decode("utf-8", errors="replace")

    async def get_xbrl_facts(self, cik: str) -> dict:
        """
        Fetch XBRL company facts JSON.
        Accepts padded or unpadded CIK.
        """
        padded = str(cik).strip().lstrip("0").zfill(10)
        return await self._get_json(f"{XBRL_URL}/CIK{padded}.json")

    async def get_filing_index(self, cik: str, accession: str) -> dict:
        """
        Fetch the SEC filing directory index JSON for one accession.
        """
        index_url = build_sec_filing_index_url(cik=cik, accession=accession)
        return await self._get_json(index_url)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_json(self, url: str, params: Optional[dict] = None) -> dict:
        response = await self._request("GET", url, params=params)
        return response.json()

    async def _fetch_bytes(self, url: str) -> bytes:
        response = await self._request("GET", url)
        return response.content

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Use EdgarClient as an async context manager")

        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries):
            await self._bucket.acquire()

            try:
                response = await self._client.request(method, url, params=params)

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "15"))
                    logger.warning("SEC rate limit hit, sleeping %ss", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code in {500, 502, 503, 504}:
                    wait = 2 ** attempt
                    logger.warning(
                        "SEC server error %s on %s, retry %s in %ss",
                        response.status_code,
                        url,
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                response.raise_for_status()
                return response

            except httpx.TransportError as exc:
                last_error = exc
                if attempt == self._max_retries - 1:
                    break

                wait = 2 ** attempt
                logger.warning(
                    "Transport error on %s: %s. Retry %s in %ss",
                    url,
                    exc,
                    attempt + 1,
                    wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"Request failed after {self._max_retries} attempts: {url}"
        ) from last_error

    @staticmethod
    def build_document_url(
        cik: str,
        accession: str,
        primary_document: Optional[str],
    ) -> Optional[str]:
        return build_sec_document_url(cik=cik, accession=accession, primary_document=primary_document)


def _safe_date(value: object) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _safe_int(value: object) -> Optional[int]:
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_ticker(data: dict) -> Optional[str]:
    tickers = data.get("tickers")
    if isinstance(tickers, list) and tickers:
        ticker = str(tickers[0]).strip()
        return ticker or None
    return None


def build_sec_document_url(
    *,
    cik: str,
    accession: str,
    primary_document: Optional[str],
) -> Optional[str]:
    if not accession:
        return None

    cik_unpadded = str(int(cik))
    accession_nodash = accession.replace("-", "")

    if primary_document:
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_unpadded}/{accession_nodash}/{primary_document}"
        )

    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_unpadded}/{accession_nodash}/{accession_nodash}.txt"
    )


def build_sec_filing_index_url(
    *,
    cik: str,
    accession: str,
) -> str:
    cik_unpadded = str(int(cik))
    accession_nodash = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_unpadded}/{accession_nodash}/index.json"
    )
