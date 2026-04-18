from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.session import get_db
from ingestion.company_repo import log_event
from ingestion.insider_repo import upsert_insider_transactions

logger = logging.getLogger(__name__)

FORM4_PARSER_VERSION = "1.0.0"
TRANSACTION_TYPE_MAP = {
    "P": "open_market_buy",
    "S": "open_market_sell",
    "M": "option_exercise",
    "A": "equity_award",
    "F": "tax_withholding",
    "G": "gift",
    "C": "conversion",
    "D": "issuer_transaction",
}


@dataclass(slots=True)
class ParsedInsiderTransaction:
    company_id: int
    filing_id: int | None
    accession_number: str
    cik: str
    ticker: str | None
    issuer_name: str | None
    security_title: str
    insider_name: str
    insider_cik: str | None
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    officer_title: str | None
    transaction_date: date
    transaction_code: str
    transaction_type_normalized: str
    shares: float
    price_per_share: float | None
    transaction_value: float | None
    shares_owned_after: float | None
    ownership_nature: str | None
    acquired_disposed_code: str | None
    is_derivative: bool
    form_type: str
    filed_at: date | None
    source_url: str | None
    raw_detail: dict[str, Any]
    transaction_uid: str

    def to_model_kwargs(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ParsedReportingOwner:
    insider_name: str
    insider_cik: str | None
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    is_other: bool
    officer_title: str | None


@dataclass(slots=True)
class Form4ParseResult:
    company_id: int
    filing_id: int | None
    accession_number: str
    stored_count: int
    inserted_count: int
    updated_count: int
    parser_version: str = FORM4_PARSER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_transaction_type(
    transaction_code: str | None,
    *,
    acquired_disposed_code: str | None = None,
    is_derivative: bool = False,
) -> str:
    code = (transaction_code or "").strip().upper()
    if code in TRANSACTION_TYPE_MAP:
        return TRANSACTION_TYPE_MAP[code]
    if is_derivative and code:
        return "derivative_other"
    if acquired_disposed_code == "A":
        return "other_acquisition"
    if acquired_disposed_code == "D":
        return "other_disposition"
    return "other"


def parse_form4_xml(
    xml_text: str,
    *,
    company_id: int,
    accession_number: str,
    cik: str,
    ticker: str | None = None,
    issuer_name: str | None = None,
    filing_id: int | None = None,
    filed_at: date | None = None,
    form_type: str = "4",
    source_url: str | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    _strip_namespaces(root)

    issuer = root.find("issuer")
    issuer_cik = _text(issuer, "issuerCik") or cik
    issuer_ticker = _text(issuer, "issuerTradingSymbol") or ticker
    issuer_name_value = _text(issuer, "issuerName") or issuer_name

    reporting_owners = _parse_reporting_owners(root)
    if not reporting_owners:
        owner_name = _text(root, "reportingOwner/reportingOwnerId/rptOwnerName") or "unknown"
        reporting_owners = [
            ParsedReportingOwner(
                insider_name=owner_name,
                insider_cik=_text(root, "reportingOwner/reportingOwnerId/rptOwnerCik"),
                is_director=False,
                is_officer=False,
                is_ten_percent_owner=False,
                is_other=False,
                officer_title=None,
            )
        ]

    transactions: list[dict[str, Any]] = []
    for is_derivative, table_path, transaction_tag in (
        (False, "nonDerivativeTable", "nonDerivativeTransaction"),
        (True, "derivativeTable", "derivativeTransaction"),
    ):
        table = root.find(table_path)
        if table is None:
            continue

        for transaction in table.findall(transaction_tag):
            parsed_rows = _parse_transaction_rows(
                transaction,
                reporting_owners=reporting_owners,
                company_id=company_id,
                filing_id=filing_id,
                accession_number=accession_number,
                cik=issuer_cik,
                ticker=issuer_ticker,
                issuer_name=issuer_name_value,
                filed_at=filed_at,
                form_type=form_type,
                source_url=source_url,
                is_derivative=is_derivative,
            )
            transactions.extend(row.to_model_kwargs() for row in parsed_rows)

    return transactions


def parse_and_store_form4_xml(
    *,
    filing_id: int,
    xml_text: str,
    db: Session | None = None,
    source_url: str | None = None,
) -> Form4ParseResult:
    if db is None:
        with get_db() as session:
            return parse_and_store_form4_xml(
                filing_id=filing_id,
                xml_text=xml_text,
                db=session,
                source_url=source_url,
            )

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    company = db.get(Company, filing.company_id)
    if company is None:
        raise RuntimeError(f"Company id={filing.company_id} not found in database")

    if filing.form_type not in {"4", "4/A"}:
        raise RuntimeError(
            f"Filing id={filing_id} has form_type={filing.form_type!r}, expected Form 4"
        )

    transactions = parse_form4_xml(
        xml_text,
        company_id=company.id,
        filing_id=filing.id,
        accession_number=filing.accession_number,
        cik=company.cik,
        ticker=company.ticker,
        issuer_name=company.name,
        filed_at=filing.filed_at,
        form_type=filing.form_type,
        source_url=source_url,
    )
    inserted_count, updated_count = upsert_insider_transactions(db, transactions)
    filing.is_form4_parsed = True
    filing.processing_status = "form4_parsed"
    filing.last_error_message = None

    log_event(
        db,
        event_type="form4_parsed",
        layer="processing",
        company_id=company.id,
        filing_id=filing.id,
        detail={
            "step": "form4_parser",
            "stored_count": len(transactions),
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "parser_version": FORM4_PARSER_VERSION,
        },
    )

    return Form4ParseResult(
        company_id=company.id,
        filing_id=filing.id,
        accession_number=filing.accession_number,
        stored_count=len(transactions),
        inserted_count=inserted_count,
        updated_count=updated_count,
    )


def _parse_reporting_owners(root: ET.Element) -> list[ParsedReportingOwner]:
    owners: list[ParsedReportingOwner] = []
    for owner in root.findall("reportingOwner"):
        owner_id = owner.find("reportingOwnerId")
        relationship = owner.find("reportingOwnerRelationship")
        insider_name = _text(owner_id, "rptOwnerName")
        if insider_name is None:
            continue
        owners.append(
            ParsedReportingOwner(
                insider_name=insider_name,
                insider_cik=_text(owner_id, "rptOwnerCik"),
                is_director=_text_bool(relationship, "isDirector"),
                is_officer=_text_bool(relationship, "isOfficer"),
                is_ten_percent_owner=_text_bool(relationship, "isTenPercentOwner"),
                is_other=_text_bool(relationship, "isOther"),
                officer_title=_text(relationship, "officerTitle"),
            )
        )
    return owners


def _parse_transaction_rows(
    transaction: ET.Element,
    *,
    reporting_owners: Iterable[ParsedReportingOwner],
    company_id: int,
    filing_id: int | None,
    accession_number: str,
    cik: str,
    ticker: str | None,
    issuer_name: str | None,
    filed_at: date | None,
    form_type: str,
    source_url: str | None,
    is_derivative: bool,
) -> list[ParsedInsiderTransaction]:
    transaction_date = _text_date(transaction, "transactionDate/value")
    shares = _text_number(transaction, "transactionAmounts/transactionShares/value")
    transaction_code = (_text(transaction, "transactionCoding/transactionCode") or "").upper()

    if transaction_date is None or shares is None or not transaction_code:
        logger.debug("Skipping incomplete Form 4 transaction row")
        return []

    price_per_share = _text_number(transaction, "transactionAmounts/transactionPricePerShare/value")
    acquired_disposed_code = _text(
        transaction,
        "transactionAmounts/transactionAcquiredDisposedCode/value",
    )
    shares_owned_after = _text_number(
        transaction,
        "postTransactionAmounts/sharesOwnedFollowingTransaction/value",
    )
    ownership_nature = _ownership_nature(
        _text(transaction, "ownershipNature/directOrIndirectOwnership/value")
    )
    security_title = _text(transaction, "securityTitle/value")
    derivative_security_price = _text_number(transaction, "conversionOrExercisePrice/value")
    source_table_type = "derivative" if is_derivative else "non_derivative"
    transaction_type_normalized = normalize_transaction_type(
        transaction_code,
        acquired_disposed_code=acquired_disposed_code,
        is_derivative=is_derivative,
    )
    transaction_value = _transaction_value(shares, price_per_share)
    # Keep richer XML-derived fields for audit/debug provenance; the signal layer
    # should rely on normalized columns first and treat raw_detail as secondary context.
    raw_detail = {
        "security_title": security_title,
        "transaction_timeliness": _text(transaction, "transactionCoding/transactionTimeliness/value"),
        "equity_swap_involved": _text_bool(transaction.find("transactionCoding"), "equitySwapInvolved"),
        "footnote_ids": _footnote_ids(transaction),
        "deemed_execution_date": _text(transaction, "deemedExecutionDate/value"),
        "conversion_or_exercise_price": derivative_security_price,
        "shares_owned_after": shares_owned_after,
        "ownership_nature": ownership_nature,
        "is_derivative": is_derivative,
        "source_table_type": source_table_type,
    }

    rows: list[ParsedInsiderTransaction] = []
    for owner in reporting_owners:
        uid = _build_transaction_uid(
            accession_number=accession_number,
            insider_name=owner.insider_name,
            insider_cik=owner.insider_cik,
            transaction_date=transaction_date,
            transaction_code=transaction_code,
            shares=shares,
            price_per_share=price_per_share,
            security_title=security_title,
            shares_owned_after=shares_owned_after,
            source_table_type=source_table_type,
            ownership_nature=ownership_nature,
            acquired_disposed_code=acquired_disposed_code,
            is_derivative=is_derivative,
        )
        rows.append(
            ParsedInsiderTransaction(
                company_id=company_id,
                filing_id=filing_id,
                accession_number=accession_number,
                cik=str(cik).strip().zfill(10),
                ticker=ticker,
                issuer_name=issuer_name,
                security_title=security_title or "",
                insider_name=owner.insider_name,
                insider_cik=owner.insider_cik,
                is_director=owner.is_director,
                is_officer=owner.is_officer,
                is_ten_percent_owner=owner.is_ten_percent_owner,
                is_other=owner.is_other,
                officer_title=owner.officer_title,
                transaction_date=transaction_date,
                transaction_code=transaction_code,
                transaction_type_normalized=transaction_type_normalized,
                shares=shares,
                price_per_share=price_per_share,
                transaction_value=transaction_value,
                shares_owned_after=shares_owned_after,
                ownership_nature=ownership_nature,
                acquired_disposed_code=acquired_disposed_code,
                is_derivative=is_derivative,
                form_type=form_type,
                filed_at=filed_at,
                source_url=source_url,
                raw_detail=raw_detail,
                transaction_uid=uid,
            )
        )
    return rows


def _build_transaction_uid(**parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _transaction_value(shares: float, price_per_share: float | None) -> float | None:
    if price_per_share is None:
        return None
    return float(shares * price_per_share)


def _ownership_nature(code: str | None) -> str | None:
    if code is None:
        return None
    code = code.strip().upper()
    if code == "D":
        return "direct"
    if code == "I":
        return "indirect"
    return code.lower() or None


def _footnote_ids(transaction: ET.Element) -> list[str]:
    values: list[str] = []
    for tag in (
        "transactionAmounts/transactionShares",
        "transactionAmounts/transactionPricePerShare",
        "postTransactionAmounts/sharesOwnedFollowingTransaction",
    ):
        node = transaction.find(tag)
        if node is None:
            continue
        for footnote in node.findall("footnoteId"):
            value = footnote.attrib.get("id")
            if value:
                values.append(value)
    return values


def _strip_namespaces(root: ET.Element) -> None:
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]


def _text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    node = element.find(path)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _text_bool(element: ET.Element | None, path: str) -> bool:
    value = _text(element, path)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "y", "yes"}


def _text_date(element: ET.Element | None, path: str) -> date | None:
    value = _text(element, path)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text_number(element: ET.Element | None, path: str) -> float | None:
    value = _text(element, path)
    if value is None:
        return None
    token = value.replace(",", "").strip()
    if token in {"", "N/A"}:
        return None
    try:
        return float(Decimal(token))
    except (InvalidOperation, ValueError):
        return None
