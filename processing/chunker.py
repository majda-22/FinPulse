"""
processing/chunker.py

Build embedding-sized text chunks from extracted filing sections.

This module is intentionally focused on chunking only:
    - reads `filing_sections`
    - splits section text into sentence-aware chunks with overlap
    - returns chunk metadata for downstream embedding code

It does NOT call an embedding provider and does NOT mark `filings.is_embedded`.
That state should be updated only after vectors are successfully written.
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.filing_section import FilingSection
from app.db.session import get_db

logger = logging.getLogger(__name__)

CHUNKER_VERSION = "1.0.0"

DEFAULT_TARGET_CHARS = 1_500
DEFAULT_MAX_CHARS = 1_800
DEFAULT_MIN_CHARS = 300
DEFAULT_OVERLAP_CHARS = 150

SECTION_SORT_ORDER = {
    "business": 10,
    "risk_factors": 20,
    "forward_looking": 30,
    "mda": 40,
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


@dataclass
class FilingChunk:
    filing_id: int
    company_id: int
    filing_section_id: int
    section: str
    section_sequence_idx: int
    chunk_idx: int
    text: str
    char_count: int
    approx_tokens: int


@dataclass
class ChunkingResult:
    filing_id: int
    accession_number: str
    chunks: list[FilingChunk]
    warnings: list[str]


def chunk_filing(
    filing_id: int,
    db: Optional[Session] = None,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    include_sections: Optional[Sequence[str]] = None,
) -> ChunkingResult:
    """
    Load one filing plus its extracted sections and produce chunk metadata.
    """
    own_session = db is None
    if own_session:
        ctx = get_db()
        db = ctx.__enter__()

    try:
        assert db is not None
        result = _chunk_filing_inner(
            filing_id=filing_id,
            db=db,
            target_chars=target_chars,
            max_chars=max_chars,
            min_chars=min_chars,
            overlap_chars=overlap_chars,
            include_sections=include_sections,
        )
        if own_session:
            ctx.__exit__(None, None, None)
        return result
    except Exception as exc:
        if own_session:
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise


def chunk_section(
    section_row: FilingSection,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[FilingChunk]:
    """
    Chunk a single FilingSection row into embedding-sized chunks.
    """
    chunk_texts = chunk_text(
        section_row.text,
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
        overlap_chars=overlap_chars,
    )

    results: list[FilingChunk] = []
    for idx, text in enumerate(chunk_texts):
        results.append(
            FilingChunk(
                filing_id=section_row.filing_id,
                company_id=section_row.company_id,
                filing_section_id=section_row.id,
                section=section_row.section,
                section_sequence_idx=section_row.sequence_idx,
                chunk_idx=idx,
                text=text,
                char_count=len(text),
                approx_tokens=_estimate_tokens(text),
            )
        )

    return results


def chunk_text(
    text: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """
    Split free-form text into chunks that are appropriate for embedding APIs.

    The algorithm prefers:
        1. paragraph boundaries
        2. sentence boundaries
        3. word boundaries for very long sentences
    """
    _validate_chunk_args(
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
        overlap_chars=overlap_chars,
    )

    normalized = _normalize_text(text, preserve_breaks=True)
    if not normalized:
        return []

    units = _text_to_units(normalized, max_chars=max_chars)
    if not units:
        return []

    return _assemble_chunks(
        units,
        target_chars=target_chars,
        max_chars=max_chars,
        min_chars=min_chars,
        overlap_chars=overlap_chars,
    )


def preview_chunks(
    chunks: Sequence[FilingChunk],
    *,
    limit: int = 5,
    preview_chars: int = 140,
) -> list[str]:
    """
    Return compact human-readable summaries for CLI preview/debugging.
    """
    rows: list[str] = []
    for chunk in list(chunks)[:limit]:
        snippet = chunk.text[:preview_chars].replace("\n", " ")
        if len(chunk.text) > preview_chars:
            snippet += "..."
        rows.append(
            f"[{chunk.section}#{chunk.section_sequence_idx}:{chunk.chunk_idx}] "
            f"{chunk.char_count} chars ~{chunk.approx_tokens} tok  {snippet}"
        )
    return rows


def _chunk_filing_inner(
    filing_id: int,
    db: Session,
    *,
    target_chars: int,
    max_chars: int,
    min_chars: int,
    overlap_chars: int,
    include_sections: Optional[Sequence[str]],
) -> ChunkingResult:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    warnings: list[str] = []

    if not filing.is_extracted:
        warnings.append("filing_not_marked_extracted")

    rows = db.scalars(
        select(FilingSection)
        .where(FilingSection.filing_id == filing_id)
    ).all()

    if include_sections:
        wanted = {name.strip().lower() for name in include_sections if name.strip()}
        rows = [row for row in rows if row.section.lower() in wanted]

    rows = sorted(rows, key=_section_sort_key)

    if not rows:
        warnings.append("no_sections_found")
        return ChunkingResult(
            filing_id=filing.id,
            accession_number=filing.accession_number,
            chunks=[],
            warnings=warnings,
        )

    chunks: list[FilingChunk] = []
    for row in rows:
        section_chunks = chunk_section(
            row,
            target_chars=target_chars,
            max_chars=max_chars,
            min_chars=min_chars,
            overlap_chars=overlap_chars,
        )
        if not section_chunks:
            warnings.append(f"empty_section:{row.section}:{row.sequence_idx}")
            continue
        chunks.extend(section_chunks)

    return ChunkingResult(
        filing_id=filing.id,
        accession_number=filing.accession_number,
        chunks=chunks,
        warnings=warnings,
    )


def _validate_chunk_args(
    *,
    target_chars: int,
    max_chars: int,
    min_chars: int,
    overlap_chars: int,
) -> None:
    if min_chars <= 0:
        raise ValueError("min_chars must be > 0")
    if target_chars < min_chars:
        raise ValueError("target_chars must be >= min_chars")
    if max_chars < target_chars:
        raise ValueError("max_chars must be >= target_chars")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")


def _section_sort_key(row: FilingSection) -> tuple[int, str, int, int]:
    return (
        SECTION_SORT_ORDER.get(row.section, 999),
        row.section,
        row.sequence_idx,
        row.id,
    )


def _text_to_units(text: str, *, max_chars: int) -> list[str]:
    paragraphs = _split_paragraphs(text)
    units: list[str] = []

    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            units.append(paragraph)
            continue

        sentences = _split_sentences(paragraph)
        if len(sentences) <= 1:
            units.extend(_split_long_text(paragraph, max_chars=max_chars))
            continue

        for sentence in sentences:
            if len(sentence) <= max_chars:
                units.append(sentence)
            else:
                units.extend(_split_long_text(sentence, max_chars=max_chars))

    return [unit for unit in units if unit]


def _split_paragraphs(text: str) -> list[str]:
    if "\n" not in text:
        clean = _normalize_text(text)
        return [clean] if clean else []

    parts = []
    for part in PARAGRAPH_SPLIT_RE.split(text):
        clean = _normalize_text(part)
        if clean:
            parts.append(clean)
    return parts


def _split_sentences(paragraph: str) -> list[str]:
    paragraph = _normalize_text(paragraph)
    if not paragraph:
        return []

    parts = SENTENCE_SPLIT_RE.split(paragraph)
    if len(parts) == 1:
        parts = re.split(r";\s+", paragraph)

    sentences = [_normalize_text(part) for part in parts]
    return [sentence for sentence in sentences if sentence]


def _split_long_text(text: str, *, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        if len(word) > max_chars:
            if current:
                pieces.append(" ".join(current))
                current = []
                current_len = 0
            pieces.extend(_split_very_long_word(word, max_chars=max_chars))
            continue

        add_len = len(word) if not current else len(word) + 1
        if current and current_len + add_len > max_chars:
            pieces.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += add_len

    if current:
        pieces.append(" ".join(current))

    return pieces


def _split_very_long_word(word: str, *, max_chars: int) -> list[str]:
    return [word[i:i + max_chars] for i in range(0, len(word), max_chars)]


def _assemble_chunks(
    units: Sequence[str],
    *,
    target_chars: int,
    max_chars: int,
    min_chars: int,
    overlap_chars: int,
) -> list[str]:
    chunks: list[str] = []
    current_units: list[str] = []

    for unit in units:
        candidate_len = _units_len((*current_units, unit))
        should_flush = bool(current_units) and (
            candidate_len > max_chars
            or (_units_len(current_units) >= min_chars and candidate_len > target_chars)
        )

        if should_flush:
            chunks.append(_join_units(current_units))
            current_units = _overlap_units(current_units, overlap_chars=overlap_chars)

            while current_units and _units_len((*current_units, unit)) > max_chars:
                current_units.pop(0)

        current_units.append(unit)

    if current_units:
        chunks.append(_join_units(current_units))

    return [_normalize_text(chunk) for chunk in chunks if chunk and _normalize_text(chunk)]


def _overlap_units(units: Sequence[str], *, overlap_chars: int) -> list[str]:
    if overlap_chars <= 0 or not units:
        return []

    overlap: list[str] = []
    total = 0

    for unit in reversed(units):
        add_len = len(unit) if not overlap else len(unit) + 1
        if overlap and total + add_len > overlap_chars:
            break
        overlap.insert(0, unit)
        total += add_len

    return overlap


def _units_len(units: Iterable[str]) -> int:
    items = [unit for unit in units if unit]
    if not items:
        return 0
    return sum(len(unit) for unit in items) + max(0, len(items) - 1)


def _join_units(units: Sequence[str]) -> str:
    return " ".join(unit.strip() for unit in units if unit and unit.strip()).strip()


def _estimate_tokens(text: str) -> int:
    # Quick rule-of-thumb for English-heavy filings.
    return max(1, round(len(text) / 4))


def _normalize_text(text: str, *, preserve_breaks: bool = False) -> str:
    text = "".join(ch if ch.isprintable() or ch in "\r\n\t" else " " for ch in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if preserve_breaks:
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_args():
    parser = argparse.ArgumentParser(description="Preview chunked filing sections")
    parser.add_argument("--filing-id", type=int, required=True, help="Database filing id")
    parser.add_argument("--target-chars", type=int, default=DEFAULT_TARGET_CHARS)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    parser.add_argument("--overlap-chars", type=int, default=DEFAULT_OVERLAP_CHARS)
    parser.add_argument(
        "--sections",
        nargs="*",
        default=None,
        help="Optional section names to include, e.g. risk_factors mda",
    )
    parser.add_argument("--preview", type=int, default=5, help="Number of chunks to preview")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args()
    result = chunk_filing(
        filing_id=args.filing_id,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        overlap_chars=args.overlap_chars,
        include_sections=args.sections,
    )

    print(f"\nFiling {result.filing_id} ({result.accession_number})")
    print(f"Chunks produced: {len(result.chunks)}")
    if result.warnings:
        print(f"Warnings: {result.warnings}")

    for row in preview_chunks(result.chunks, limit=args.preview):
        print(f"  {row}")


if __name__ == "__main__":
    main()
