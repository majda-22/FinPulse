"""
market_client.py

Fetch daily market OHLCV history from a free market data source and return a
normalized daily-bar shape for downstream storage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_MARKET_PROVIDER = "yahoo_chart"


class MarketClient:
    """
    Thin async client for daily OHLCV history.
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

    async def __aenter__(self) -> "MarketClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout_sec,
                follow_redirects=True,
                headers={"User-Agent": "FinPulse market pipeline"},
            )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client is not None and self._provided_client is None:
            await self._client.aclose()
        self._client = self._provided_client

    async def fetch_daily_history(
        self,
        *,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
        provider: str = DEFAULT_MARKET_PROVIDER,
    ) -> list[dict[str, Any]]:
        client = self._require_client()

        end_date = end or date.today()
        start_date = start or (end_date - timedelta(days=365))
        if start_date > end_date:
            raise ValueError("start date must be on or before end date")

        response = await client.get(
            YAHOO_CHART_URL.format(symbol=symbol.upper()),
            params={
                "interval": "1d",
                "includeAdjustedClose": "true",
                "period1": _to_epoch_seconds(start_date),
                "period2": _to_epoch_seconds(end_date + timedelta(days=1)),
            },
        )
        response.raise_for_status()

        return self._parse_chart_response(
            response.json(),
            symbol=symbol.upper(),
            provider=provider,
        )

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use MarketClient as an async context manager")
        return self._client

    @staticmethod
    def _parse_chart_response(
        payload: dict[str, Any],
        *,
        symbol: str,
        provider: str,
    ) -> list[dict[str, Any]]:
        chart = payload.get("chart") if isinstance(payload, dict) else None
        errors = chart.get("error") if isinstance(chart, dict) else None
        if errors:
            raise RuntimeError(f"Yahoo chart API error for {symbol}: {errors}")

        results = chart.get("result") if isinstance(chart, dict) else None
        if not isinstance(results, list) or not results:
            return []

        result = results[0]
        meta = result.get("meta") if isinstance(result, dict) else {}
        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quotes = indicators.get("quote") or []
        adjclose_rows = indicators.get("adjclose") or []

        quote = quotes[0] if quotes and isinstance(quotes[0], dict) else {}
        if not timestamps or not quote:
            raise RuntimeError(
                "No historical market data returned for "
                f"{symbol} from {provider}. "
                f"validRanges={meta.get('validRanges')!r}, "
                f"firstTradeDate={meta.get('firstTradeDate')!r}, "
                f"regularMarketPrice={meta.get('regularMarketPrice')!r}"
            )

        adjclose = adjclose_rows[0] if adjclose_rows and isinstance(adjclose_rows[0], dict) else {}

        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        adjusted_closes = adjclose.get("adjclose") or []

        rows: list[dict[str, Any]] = []

        for idx, timestamp in enumerate(timestamps):
            try:
                trading_date = datetime.fromtimestamp(
                    int(timestamp),
                    tz=timezone.utc,
                ).date()
            except (TypeError, ValueError, OSError):
                continue

            row = {
                "ticker": symbol,
                "trading_date": trading_date,
                "open": _coerce_float(_get_by_index(opens, idx)),
                "high": _coerce_float(_get_by_index(highs, idx)),
                "low": _coerce_float(_get_by_index(lows, idx)),
                "close": _coerce_float(_get_by_index(closes, idx)),
                "adjusted_close": _coerce_float(_get_by_index(adjusted_closes, idx)),
                "volume": _coerce_int(_get_by_index(volumes, idx)),
                "provider": provider,
            }

            if row["adjusted_close"] is None:
                row["adjusted_close"] = row["close"]
            if all(row[field] is None for field in ("open", "high", "low", "close", "volume")):
                continue

            rows.append(row)

        return rows


def _to_epoch_seconds(value: date) -> int:
    return int(datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc).timestamp())


def _get_by_index(values: list[Any], idx: int) -> Any:
    if idx >= len(values):
        return None
    return values[idx]


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
