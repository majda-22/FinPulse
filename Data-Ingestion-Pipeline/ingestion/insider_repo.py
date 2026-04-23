from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db.models.insider_transaction import InsiderTransaction


def upsert_insider_transactions(
    db: Session,
    transactions: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    if not transactions:
        return 0, 0

    transactions = _dedupe_transactions(transactions)

    transaction_uids = [str(transaction["transaction_uid"]) for transaction in transactions]
    existing_rows = db.scalars(
        select(InsiderTransaction).where(InsiderTransaction.transaction_uid.in_(transaction_uids))
    ).all()
    existing_by_uid = {row.transaction_uid: row for row in existing_rows}

    business_lookup_keys = [_business_lookup_key(transaction) for transaction in transactions]
    existing_rows_by_key = db.scalars(
        select(InsiderTransaction).where(
            tuple_(
                InsiderTransaction.accession_number,
                InsiderTransaction.insider_name,
                InsiderTransaction.transaction_date,
                InsiderTransaction.transaction_code,
                InsiderTransaction.shares,
                InsiderTransaction.price_per_share,
                InsiderTransaction.security_title,
                InsiderTransaction.ownership_nature,
                InsiderTransaction.acquired_disposed_code,
                InsiderTransaction.is_derivative,
            ).in_(business_lookup_keys)
        )
    ).all() if business_lookup_keys else []
    existing_by_business_key = {
        _business_key_from_row(row): row for row in existing_rows_by_key
    }

    inserted = 0
    updated = 0
    for transaction in transactions:
        uid = str(transaction["transaction_uid"])
        existing = existing_by_uid.get(uid)
        if existing is None:
            existing = existing_by_business_key.get(_business_key(transaction))

        payload = {
            "filing_id": transaction.get("filing_id"),
            "company_id": transaction["company_id"],
            "transaction_uid": uid,
            "accession_number": transaction["accession_number"],
            "cik": transaction["cik"],
            "ticker": transaction.get("ticker"),
            "issuer_name": transaction.get("issuer_name"),
            "security_title": _security_title(transaction),
            "insider_name": transaction["insider_name"],
            "insider_cik": transaction.get("insider_cik"),
            "is_director": bool(transaction.get("is_director", False)),
            "is_officer": bool(transaction.get("is_officer", False)),
            "is_ten_percent_owner": bool(transaction.get("is_ten_percent_owner", False)),
            "is_other": bool(transaction.get("is_other", False)),
            "officer_title": transaction.get("officer_title"),
            "transaction_date": transaction["transaction_date"],
            "transaction_code": transaction["transaction_code"],
            "transaction_type_normalized": transaction["transaction_type_normalized"],
            "shares": transaction["shares"],
            "price_per_share": transaction.get("price_per_share"),
            "transaction_value": transaction.get("transaction_value"),
            "shares_owned_after": transaction.get("shares_owned_after"),
            "ownership_nature": transaction.get("ownership_nature"),
            "acquired_disposed_code": transaction.get("acquired_disposed_code"),
            "is_derivative": bool(transaction.get("is_derivative", False)),
            "form_type": transaction.get("form_type") or "4",
            "filed_at": transaction.get("filed_at"),
            "source_url": transaction.get("source_url"),
            "raw_detail": _json_safe(transaction.get("raw_detail")),
        }

        if existing is None:
            db.add(InsiderTransaction(**payload))
            inserted += 1
            continue

        if existing.company_id != payload["company_id"]:
            raise ValueError(
                f"Transaction uid={uid} already belongs to company_id={existing.company_id}, "
                f"not {payload['company_id']}"
            )

        for field_name, value in payload.items():
            setattr(existing, field_name, value)
        updated += 1

    db.flush()
    return inserted, updated


def _dedupe_transactions(
    transactions: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    deduped_by_uid: dict[str, Mapping[str, Any]] = {}
    deduped_by_business_key: dict[tuple[Any, ...], Mapping[str, Any]] = {}

    for transaction in transactions:
        uid = str(transaction["transaction_uid"])
        deduped_by_uid[uid] = transaction

    for transaction in deduped_by_uid.values():
        deduped_by_business_key[_business_key(transaction)] = transaction

    return list(deduped_by_business_key.values())


def _business_key(transaction: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        transaction["accession_number"],
        transaction["insider_name"],
        transaction["transaction_date"],
        transaction["transaction_code"],
        _normalize_numeric_key_part(transaction["shares"]),
        _normalize_numeric_key_part(transaction.get("price_per_share")),
        _security_title(transaction),
        transaction.get("ownership_nature"),
        transaction.get("acquired_disposed_code"),
        bool(transaction.get("is_derivative", False)),
    )


def _business_lookup_key(transaction: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        transaction["accession_number"],
        transaction["insider_name"],
        transaction["transaction_date"],
        transaction["transaction_code"],
        _numeric_lookup_value(transaction["shares"]),
        _numeric_lookup_value(transaction.get("price_per_share")),
        _security_title(transaction),
        transaction.get("ownership_nature"),
        transaction.get("acquired_disposed_code"),
        bool(transaction.get("is_derivative", False)),
    )


def _business_key_from_row(row: InsiderTransaction) -> tuple[Any, ...]:
    return (
        row.accession_number,
        row.insider_name,
        row.transaction_date,
        row.transaction_code,
        _normalize_numeric_key_part(row.shares),
        _normalize_numeric_key_part(row.price_per_share),
        (row.security_title or "").strip(),
        row.ownership_nature,
        row.acquired_disposed_code,
        row.is_derivative,
    )


def _normalize_numeric_key_part(value: Any) -> str | None:
    decimal_value = _numeric_lookup_value(value)
    if decimal_value is None:
        return None
    normalized = decimal_value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _numeric_lookup_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _security_title(transaction: Mapping[str, Any]) -> str:
    security_title = transaction.get("security_title")
    if security_title is None:
        raw_detail = transaction.get("raw_detail")
        if isinstance(raw_detail, Mapping):
            security_title = raw_detail.get("security_title")
    if security_title is None:
        return ""
    return str(security_title).strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value
