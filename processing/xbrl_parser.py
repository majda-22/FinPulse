from __future__ import annotations

import argparse
import asyncio
import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.xbrl_fact import XbrlFact
from app.db.session import check_connection, get_db
from ingestion.company_repo import log_event
from ingestion.edgar_client import EdgarClient
from ingestion.file_store import FileStore

logger = logging.getLogger(__name__)

SUPPORTED_XBRL_FORMS = {
    "10-K",
    "10-Q",
    "10-K/A",
    "10-Q/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
}
DEFAULT_TAXONOMIES = ("us-gaap", "ifrs-full", "dei")
XBRL_PARSER_VERSION = "1.0.0"
IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"


@dataclass(slots=True)
class ParsedXbrlFact:
    company_id: int
    filing_id: int | None
    taxonomy: str
    concept: str
    label: str | None
    value: float | None
    unit: str | None
    decimals: str | None
    period_type: str | None
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_quarter: int | None
    form_type: str | None

    def business_key(self) -> tuple:
        return (
            self.company_id,
            self.taxonomy,
            self.concept,
            self.period_type,
            self.period_start,
            self.period_end,
            self.unit,
            self.form_type,
        )

    def to_model_kwargs(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "filing_id": self.filing_id,
            "taxonomy": self.taxonomy,
            "concept": self.concept,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "decimals": self.decimals,
            "period_type": self.period_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "form_type": self.form_type,
        }


@dataclass(slots=True)
class XbrlParseResult:
    company_id: int
    cik: str
    filing_id: int | None
    stored_count: int
    inserted_count: int
    updated_count: int
    matched_filing_ids: list[int]
    warnings: list[str]
    parser_version: str = XBRL_PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InlineContext:
    period_type: str
    period_start: date | None
    period_end: date | None
    has_dimensions: bool


def parse_companyfacts_payload(
    payload: dict[str, Any],
    *,
    company_id: int,
    filings_by_accession: dict[str, Filing] | None = None,
    filings_by_form_period: dict[tuple[str, date], Filing] | None = None,
    taxonomies: Sequence[str] = DEFAULT_TAXONOMIES,
    accepted_forms: set[str] | None = None,
    concept_names: set[str] | None = None,
) -> tuple[list[ParsedXbrlFact], list[str]]:
    facts = payload.get("facts") or {}
    allowed_taxonomies = set(taxonomies)
    allowed_forms = accepted_forms or SUPPORTED_XBRL_FORMS

    parsed_by_key: dict[tuple, ParsedXbrlFact] = {}
    warnings: list[str] = []

    for taxonomy, concept_map in facts.items():
        if taxonomy not in allowed_taxonomies:
            continue
        if not isinstance(concept_map, dict):
            continue

        for concept_name, concept_payload in concept_map.items():
            if concept_names is not None and concept_name not in concept_names:
                continue

            if not isinstance(concept_payload, dict):
                continue

            label = _safe_str(concept_payload.get("label"))
            units = concept_payload.get("units") or {}
            if not isinstance(units, dict):
                continue

            for unit_name, unit_entries in units.items():
                if not isinstance(unit_entries, list):
                    continue

                for unit_entry in unit_entries:
                    parsed = _parse_unit_entry(
                        unit_entry,
                        company_id=company_id,
                        taxonomy=taxonomy,
                        concept=concept_name,
                        label=label,
                        unit_name=unit_name,
                        allowed_forms=allowed_forms,
                        filings_by_accession=filings_by_accession or {},
                        filings_by_form_period=filings_by_form_period or {},
                    )
                    if parsed is None:
                        continue

                    existing = parsed_by_key.get(parsed.business_key())
                    if existing is None or _should_prefer_fact(parsed, existing):
                        parsed_by_key[parsed.business_key()] = parsed

    return list(parsed_by_key.values()), warnings


