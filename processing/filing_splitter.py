"""
processing/filing_splitter.py — Phase 2

Reads a raw filing from file_store, extracts structured sections
(Risk Factors, MD&A, Forward-Looking Statements, Business),
and writes them to the filing_sections table.

Sets filing.is_extracted = True on success.
Sets filing.processing_status = "failed" + last_error_message on failure.

Usage — standalone:
    python -m processing.filing_splitter --ticker AAPL
    python -m processing.filing_splitter --filing-id 3
    python -m processing.filing_splitter --all-pending

Usage — from pipeline.py or another module:
    from processing.filing_splitter import split_filing
    split_filing(filing_id=42)
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.models.pipeline_event import PipelineEvent
from app.db.session import get_db
from ingestion.file_store import FileStore

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "1.0.0"


# -----------------------------------------------------------------------------
# Section definitions
# -----------------------------------------------------------------------------

# Canonical annual item map for robust sequential extraction.
# We first detect document headings in order, then slice text between them.
ANNUAL_ITEM_SECTION_MAP: dict[str, str] = {
    "1": "business",
    "1A": "risk_factors",
    "7": "mda",
}

QUARTERLY_ITEM_SECTION_MAP: dict[str, str] = {
    "1A": "risk_factors",
    "2": "mda",
}

# Optional non-item section patterns.
# These are extracted independently if found and sufficiently long.
EXTRA_SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "forward_looking",
        [
            r"forward[-\s]looking statements",
            r"special note regarding forward",
            r"cautionary statement",
            r"cautionary language",
        ],
    ),
]

# Strong heading patterns for SEC filings.
ITEM_HEADING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("1", re.compile(r"^\s*item\s*1\b", re.IGNORECASE)),
    ("1A", re.compile(r"^\s*item\s*1a\b", re.IGNORECASE)),
    ("1B", re.compile(r"^\s*item\s*1b\b", re.IGNORECASE)),
    ("1C", re.compile(r"^\s*item\s*1c\b", re.IGNORECASE)),
    ("2", re.compile(r"^\s*item\s*2\b", re.IGNORECASE)),
    ("3", re.compile(r"^\s*item\s*3\b", re.IGNORECASE)),
    ("4", re.compile(r"^\s*item\s*4\b", re.IGNORECASE)),
    ("5", re.compile(r"^\s*item\s*5\b", re.IGNORECASE)),
    ("6", re.compile(r"^\s*item\s*6\b", re.IGNORECASE)),
    ("7", re.compile(r"^\s*item\s*7\b", re.IGNORECASE)),
    ("7A", re.compile(r"^\s*item\s*7a\b", re.IGNORECASE)),
    ("8", re.compile(r"^\s*item\s*8\b", re.IGNORECASE)),
    ("9", re.compile(r"^\s*item\s*9\b", re.IGNORECASE)),
    ("9A", re.compile(r"^\s*item\s*9a\b", re.IGNORECASE)),
    ("10", re.compile(r"^\s*item\s*10\b", re.IGNORECASE)),
    ("11", re.compile(r"^\s*item\s*11\b", re.IGNORECASE)),
    ("12", re.compile(r"^\s*item\s*12\b", re.IGNORECASE)),
    ("13", re.compile(r"^\s*item\s*13\b", re.IGNORECASE)),
    ("14", re.compile(r"^\s*item\s*14\b", re.IGNORECASE)),
    ("15", re.compile(r"^\s*item\s*15\b", re.IGNORECASE)),
]

STOP_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsignatures\b", re.IGNORECASE),
    re.compile(r"\bexhibit\s+index\b", re.IGNORECASE),
]


# -----------------------------------------------------------------------------
# Result dataclasses
# -----------------------------------------------------------------------------

@dataclass
class ExtractedSection:
    section: str
    sequence_idx: int
    text: str
    char_count: int


@dataclass
class SplitResult:
    filing_id: int
    sections: list[ExtractedSection]
    warnings: list[str]


@dataclass
class TextBlock:
    idx: int
    text: str


@dataclass
class HeadingMatch:
    block_idx: int
    item_code: str
    section_key: Optional[str]
    heading_text: str


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def split_filing(
    filing_id: int,
    db: Optional[Session] = None,
) -> SplitResult:
    """
    Extract sections from one filing and persist to filing_sections.
    Can be called with an existing session or standalone.
    """
    own_session = db is None
    if own_session:
        ctx = get_db()
        db = ctx.__enter__()

    try:
        assert db is not None
        result = _split_filing_inner(filing_id, db)
        if own_session:
            ctx.__exit__(None, None, None)
        return result
    except Exception as exc:
        if own_session:
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise


def split_all_pending(limit: int = 100) -> dict:
    summary = {"processed": 0, "skipped": 0, "failed": 0, "total_sections": 0}

    with get_db() as db:
        pending_ids = db.scalars(
            select(Filing.id)
            .where(Filing.is_extracted == False)  # noqa: E712
            .order_by(Filing.filed_at.desc())
            .limit(limit)
        ).all()

    logger.info("Found %d pending filings to extract", len(pending_ids))

    for filing_id in pending_ids:
        try:
            result = split_filing(filing_id)
            if "already_extracted" in result.warnings:
                summary["skipped"] += 1
            else:
                summary["processed"] += 1
                summary["total_sections"] += len(result.sections)
        except Exception as exc:
            logger.error("Failed to split filing %d: %s", filing_id, exc)
            summary["failed"] += 1

    return summary


def split_by_ticker(ticker: str, form_type: str = "10-K") -> dict:
    with get_db() as db:
        company = db.scalar(
            select(Company).where(Company.ticker == ticker.upper())
        )
        if company is None:
            raise ValueError(f"Company with ticker {ticker!r} not found in DB")

        filing_ids = db.scalars(
            select(Filing.id)
            .where(
                Filing.company_id == company.id,
                Filing.form_type == form_type,
                Filing.is_extracted == False,  # noqa: E712
            )
            .order_by(Filing.filed_at.desc())
        ).all()

    logger.info("Processing %d %s filings for %s", len(filing_ids), form_type, ticker)

    summary = {"ticker": ticker, "processed": 0, "failed": 0, "sections": []}

    for fid in filing_ids:
        try:
            result = split_filing(fid)
            summary["processed"] += 1
            summary["sections"].extend([s.section for s in result.sections])
        except Exception as exc:
            logger.error("Failed filing %d: %s", fid, exc)
            summary["failed"] += 1

    return summary


# -----------------------------------------------------------------------------
# Core implementation
# -----------------------------------------------------------------------------

def _split_filing_inner(filing_id: int, db: Session) -> SplitResult:
    t0 = time.monotonic()

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    if filing.is_extracted:
        logger.info("Filing %d already extracted — skipping", filing_id)
        return SplitResult(
            filing_id=filing_id,
            sections=[],
            warnings=["already_extracted"],
        )

    logger.info(
        "Splitting filing id=%d  %s  %s  %s",
        filing_id,
        filing.form_type,
        filing.accession_number,
        filing.filed_at,
    )

    store = FileStore()
    try:
        raw_text = store.get(filing.raw_s3_key)
    except FileNotFoundError:
        error = f"Raw file not found: {filing.raw_s3_key}"
        _mark_failed(db, filing, error)
        raise RuntimeError(error)

    warnings: list[str] = []

    if _looks_like_html(raw_text):
        sections = _extract_from_html(raw_text, filing.form_type, warnings)
    else:
        sections = _extract_from_text(raw_text, filing.form_type, warnings)

    if not sections:
        warnings.append("no_sections_found")
        logger.warning(
            "No sections extracted from filing %d (%s)",
            filing_id,
            filing.accession_number,
        )

        filing.is_extracted = False
        filing.processing_status = "failed"
        filing.last_error_message = "no_sections_found"
        db.flush()

        duration_ms = int((time.monotonic() - t0) * 1000)
        db.add(
            PipelineEvent(
                filing_id=filing_id,
                company_id=filing.company_id,
                layer="processing",
                event_type="failed",
                duration_ms=duration_ms,
                detail={
                    "step": "filing_splitter",
                    "reason": "no_sections_found",
                    "warnings": warnings,
                    "extractor": EXTRACTOR_VERSION,
                    "accession": filing.accession_number,
                },
            )
        )
        db.flush()

        return SplitResult(filing_id=filing_id, sections=[], warnings=warnings)

    _replace_filing_sections(db, filing, sections)

    filing.is_extracted = True
    filing.processing_status = "extracted"
    filing.last_error_message = None
    db.flush()

    duration_ms = int((time.monotonic() - t0) * 1000)
    db.add(
        PipelineEvent(
            filing_id=filing_id,
            company_id=filing.company_id,
            layer="processing",
            event_type="extracted",
            duration_ms=duration_ms,
            detail={
                "sections_found": [s.section for s in sections],
                "section_count": len(sections),
                "warnings": warnings,
                "extractor": EXTRACTOR_VERSION,
                "accession": filing.accession_number,
            },
        )
    )
    db.flush()

    logger.info(
        "Extracted %d section(s) from filing %d in %dms: %s",
        len(sections),
        filing_id,
        duration_ms,
        [s.section for s in sections],
    )

    return SplitResult(filing_id=filing_id, sections=sections, warnings=warnings)


def _replace_filing_sections(
    db: Session,
    filing: Filing,
    sections: list[ExtractedSection],
) -> None:
    existing_rows = db.scalars(
        select(FilingSection).where(FilingSection.filing_id == filing.id)
    ).all()

    for row in existing_rows:
        db.delete(row)

    db.flush()

    for sec in sections:
        db.add(
            FilingSection(
                filing_id=filing.id,
                company_id=filing.company_id,
                section=sec.section,
                sequence_idx=sec.sequence_idx,
                text=sec.text,
                extractor_version=EXTRACTOR_VERSION,
            )
        )

    db.flush()


# -----------------------------------------------------------------------------
# HTML extraction
# -----------------------------------------------------------------------------

def _extract_from_html(
    raw: str,
    form_type_or_warnings: Optional[str | list[str]] = None,
    warnings: Optional[list[str]] = None,
) -> list[ExtractedSection]:
    # Keep compatibility with tests and older callers that passed
    # `(raw, form_type, warnings)` even though `form_type` is unused here.
    if warnings is None:
        if isinstance(form_type_or_warnings, list):
            warnings = form_type_or_warnings
        else:
            warnings = []

    form_type = form_type_or_warnings if isinstance(form_type_or_warnings, str) else None
    section_map = _section_map_for_form_type(form_type)

    soup = BeautifulSoup(raw, "lxml")

    # Remove obvious noise.
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    # Remove hidden ix header blocks and hidden display blocks.
    for tag in soup.find_all():
        if not isinstance(tag, Tag):
            continue

        tag_name = (tag.name or "").lower()

        if tag_name == "ix:header":
            tag.decompose()
            continue

        style = tag.attrs.get("style", "") if tag.attrs is not None else ""
        if isinstance(style, str) and "display:none" in style.lower():
            tag.decompose()

    blocks = _html_to_blocks(soup)
    if not blocks:
        warnings.append("html_no_blocks_found")
        return []

    results: list[ExtractedSection] = []

    # Primary extraction by ordered SEC item headings.
    heading_matches = _find_item_headings(blocks, section_map=section_map)

    if heading_matches:
        results.extend(
            _extract_sections_from_headings(
                blocks,
                heading_matches,
                warnings,
                needed_sections=set(section_map.values()),
            )
        )
    else:
        warnings.append("item_headings_not_found")

    # Secondary extraction for optional sections not tied to item numbering.
    extra_sections = _extract_extra_sections_from_blocks(
        blocks=blocks,
        already_have={r.section for r in results},
        warnings=warnings,
    )
    results.extend(extra_sections)

    return results


def _html_to_blocks(soup: BeautifulSoup) -> list[TextBlock]:
    wanted_tags = {"p", "div", "h1", "h2", "h3", "h4", "li"}
    blocks: list[TextBlock] = []

    idx = 0
    for el in soup.find_all(list(wanted_tags)):
        if not isinstance(el, Tag):
            continue

        text = el.get_text(separator=" ", strip=True)
        text = _normalize_text(text)

        if len(text) < 8:
            continue

        blocks.append(TextBlock(idx=idx, text=text))
        idx += 1

    return blocks


def _find_item_headings(
    blocks: list[TextBlock],
    *,
    section_map: dict[str, str],
) -> list[HeadingMatch]:
    matches: list[HeadingMatch] = []

    for block in blocks:
        clean = _clean_heading_text(block.text)

        # Headings should be short-ish.
        if len(clean) > 220:
            continue

        for item_code, pattern in ITEM_HEADING_PATTERNS:
            if pattern.match(clean):
                section_key = section_map.get(item_code)
                matches.append(
                    HeadingMatch(
                        block_idx=block.idx,
                        item_code=item_code,
                        section_key=section_key,
                        heading_text=clean,
                    )
                )
                break

    matches.sort(key=lambda m: m.block_idx)
    return matches


def _extract_sections_from_headings(
    blocks: list[TextBlock],
    heading_matches: list[HeadingMatch],
    warnings: list[str],
    *,
    needed_sections: set[str],
) -> list[ExtractedSection]:
    results: list[ExtractedSection] = []
    section_counts: dict[str, int] = {}
    block_index_map = {b.idx: i for i, b in enumerate(blocks)}

    for i, heading in enumerate(heading_matches):
        if heading.section_key is None:
            continue

        start_pos = block_index_map.get(heading.block_idx)
        if start_pos is None:
            continue

        end_pos = len(blocks)
        for j in range(i + 1, len(heading_matches)):
            next_pos = block_index_map.get(heading_matches[j].block_idx)
            if next_pos is not None and next_pos > start_pos:
                end_pos = next_pos
                break

        body = _collect_blocks_between(blocks, start_pos + 1, end_pos)

        if len(body) < 200:
            continue

        seq = section_counts.get(heading.section_key, 0)
        section_counts[heading.section_key] = seq + 1

        results.append(
            ExtractedSection(
                section=heading.section_key,
                sequence_idx=seq,
                text=body,
                char_count=len(body),
            )
        )

    # Record missing key sections.
    found_sections = {r.section for r in results}
    for needed in needed_sections:
        if needed not in found_sections:
            warnings.append(f"section_not_found:{needed}")

    return results


def _extract_extra_sections_from_blocks(
    blocks: list[TextBlock],
    already_have: set[str],
    warnings: list[str],
) -> list[ExtractedSection]:
    results: list[ExtractedSection] = []

    for section_key, patterns in EXTRA_SECTION_PATTERNS:
        if section_key in already_have:
            continue

        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        heading_pos: Optional[int] = None

        for idx, block in enumerate(blocks):
            clean = _clean_heading_text(block.text)
            if len(clean) > 220:
                continue
            if any(p.search(clean) for p in compiled):
                heading_pos = idx
                break

        if heading_pos is None:
            continue

        end_pos = len(blocks)
        for idx in range(heading_pos + 1, len(blocks)):
            clean = _clean_heading_text(blocks[idx].text)
            if len(clean) <= 220:
                if _looks_like_item_heading(clean) or any(p.search(clean) for p in STOP_TEXT_PATTERNS):
                    end_pos = idx
                    break

        body = _collect_blocks_between(blocks, heading_pos + 1, end_pos)
        if len(body) < 200:
            warnings.append(f"section_too_short:{section_key}:{len(body)}")
            continue

        results.append(
            ExtractedSection(
                section=section_key,
                sequence_idx=0,
                text=body,
                char_count=len(body),
            )
        )

    return results


def _collect_blocks_between(
    blocks: list[TextBlock],
    start_idx: int,
    end_idx: int,
    max_chars: int = 300_000,
) -> str:
    collected: list[str] = []
    char_count = 0

    for idx in range(start_idx, min(end_idx, len(blocks))):
        text = blocks[idx].text
        clean = _clean_heading_text(text)

        if len(clean) <= 220:
            if _looks_like_item_heading(clean) or any(p.search(clean) for p in STOP_TEXT_PATTERNS):
                break

        collected.append(text)
        char_count += len(text)

        if char_count >= max_chars:
            break

    return _join_text(collected)


# -----------------------------------------------------------------------------
# Plain text extraction
# -----------------------------------------------------------------------------

def _extract_from_text(
    raw: str,
    form_type_or_warnings: Optional[str | list[str]] = None,
    warnings: Optional[list[str]] = None,
) -> list[ExtractedSection]:
    # Keep compatibility with tests and older callers that passed
    # `(raw, form_type, warnings)` even though `form_type` is unused here.
    if warnings is None:
        if isinstance(form_type_or_warnings, list):
            warnings = form_type_or_warnings
        else:
            warnings = []

    form_type = form_type_or_warnings if isinstance(form_type_or_warnings, str) else None
    section_map = _section_map_for_form_type(form_type)

    lines = [_normalize_text(line) for line in raw.splitlines()]
    lines = [line for line in lines if line]

    if not lines:
        warnings.append("text_empty")
        return []

    blocks = [TextBlock(idx=i, text=line) for i, line in enumerate(lines)]
    heading_matches = _find_item_headings(blocks, section_map=section_map)

    results: list[ExtractedSection] = []
    if heading_matches:
        results.extend(
            _extract_sections_from_headings(
                blocks,
                heading_matches,
                warnings,
                needed_sections=set(section_map.values()),
            )
        )
    else:
        warnings.append("text_item_headings_not_found")

    extra_sections = _extract_extra_sections_from_blocks(
        blocks=blocks,
        already_have={r.section for r in results},
        warnings=warnings,
    )
    results.extend(extra_sections)

    return results


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def _looks_like_html(text: str) -> bool:
    sample = text[:5000].lower()
    return "<html" in sample or "<body" in sample or "<div" in sample or "<table" in sample


def _looks_like_item_heading(text: str) -> bool:
    return any(pattern.search(text) for _, pattern in ITEM_HEADING_PATTERNS)


def _section_map_for_form_type(form_type: Optional[str]) -> dict[str, str]:
    normalized = (form_type or "").upper()
    if normalized in {"10-Q", "10-Q/A"}:
        return QUARTERLY_ITEM_SECTION_MAP
    return ANNUAL_ITEM_SECTION_MAP


def _clean_heading_text(text: str) -> str:
    text = _normalize_text(text)
    # Normalize curly apostrophes etc.
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return text


def _normalize_text(text: str) -> str:
    text = "".join(ch if ch.isprintable() or ch.isspace() else " " for ch in text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _join_text(parts: list[str]) -> str:
    joined = " ".join(p.strip() for p in parts if p and p.strip())
    joined = re.sub(r"\s{2,}", " ", joined)
    return joined.strip()


def _mark_failed(db: Session, filing: Filing, error: str) -> None:
    filing.processing_status = "failed"
    filing.last_error_message = error

    db.add(
        PipelineEvent(
            filing_id=filing.id,
            company_id=filing.company_id,
            layer="processing",
            event_type="failed",
            detail={"error": error, "step": "filing_splitter"},
        )
    )
    db.flush()


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="FinPulse filing splitter — Phase 2")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--filing-id", type=int, help="Split one specific filing by DB id")
    group.add_argument("--ticker", type=str, help="Split all unextracted filings for a ticker")
    group.add_argument("--all-pending", action="store_true", help="Process all pending filings")
    p.add_argument("--form", default="10-K", help="Form type filter when using --ticker")
    p.add_argument("--limit", type=int, default=100, help="Max filings when using --all-pending")
    return p.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args()

    if args.filing_id:
        result = split_filing(args.filing_id)
        print(f"\nFiling {args.filing_id}:")
        print(f"  Sections extracted: {len(result.sections)}")
        for s in result.sections:
            print(f"    [{s.section}] {s.char_count:,} chars")
        if result.warnings:
            print(f"  Warnings: {result.warnings}")

    elif args.ticker:
        summary = split_by_ticker(args.ticker, args.form)
        print(f"\n{args.ticker} — {args.form}")
        print(f"  Processed: {summary['processed']}  Failed: {summary['failed']}")
        print(f"  Sections: {summary['sections']}")

    elif args.all_pending:
        summary = split_all_pending(limit=args.limit)
        print("\nAll pending filings:")
        print(f"  Processed: {summary['processed']}")
        print(f"  Skipped:   {summary['skipped']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Sections:  {summary['total_sections']}")


if __name__ == "__main__":
    main()
