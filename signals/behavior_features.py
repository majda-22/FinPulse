from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.models.insider_transaction import InsiderTransaction
from signals.policies import ROLE_WEIGHTS, ROUTINE_TRANSACTION_CODES, SENIOR_OPPORTUNISTIC_ROLES

BEHAVIOR_FEATURES_VERSION = "behavior_features_v2"
WINDOW_BEFORE_DAYS = 90
WINDOW_AFTER_DAYS = 90
GOVERNANCE_LOOKBACK_DAYS = 365


@dataclass(slots=True)
class BehaviorFeatureSnapshot:
    filing_id: int
    company_id: int
    anchor_filed_at: Any
    history_filing_ids: list[int]
    transaction_row_count: int
    feature_basis: str
    features: dict[str, Any]
    feature_version: str = BEHAVIOR_FEATURES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_behavior_feature_snapshot(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> dict[str, Any]:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")

    filing_history = db.scalars(
        select(Filing)
        .where(
            Filing.company_id == filing.company_id,
            Filing.form_type.in_(("10-K", "10-K/A", "10-Q", "10-Q/A")),
            Filing.filed_at < filing.filed_at,
        )
        .order_by(Filing.filed_at.desc(), Filing.id.desc())
        .limit(history_limit)
    ).all()
    history_filing_ids = [row.id for row in reversed(filing_history)]

    window_start = filing.filed_at - timedelta(days=WINDOW_BEFORE_DAYS)
    window_end = filing.filed_at + timedelta(days=WINDOW_AFTER_DAYS)

    rows = db.scalars(
        select(InsiderTransaction)
        .where(
            InsiderTransaction.company_id == filing.company_id,
            InsiderTransaction.transaction_date <= window_end,
        )
        .order_by(InsiderTransaction.transaction_date.asc(), InsiderTransaction.id.asc())
    ).all()

    economic_transactions = _economic_transactions(rows)
    historical_transactions = [row for row in economic_transactions if row.transaction_date < window_start]
    window_transactions = [
        row
        for row in economic_transactions
        if window_start <= row.transaction_date <= window_end
    ]

    historical_medians = _historical_medians(historical_transactions)
    classified_rows = [_classify_transaction(row, historical_medians) for row in window_transactions]
    governance_window_start = filing.filed_at - timedelta(days=GOVERNANCE_LOOKBACK_DAYS)
    governance_rows = [
        row
        for row in economic_transactions
        if governance_window_start <= row.transaction_date <= filing.filed_at
    ]
    late_filing_ratio = _late_filing_ratio(governance_rows)

    opportunistic_sells = [row for row in classified_rows if row["classification"] == "opportunistic_sell"]
    opportunistic_buys = [row for row in classified_rows if row["classification"] == "opportunistic_buy"]
    routine_rows = [row for row in classified_rows if row["classification"] == "routine"]
    active_insiders = _active_insiders(classified_rows)

    features = {
        "window_transaction_count": len(window_transactions),
        "historical_transaction_count": len(historical_transactions),
        "routine_transaction_count": len(routine_rows),
        "opportunistic_sell_count": len(opportunistic_sells),
        "opportunistic_buy_count": len(opportunistic_buys),
        "opportunistic_sell_value": _sum_transaction_value(opportunistic_sells),
        "opportunistic_buy_value": _sum_transaction_value(opportunistic_buys),
        "unique_sellers_in_window": len({row["insider_key"] for row in opportunistic_sells}),
        "active_insider_count": len(active_insiders),
        "late_filing_ratio": late_filing_ratio,
        "per_insider_activity": active_insiders,
        "historical_median_sizes": historical_medians,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }

    return BehaviorFeatureSnapshot(
        filing_id=filing.id,
        company_id=filing.company_id,
        anchor_filed_at=filing.filed_at,
        history_filing_ids=history_filing_ids,
        transaction_row_count=len(rows),
        feature_basis=(
            "behavior_features_v2 uses a +/-90 day filing window, "
            "historical per-insider median sizing, and role-aware opportunistic filtering"
        ),
        features=features,
    ).to_dict()


def compute_insider_features_for_filing(
    db: Session,
    *,
    filing_id: int,
    history_limit: int = 8,
) -> dict[str, Any]:
    return compute_behavior_feature_snapshot(db, filing_id=filing_id, history_limit=history_limit)


def _economic_transactions(rows: list[InsiderTransaction]) -> list[InsiderTransaction]:
    deduped: dict[tuple[Any, ...], InsiderTransaction] = {}
    for row in rows:
        key = (
            row.accession_number,
            row.insider_name,
            row.transaction_date,
            row.transaction_code,
            float(row.shares),
            float(row.price_per_share) if row.price_per_share is not None else None,
            row.ownership_nature,
            row.acquired_disposed_code,
            row.is_derivative,
        )
        deduped.setdefault(key, row)
    return list(deduped.values())


def _historical_medians(rows: list[InsiderTransaction]) -> dict[str, float]:
    sizes_by_insider: dict[str, list[float]] = {}
    for row in rows:
        sizes_by_insider.setdefault(_insider_key(row), []).append(float(row.shares))
    return {
        insider_key: float(median(sizes))
        for insider_key, sizes in sizes_by_insider.items()
        if sizes
    }


def _classify_transaction(
    row: InsiderTransaction,
    historical_medians: dict[str, float],
) -> dict[str, Any]:
    insider_key = _insider_key(row)
    role_name = _role_name(row)
    median_size = historical_medians.get(insider_key)
    shares = float(row.shares)
    transaction_value = (
        float(row.transaction_value)
        if row.transaction_value is not None
        else float(row.price_per_share or 0.0) * shares
    )

    is_routine = (
        row.transaction_code in ROUTINE_TRANSACTION_CODES
        or shares < 1000.0
        or role_name not in SENIOR_OPPORTUNISTIC_ROLES
    )

    classification = "routine"
    if not is_routine and median_size is not None and shares > median_size:
        if row.transaction_code == "S":
            classification = "opportunistic_sell"
        elif row.transaction_code == "P":
            classification = "opportunistic_buy"

    return {
        "insider_key": insider_key,
        "role_name": role_name,
        "role_weight": ROLE_WEIGHTS.get(role_name, ROLE_WEIGHTS["Other Officer"]),
        "classification": classification,
        "transaction_code": row.transaction_code,
        "transaction_date": row.transaction_date,
        "shares": shares,
        "transaction_value": transaction_value,
        "historical_median_size": median_size,
        "insider_name": row.insider_name,
    }


def _active_insiders(classified_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    activity: dict[str, dict[str, Any]] = {}
    for row in classified_rows:
        insider_key = row["insider_key"]
        current = activity.setdefault(
            insider_key,
            {
                "insider_name": row["insider_name"],
                "role_name": row["role_name"],
                "role_weight": row["role_weight"],
                "opportunistic_sell_value": 0.0,
                "opportunistic_buy_value": 0.0,
                "opportunistic_sell_count": 0,
                "opportunistic_buy_count": 0,
            },
        )
        if row["classification"] == "opportunistic_sell":
            current["opportunistic_sell_value"] += row["transaction_value"]
            current["opportunistic_sell_count"] += 1
        elif row["classification"] == "opportunistic_buy":
            current["opportunistic_buy_value"] += row["transaction_value"]
            current["opportunistic_buy_count"] += 1
    return activity


def _insider_key(row: InsiderTransaction) -> str:
    return f"{row.insider_cik or ''}|{row.insider_name.strip().lower()}"


def _role_name(row: InsiderTransaction) -> str:
    title = (row.officer_title or "").lower()
    if "chief executive officer" in title or title == "ceo":
        return "CEO"
    if "chief financial officer" in title or title == "cfo":
        return "CFO"
    if "president" in title:
        return "President"
    if "chief technology officer" in title or title == "cto":
        return "CTO"
    if "chief operating officer" in title or title == "coo":
        return "COO"
    if row.is_director:
        return "Director"
    return "Other Officer"


def _sum_transaction_value(rows: list[dict[str, Any]]) -> float:
    return float(sum(row["transaction_value"] for row in rows))


def _late_filing_ratio(rows: list[InsiderTransaction]) -> float:
    if not rows:
        return 0.0

    by_accession: dict[str, tuple[date, date | None]] = {}
    for row in rows:
        current = by_accession.get(row.accession_number)
        transaction_date = row.transaction_date
        filed_at = row.filed_at
        if current is None:
            by_accession[row.accession_number] = (transaction_date, filed_at)
            continue
        previous_transaction_date, previous_filed_at = current
        by_accession[row.accession_number] = (
            min(previous_transaction_date, transaction_date),
            previous_filed_at or filed_at,
        )

    late_count = 0
    for transaction_date, filed_at in by_accession.values():
        if filed_at is None:
            late_count += 1
            continue
        if _business_days_between(transaction_date, filed_at) > 2:
            late_count += 1

    return float(late_count / max(len(by_accession), 1))


def _business_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0

    day = start
    business_days = 0
    while day < end:
        day += timedelta(days=1)
        if day.weekday() < 5:
            business_days += 1
    return business_days