def parse_inline_xbrl_payload(
    raw_text: str,
    *,
    company_id: int,
    filing: Filing,
    taxonomies: Sequence[str] | None = DEFAULT_TAXONOMIES,
    concept_names: set[str] | None = None,
) -> tuple[list[ParsedXbrlFact], list[str]]:
    root = ET.fromstring(raw_text)
    allowed_taxonomies = set(taxonomies) if taxonomies else None
    contexts = _parse_inline_contexts(root)
    units = _parse_inline_units(root)

    parsed_by_key: dict[tuple, ParsedXbrlFact] = {}
    warnings: list[str] = []

    for element in root.iterfind(f".//{{{IX_NS}}}nonFraction"):
        name = _safe_str(element.attrib.get("name"))
        if name is None or ":" not in name:
            continue

        taxonomy, concept = name.split(":", 1)
        if allowed_taxonomies is not None and taxonomy not in allowed_taxonomies:
            continue
        if concept_names is not None and concept not in concept_names:
            continue

        context_ref = _safe_str(element.attrib.get("contextRef"))
        if context_ref is None:
            continue

        context = contexts.get(context_ref)
        if context is None or context.period_end is None or context.has_dimensions:
            continue

        value = _parse_inline_numeric_value(element)
        if value is None:
            continue

        parsed = ParsedXbrlFact(
            company_id=company_id,
            filing_id=filing.id,
            taxonomy=taxonomy,
            concept=concept,
            label=None,
            value=value,
            unit=_resolve_inline_unit(units, unit_ref=element.attrib.get("unitRef")),
            decimals=_safe_str(element.attrib.get("decimals")),
            period_type=context.period_type,
            period_start=context.period_start,
            period_end=context.period_end,
            fiscal_year=filing.fiscal_year or context.period_end.year,
            fiscal_quarter=filing.fiscal_quarter,
            form_type=filing.form_type,
        )

        existing = parsed_by_key.get(parsed.business_key())
        if existing is None or _should_prefer_fact(parsed, existing):
            parsed_by_key[parsed.business_key()] = parsed

    if not parsed_by_key:
        warnings.append("inline_xbrl_no_numeric_facts_found")

    return list(parsed_by_key.values()), warnings


def upsert_xbrl_facts(db: Session, parsed_facts: Sequence[ParsedXbrlFact]) -> tuple[int, int]:
    if not parsed_facts:
        return 0, 0

    company_id = parsed_facts[0].company_id
    concept_names = {fact.concept for fact in parsed_facts}
    taxonomies = {fact.taxonomy for fact in parsed_facts}
    period_ends = {fact.period_end for fact in parsed_facts}

    existing_rows = db.scalars(
        select(XbrlFact).where(
            XbrlFact.company_id == company_id,
            XbrlFact.concept.in_(concept_names),
            XbrlFact.taxonomy.in_(taxonomies),
            XbrlFact.period_end.in_(period_ends),
        )
    ).all()
    existing_by_key = {_row_business_key(row): row for row in existing_rows}

    inserted = 0
    updated = 0

    for parsed in parsed_facts:
        existing = existing_by_key.get(parsed.business_key())
        if existing is None:
            row = XbrlFact(**parsed.to_model_kwargs())
            db.add(row)
            existing_by_key[parsed.business_key()] = row
            inserted += 1
            continue

        existing.filing_id = parsed.filing_id
        existing.label = parsed.label
        existing.value = parsed.value
        existing.unit = parsed.unit
        existing.decimals = parsed.decimals
        existing.period_type = parsed.period_type
        existing.period_start = parsed.period_start
        existing.period_end = parsed.period_end
        existing.fiscal_year = parsed.fiscal_year
        existing.fiscal_quarter = parsed.fiscal_quarter
        existing.form_type = parsed.form_type
        updated += 1

    db.flush()
    return inserted, updated


