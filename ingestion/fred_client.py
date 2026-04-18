"""
fred_client.py

Fetch macroeconomic series from the official FRED API and normalize metadata
plus observations into a single downstream-ready observation shape.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.core.config import get_settings

DEFAULT_FRED_PROVIDER = "fred"


class FredClient:
    """
    Thin async client for series metadata and observations from FRED.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout_sec: float = 30.0,
    ) -> None:
        self._provided_client = http_client
        self._client = http_client
        self._timeout_sec = timeout_sec
        self._settings = get_settings()

    async def __aenter__(self) -> "FredClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout_sec,
                follow_redirects=True,
                headers={"User-Agent": self._settings.edgar_user_agent},
            )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client is not None and self._provided_client is None:
            await self._client.aclose()
        self._client = self._provided_client

    async def fetch_series_observations(
        self,
        *,
        series_id: str,
        start: date | None = None,
        end: date | None = None,
        provider: str = DEFAULT_FRED_PROVIDER,
    ) -> list[dict[str, Any]]:
        client = self._require_client()
        api_key = self._settings.fred_api_key.strip()
        if not api_key:
            raise RuntimeError(
                "FRED_API_KEY is required to fetch macro observations from FRED."
            )

        metadata_response = await client.get(
            f"{self._settings.fred_api_base}/series",
            params={
                "api_key": api_key,
                "file_type": "json",
                "series_id": series_id,
            },
        )
        metadata_response.raise_for_status()
        metadata = self._parse_series_metadata(
            metadata_response.json(),
            series_id=series_id,
        )

        observation_params: dict[str, Any] = {
            "api_key": api_key,
            "file_type": "json",
            "series_id": series_id,
            "sort_order": "asc",
        }
        if start is not None:
            observation_params["observation_start"] = start.isoformat()
        if end is not None:
            observation_params["observation_end"] = end.isoformat()

        observations_response = await client.get(
            f"{self._settings.fred_api_base}/series/observations",
            params=observation_params,
        )
        observations_response.raise_for_status()

        return self._parse_observations_response(
            observations_response.json(),
            provider=provider,
            metadata=metadata,
        )

    @staticmethod
    def _parse_series_metadata(
        payload: dict[str, Any],
        *,
        series_id: str,
    ) -> dict[str, str | None]:
        series_rows = payload.get("seriess") if isinstance(payload, dict) else None
        if not isinstance(series_rows, list) or not series_rows:
            raise RuntimeError(f"FRED returned no metadata for series {series_id!r}")

        row = series_rows[0]
        return {
            "series_id": str(row.get("id") or series_id),
            "frequency": _clean_text(row.get("frequency")),
            "units": _clean_text(row.get("units")),
            "title": _clean_text(row.get("title")),
        }

    @staticmethod
    def _parse_observations_response(
        payload: dict[str, Any],
        *,
        provider: str,
        metadata: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, list):
            return []

        rows: list[dict[str, Any]] = []
        for observation in observations:
            if not isinstance(observation, dict):
                continue

            observation_date = _parse_date(observation.get("date"))
            value = _parse_value(observation.get("value"))

            if observation_date is None or value is None:
                continue

            rows.append(
                {
                    "series_id": metadata["series_id"],
                    "observation_date": observation_date,
                    "value": value,
                    "provider": provider,
                    "frequency": metadata["frequency"],
                    "units": metadata["units"],
                    "title": metadata["title"],
                }
            )

        return rows

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use FredClient as an async context manager")
        return self._client


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_value(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None
