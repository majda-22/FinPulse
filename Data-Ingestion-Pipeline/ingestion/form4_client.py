from __future__ import annotations

from typing import Any, Sequence

from ingestion.edgar_client import EdgarClient, FilingMeta, build_sec_document_url

FORM4_FORMS = {"4", "4/A"}


class Form4Client:
    """
    Thin Form 4-specific wrapper around the generic EDGAR client.
    """

    def __init__(self, edgar_client: EdgarClient | None = None) -> None:
        self._provided_client = edgar_client
        self._client = edgar_client

    async def __aenter__(self) -> "Form4Client":
        if self._client is None:
            self._client = EdgarClient()
            await self._client.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        if self._client is not None and self._provided_client is None:
            await self._client.__aexit__(*args)
        self._client = self._provided_client

    async def get_recent_form4_filings(self, ticker: str, limit: int = 20) -> list[FilingMeta]:
        client = self._require_client()
        return await client.get_recent_filings(ticker, forms=FORM4_FORMS, limit=limit)

    async def get_recent_form4_for_company(self, cik: str, limit: int = 20) -> list[FilingMeta]:
        client = self._require_client()
        return await client.get_recent_filings_by_cik(cik, forms=FORM4_FORMS, limit=limit)

    async def get_form4_xml(
        self,
        *,
        accession_number: str,
        cik: str,
        primary_document: str | None = None,
    ) -> str:
        client = self._require_client()
        candidates = self._candidate_xml_documents(
            primary_document=primary_document,
            filing_index=await client.get_filing_index(cik, accession_number),
        )

        if primary_document and primary_document not in candidates:
            candidates.append(primary_document)

        for candidate in candidates:
            document_url = build_sec_document_url(
                cik=str(cik).strip().zfill(10),
                accession=accession_number,
                primary_document=candidate,
            )
            if document_url is None:
                continue

            document_text = await client.get_document_text(document_url)
            if _looks_like_ownership_xml(document_text):
                return document_text

        raise RuntimeError(
            f"Unable to locate ownership XML for Form 4 accession {accession_number!r}"
        )

    @staticmethod
    def filter_recent_form4_filings(
        filings: Sequence[FilingMeta],
        *,
        limit: int | None = None,
    ) -> list[FilingMeta]:
        filtered = [filing for filing in filings if filing.form_type in FORM4_FORMS]
        if limit is not None:
            return filtered[:limit]
        return filtered

    def _require_client(self) -> EdgarClient:
        if self._client is None:
            raise RuntimeError("Use Form4Client as an async context manager")
        return self._client

    @staticmethod
    def _candidate_xml_documents(
        *,
        primary_document: str | None,
        filing_index: dict[str, Any],
    ) -> list[str]:
        preferred: list[str] = []
        secondary: list[str] = []
        seen: set[str] = set()

        if primary_document and primary_document.lower().endswith(".xml"):
            preferred.append(primary_document)
            seen.add(primary_document)

        directory = filing_index.get("directory") if isinstance(filing_index, dict) else None
        items = directory.get("item") if isinstance(directory, dict) else None
        if not isinstance(items, list):
            return preferred

        for item in items:
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue

            lower_name = name.lower()
            if not lower_name.endswith(".xml"):
                continue
            if lower_name.endswith(".xsd"):
                continue
            if lower_name in {"index.xml", "primary_doc.xml"}:
                pass

            if name in seen:
                continue
            seen.add(name)

            basename = lower_name.rsplit("/", 1)[-1]
            if "ownership" in basename or "form4" in basename or basename.startswith("doc4"):
                preferred.append(name)
            else:
                secondary.append(name)

        return preferred + secondary


def _looks_like_ownership_xml(text: str) -> bool:
    sample = text.lstrip()[:500].lower()
    return sample.startswith("<?xml") or "<ownershipdocument" in sample