def persist_parsed_xbrl_facts(
    db: Session,
    *,
    company_id: int,
    cik: str,
    parsed_facts: Sequence[ParsedXbrlFact],
    filing_id: int | None = None,
    force: bool = False,
    warnings: list[str] | None = None,
    source: str = "companyfacts",
) -> XbrlParseResult:
    target_filing = db.get(Filing, filing_id) if filing_id is not None else None
    if target_filing is not None and target_filing.is_xbrl_parsed and not force:
        return XbrlParseResult(
            company_id=company_id,
            cik=cik,
            filing_id=filing_id,
            stored_count=0,
            inserted_count=0,
            updated_count=0,
            matched_filing_ids=[filing_id],
            warnings=["filing_already_xbrl_parsed"],
        )

    warnings = list(warnings or [])
    inserted_count, updated_count = upsert_xbrl_facts(db, parsed_facts)
    matched_filing_ids = sorted({fact.filing_id for fact in parsed_facts if fact.filing_id is not None})

    if filing_id is not None and filing_id not in matched_filing_ids:
        matched_filing_ids.append(filing_id)
        matched_filing_ids.sort()

    if matched_filing_ids:
        filings = db.scalars(select(Filing).where(Filing.id.in_(matched_filing_ids))).all()
        for filing in filings:
            filing.is_xbrl_parsed = True
            filing.processing_status = "xbrl_parsed"
            filing.last_error_message = None

    log_event(
        db,
        event_type="xbrl_parsed",
        layer="processing",
        company_id=company_id,
        filing_id=filing_id,
        detail={
            "step": "xbrl_parser",
            "source": source,
            "stored_count": len(parsed_facts),
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "matched_filing_ids": matched_filing_ids,
            "parser_version": XBRL_PARSER_VERSION,
            "warnings": warnings,
        },
    )

    return XbrlParseResult(
        company_id=company_id,
        cik=cik,
        filing_id=filing_id,
        stored_count=len(parsed_facts),
        inserted_count=inserted_count,
        updated_count=updated_count,
        matched_filing_ids=matched_filing_ids,
        warnings=warnings,
    )


def persist_companyfacts_payload(
    db: Session,
    *,
    company_id: int,
    cik: str,
    payload: dict[str, Any],
    filing_id: int | None = None,
    force: bool = False,
    taxonomies: Sequence[str] = DEFAULT_TAXONOMIES,
    accepted_forms: set[str] | None = None,
    concept_names: set[str] | None = None,
) -> XbrlParseResult:
    filings_by_accession, filings_by_form_period = _build_filing_lookups(db, company_id=company_id)
    parsed_facts, warnings = parse_companyfacts_payload(
        payload,
        company_id=company_id,
        filings_by_accession=filings_by_accession,
        filings_by_form_period=filings_by_form_period,
        taxonomies=taxonomies,
        accepted_forms=accepted_forms,
        concept_names=concept_names,
    )

    if filing_id is not None:
        parsed_facts = [fact for fact in parsed_facts if fact.filing_id == filing_id]
        if not parsed_facts:
            warnings.append("no_xbrl_facts_matched_requested_filing")

    return persist_parsed_xbrl_facts(
        db,
        company_id=company_id,
        cik=cik,
        parsed_facts=parsed_facts,
        filing_id=filing_id,
        force=force,
        warnings=warnings,
        source="companyfacts",
    )


def parse_company_xbrl_facts(
    *,
    filing_id: int | None = None,
    company_id: int | None = None,
    ticker: str | None = None,
    cik: str | None = None,
    db: Session | None = None,
    force: bool = False,
    taxonomies: Sequence[str] = DEFAULT_TAXONOMIES,
    accepted_forms: set[str] | None = None,
    concept_names: set[str] | None = None,
) -> XbrlParseResult:
    if db is None:
        with get_db() as session:
            return parse_company_xbrl_facts(
                filing_id=filing_id,
                company_id=company_id,
                ticker=ticker,
                cik=cik,
                db=session,
                force=force,
                taxonomies=taxonomies,
                accepted_forms=accepted_forms,
                concept_names=concept_names,
            )

    company, filing = _resolve_company_context(
        db,
        filing_id=filing_id,
        company_id=company_id,
        ticker=ticker,
        cik=cik,
    )

    try:
        payload = asyncio.run(_fetch_companyfacts_payload(company_cik=company.cik))
        return persist_companyfacts_payload(
            db,
            company_id=company.id,
            cik=company.cik,
            payload=payload,
            filing_id=filing.id if filing is not None else None,
            force=force,
            taxonomies=taxonomies,
            accepted_forms=accepted_forms,
            concept_names=concept_names,
        )
    except Exception as exc:
        fallback_result = _try_inline_xbrl_fallback(
            db,
            company=company,
            filing=filing,
            exc=exc,
            force=force,
            taxonomies=taxonomies,
            concept_names=concept_names,
        )
        if fallback_result is not None:
            return fallback_result

        if filing is not None:
            filing.processing_status = "failed"
            filing.last_error_message = str(exc)
        log_event(
            db,
            event_type="failed",
            layer="processing",
            company_id=company.id,
            filing_id=filing.id if filing is not None else None,
            detail={
                "step": "xbrl_parser",
                "error": str(exc),
            },
        )
        raise


async def _fetch_companyfacts_payload(*, company_cik: str) -> dict[str, Any]:
    async with EdgarClient() as client:
        return await client.get_xbrl_facts(company_cik)


def _try_inline_xbrl_fallback(
    db: Session,
    *,
    company: Company,
    filing: Filing | None,
    exc: Exception,
    force: bool,
    taxonomies: Sequence[str],
    concept_names: set[str] | None,
) -> XbrlParseResult | None:
    if filing is None or not filing.raw_s3_key:
        return None

    try:
        raw_text = FileStore().get(filing.raw_s3_key)
        parsed_facts, warnings = parse_inline_xbrl_payload(
            raw_text,
            company_id=company.id,
            filing=filing,
            taxonomies=None,
            concept_names=concept_names,
        )
    except Exception:
        return None

    if not parsed_facts:
        return None

    warnings = [
        f"companyfacts_fetch_failed:{type(exc).__name__}",
        "inline_xbrl_fallback_used",
        *warnings,
    ]
    return persist_parsed_xbrl_facts(
        db,
        company_id=company.id,
        cik=company.cik,
        parsed_facts=parsed_facts,
        filing_id=filing.id,
        force=force,
        warnings=warnings,
        source="inline_xbrl",
    )


def _build_filing_lookups(
    db: Session,
    *,
    company_id: int,
) -> tuple[dict[str, Filing], dict[tuple[str, date], Filing]]:
    filings = db.scalars(
        select(Filing)
        .where(Filing.company_id == company_id)
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
    ).all()

    by_accession: dict[str, Filing] = {}
    by_form_period: dict[tuple[str, date], Filing] = {}

    for filing in filings:
        by_accession[filing.accession_number] = filing
        if filing.period_of_report is not None:
            by_form_period[(filing.form_type, filing.period_of_report)] = filing

    return by_accession, by_form_period


def _resolve_company_context(
    db: Session,
    *,
    filing_id: int | None,
    company_id: int | None,
    ticker: str | None,
    cik: str | None,
) -> tuple[Company, Filing | None]:
    filing: Filing | None = None

    if filing_id is not None:
        filing = db.get(Filing, filing_id)
        if filing is None:
            raise RuntimeError(f"Filing id={filing_id} not found in database")
        company = db.get(Company, filing.company_id)
        if company is None:
            raise RuntimeError(f"Company id={filing.company_id} not found in database")
        return company, filing

    company: Company | None = None
    if company_id is not None:
        company = db.get(Company, company_id)
    elif ticker is not None:
        company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    elif cik is not None:
        company = db.scalar(select(Company).where(Company.cik == cik))

    if company is None:
        raise RuntimeError("Provide filing_id, company_id, ticker, or cik to resolve company context")

    return company, filing


def _parse_inline_contexts(root: ET.Element) -> dict[str, InlineContext]:
    contexts: dict[str, InlineContext] = {}

    for element in root.iterfind(f".//{{{XBRLI_NS}}}context"):
        context_id = _safe_str(element.attrib.get("id"))
        if context_id is None:
            continue

        instant = element.find(f"./{{{XBRLI_NS}}}period/{{{XBRLI_NS}}}instant")
        start = element.find(f"./{{{XBRLI_NS}}}period/{{{XBRLI_NS}}}startDate")
        end = element.find(f"./{{{XBRLI_NS}}}period/{{{XBRLI_NS}}}endDate")

        if instant is not None:
            period_type = "instant"
            period_start = None
            period_end = _safe_date(instant.text)
        else:
            period_type = "duration"
            period_start = _safe_date(start.text if start is not None else None)
            period_end = _safe_date(end.text if end is not None else None)

        contexts[context_id] = InlineContext(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            has_dimensions=_inline_context_has_dimensions(element),
        )

    return contexts


def _inline_context_has_dimensions(element: ET.Element) -> bool:
    return any(
        (
            element.find(f".//{{{XBRLI_NS}}}segment") is not None,
            element.find(f".//{{{XBRLI_NS}}}scenario") is not None,
            element.find(f".//{{{XBRLDI_NS}}}explicitMember") is not None,
            element.find(f".//{{{XBRLDI_NS}}}typedMember") is not None,
        )
    )


def _parse_inline_units(root: ET.Element) -> dict[str, str]:
    units: dict[str, str] = {}

    for element in root.iterfind(f".//{{{XBRLI_NS}}}unit"):
        unit_id = _safe_str(element.attrib.get("id"))
        if unit_id is None:
            continue

        measure = element.find(f"./{{{XBRLI_NS}}}measure")
        if measure is not None and measure.text:
            units[unit_id] = _normalize_unit_measure(measure.text)
            continue

        numerator = element.find(f"./{{{XBRLI_NS}}}divide/{{{XBRLI_NS}}}unitNumerator/{{{XBRLI_NS}}}measure")
        denominator = element.find(
            f"./{{{XBRLI_NS}}}divide/{{{XBRLI_NS}}}unitDenominator/{{{XBRLI_NS}}}measure"
        )
        if numerator is not None and denominator is not None and numerator.text and denominator.text:
            units[unit_id] = (
                f"{_normalize_unit_measure(numerator.text)}/{_normalize_unit_measure(denominator.text)}"
            )

    return units


def _normalize_unit_measure(value: str) -> str:
    token = value.strip()
    if "}" in token:
        token = token.rsplit("}", 1)[-1]
    if ":" in token:
        token = token.rsplit(":", 1)[-1]
    return token


def _resolve_inline_unit(units: dict[str, str], *, unit_ref: Any) -> str | None:
    unit_key = _safe_str(unit_ref)
    if unit_key is None:
        return None
    return units.get(unit_key, unit_key)


def _parse_unit_entry(
    unit_entry: dict[str, Any],
    *,
    company_id: int,
    taxonomy: str,
    concept: str,
    label: str | None,
    unit_name: str,
    allowed_forms: set[str],
    filings_by_accession: dict[str, Filing],
    filings_by_form_period: dict[tuple[str, date], Filing],
) -> ParsedXbrlFact | None:
    if not isinstance(unit_entry, dict):
        return None

    form_type = _safe_str(unit_entry.get("form"))
    if not form_type or form_type not in allowed_forms:
        return None

    period_end = _safe_date(unit_entry.get("end"))
    if period_end is None:
        return None

    value = _safe_float(unit_entry.get("val"))
    if value is None:
        return None

    accession = _safe_str(unit_entry.get("accn"))
    matched_filing = filings_by_accession.get(accession) if accession else None
    if matched_filing is None:
        matched_filing = filings_by_form_period.get((form_type, period_end))

    period_start = _safe_date(unit_entry.get("start"))
    period_type = "duration" if period_start is not None else "instant"
    decimals = _safe_str(unit_entry.get("decimals"))

    return ParsedXbrlFact(
        company_id=company_id,
        filing_id=matched_filing.id if matched_filing is not None else None,
        taxonomy=taxonomy,
        concept=concept,
        label=label,
        value=value,
        unit=unit_name,
        decimals=decimals,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        fiscal_year=_safe_int(unit_entry.get("fy")),
        fiscal_quarter=_parse_fiscal_quarter(unit_entry.get("fp")),
        form_type=form_type,
    )


def _parse_inline_numeric_value(element: ET.Element) -> float | None:
    raw_text = "".join(element.itertext()).strip()
    if not raw_text:
        return None

    cleaned = raw_text.replace(",", "").replace("$", "").replace("%", "")
    cleaned = cleaned.replace("\u00a0", "").replace(" ", "")
    if cleaned in {"-", "\u2014", "\u2013"}:
        return None

    sign = -1.0 if _safe_str(element.attrib.get("sign")) == "-" else 1.0
    if cleaned.startswith("(") and cleaned.endswith(")"):
        sign *= -1.0
        cleaned = cleaned[1:-1]

    value = _safe_float(cleaned)
    if value is None:
        return None

    scale = _safe_int(element.attrib.get("scale")) or 0
    return float(sign * value * (10 ** scale))


def _should_prefer_fact(candidate: ParsedXbrlFact, existing: ParsedXbrlFact) -> bool:
    candidate_rank = _fact_rank(candidate)
    existing_rank = _fact_rank(existing)
    return candidate_rank > existing_rank


def _fact_rank(fact: ParsedXbrlFact) -> tuple[int, int, int]:
    has_filing = 1 if fact.filing_id is not None else 0
    duration_days = _duration_days(fact.period_start, fact.period_end)
    annual_preference = 1 if fact.form_type in {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"} else 0
    return has_filing, annual_preference, duration_days


def _row_business_key(row: XbrlFact) -> tuple:
    return (
        row.company_id,
        row.taxonomy,
        row.concept,
        row.period_type,
        row.period_start,
        row.period_end,
        row.unit,
        row.form_type,
    )


def _duration_days(period_start: date | None, period_end: date) -> int:
    if period_start is None:
        return 0
    return max((period_end - period_start).days, 0)


def _safe_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _safe_int(value: Any) -> int | None:
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _safe_date(value: Any) -> date | None:
    if value in (None, "", "None"):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_fiscal_quarter(value: Any) -> int | None:
    token = _safe_str(value)
    if token is None:
        return None
    token = token.upper()
    if token.startswith("Q") and len(token) >= 2 and token[1].isdigit():
        return int(token[1])
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse SEC companyfacts XBRL into xbrl_facts")
    parser.add_argument("--filing-id", type=int, default=None)
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--cik", default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not check_connection():
        raise SystemExit("Cannot connect to PostgreSQL. Check your .env / Docker setup.")

    result = parse_company_xbrl_facts(
        filing_id=args.filing_id,
        company_id=args.company_id,
        ticker=args.ticker,
        cik=args.cik,
        force=args.force,
    )

    print(f"Company {result.company_id} ({result.cik})")
    if result.filing_id is not None:
        print(f"  Filing id: {result.filing_id}")
    print(f"  Stored facts: {result.stored_count}")
    print(f"  Inserted: {result.inserted_count}")
    print(f"  Updated: {result.updated_count}")
    print(f"  Matched filings: {result.matched_filing_ids}")
    if result.warnings:
        print(f"  Warnings: {result.warnings}")


if __name__ == "__main__":
    main()
