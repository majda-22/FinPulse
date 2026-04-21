from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.filing import Filing
from app.db.models.nci_score import NciScore
from app.db.session import get_db


EXPORT_ROOT = Path("data/exports/signal_validation")
FLAT_RANGE_THRESHOLD = 0.05
ALWAYS_HIGH_THRESHOLD = 0.75
SIGNAL_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
)

SIGNAL_SPECS: tuple[tuple[str, str, str], ...] = (
    ("signal_text", "text_drift", "Text Drift"),
    ("signal_fundamental", "fundamentals", "Fundamentals"),
    ("signal_balance", "balance", "Balance"),
    ("signal_growth", "growth", "Growth"),
    ("signal_earnings", "earnings_quality", "Earnings Quality"),
    ("signal_anomaly", "anomaly", "Anomaly"),
    ("signal_insider", "insider", "Insider"),
    ("signal_market", "market", "Market"),
    ("signal_sentiment", "sentiment", "Sentiment"),
)


@dataclass(slots=True)
class RawSignalRecord:
    ticker: str
    filing_id: int | None
    filed_at: date | None
    year: int
    fiscal_quarter: int | None
    event_type: str
    confidence: str | None
    coverage_ratio: float | None
    signal_key: str
    signal_label: str
    signal_value: float | None


@dataclass(slots=True)
class YearlySignalAggregate:
    ticker: str
    year: int
    signal_key: str
    signal_label: str
    point_count: int
    non_null_points: int
    mean_value: float | None
    last_value: float | None
    min_value: float | None
    max_value: float | None


@dataclass(slots=True)
class SignalValidationFlag:
    ticker: str
    signal_key: str
    signal_label: str
    yearly_points: int
    min_value: float | None
    max_value: float | None
    mean_value: float | None
    range_value: float | None
    verdict: str
    recommendation: str


def generate_signal_validation_report(
    *,
    tickers: list[str],
    output_dir: Path = EXPORT_ROOT,
    db: Session | None = None,
) -> dict[str, Any]:
    normalized_tickers = [ticker.strip().upper() for ticker in tickers if ticker and ticker.strip()]
    if not normalized_tickers:
        raise ValueError("Provide at least one ticker")

    if db is None:
        with get_db() as session:
            return generate_signal_validation_report(
                tickers=normalized_tickers,
                output_dir=output_dir,
                db=session,
            )

    rows = _load_nci_rows(db, tickers=normalized_tickers)
    raw_records = _build_raw_records(rows)
    yearly_records = _aggregate_yearly(raw_records)
    flags = _build_signal_flags(yearly_records)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = output_dir / "signal_validation_raw.csv"
    yearly_csv = output_dir / "signal_validation_yearly.csv"
    flags_csv = output_dir / "signal_validation_flags.csv"
    summary_md = output_dir / "signal_validation_summary.md"

    _write_raw_csv(raw_csv, raw_records)
    _write_yearly_csv(yearly_csv, yearly_records)
    _write_flags_csv(flags_csv, flags)
    _write_summary_markdown(summary_md, tickers=normalized_tickers, flags=flags)

    chart_paths: list[str] = []
    for ticker in normalized_tickers:
        chart_path = output_dir / f"{ticker.lower()}_signal_validation.svg"
        _write_company_svg(chart_path, ticker=ticker, yearly_records=yearly_records, flags=flags)
        chart_paths.append(str(chart_path))

    return {
        "tickers": normalized_tickers,
        "raw_csv": str(raw_csv),
        "yearly_csv": str(yearly_csv),
        "flags_csv": str(flags_csv),
        "summary_md": str(summary_md),
        "charts": chart_paths,
        "row_count": len(raw_records),
        "yearly_count": len(yearly_records),
        "flag_count": len(flags),
    }


def _load_nci_rows(
    db: Session,
    *,
    tickers: list[str],
) -> list[Any]:
    stmt = (
        select(
            Company.ticker,
            Filing.id.label("filing_id"),
            Filing.filed_at,
            NciScore.fiscal_year,
            NciScore.fiscal_quarter,
            NciScore.event_type,
            NciScore.confidence,
            NciScore.coverage_ratio,
            NciScore.signal_text,
            NciScore.signal_fundamental,
            NciScore.signal_balance,
            NciScore.signal_growth,
            NciScore.signal_earnings,
            NciScore.signal_anomaly,
            NciScore.signal_insider,
            NciScore.signal_market,
            NciScore.signal_sentiment,
        )
        .join(Company, Company.id == NciScore.company_id)
        .outerjoin(Filing, Filing.id == NciScore.filing_id)
        .where(Company.ticker.in_(tickers))
        .order_by(Company.ticker.asc(), Filing.filed_at.asc(), NciScore.computed_at.asc(), NciScore.id.asc())
    )
    return list(db.execute(stmt).all())


def _build_raw_records(rows: Iterable[Any]) -> list[RawSignalRecord]:
    records: list[RawSignalRecord] = []
    for row in rows:
        row_map = row._mapping
        year = _coerce_year(
            fiscal_year=row_map.get("fiscal_year"),
            filed_at=row_map.get("filed_at"),
        )
        for column_name, signal_key, signal_label in SIGNAL_SPECS:
            signal_value = row_map.get(column_name)
            records.append(
                RawSignalRecord(
                    ticker=str(row_map["ticker"]),
                    filing_id=row_map.get("filing_id"),
                    filed_at=row_map.get("filed_at"),
                    year=year,
                    fiscal_quarter=row_map.get("fiscal_quarter"),
                    event_type=str(row_map.get("event_type") or ""),
                    confidence=row_map.get("confidence"),
                    coverage_ratio=_coerce_float(row_map.get("coverage_ratio")),
                    signal_key=signal_key,
                    signal_label=signal_label,
                    signal_value=_coerce_float(signal_value),
                )
            )
    return records


def _aggregate_yearly(raw_records: list[RawSignalRecord]) -> list[YearlySignalAggregate]:
    grouped: dict[tuple[str, int, str], list[RawSignalRecord]] = defaultdict(list)
    for record in raw_records:
        grouped[(record.ticker, record.year, record.signal_key)].append(record)

    yearly: list[YearlySignalAggregate] = []
    for (ticker, year, signal_key), records in sorted(grouped.items()):
        non_null_values = [record.signal_value for record in records if record.signal_value is not None]
        mean_value = mean(non_null_values) if non_null_values else None
        last_value = next((record.signal_value for record in reversed(records) if record.signal_value is not None), None)
        yearly.append(
            YearlySignalAggregate(
                ticker=ticker,
                year=year,
                signal_key=signal_key,
                signal_label=records[0].signal_label,
                point_count=len(records),
                non_null_points=len(non_null_values),
                mean_value=mean_value,
                last_value=last_value,
                min_value=min(non_null_values) if non_null_values else None,
                max_value=max(non_null_values) if non_null_values else None,
            )
        )
    return yearly


def _build_signal_flags(yearly_records: list[YearlySignalAggregate]) -> list[SignalValidationFlag]:
    grouped: dict[tuple[str, str], list[YearlySignalAggregate]] = defaultdict(list)
    for record in yearly_records:
        grouped[(record.ticker, record.signal_key)].append(record)

    flags: list[SignalValidationFlag] = []
    for (ticker, signal_key), records in sorted(grouped.items()):
        values = [record.mean_value for record in records if record.mean_value is not None]
        verdict, recommendation = _classify_signal_behavior(values)
        min_value = min(values) if values else None
        max_value = max(values) if values else None
        mean_value = mean(values) if values else None
        range_value = (max_value - min_value) if min_value is not None and max_value is not None else None
        flags.append(
            SignalValidationFlag(
                ticker=ticker,
                signal_key=signal_key,
                signal_label=records[0].signal_label,
                yearly_points=len(values),
                min_value=min_value,
                max_value=max_value,
                mean_value=mean_value,
                range_value=range_value,
                verdict=verdict,
                recommendation=recommendation,
            )
        )
    return flags


def _classify_signal_behavior(values: list[float | None]) -> tuple[str, str]:
    defined = [float(value) for value in values if value is not None]
    if not defined:
        return "missing", "Disable until data coverage or computation is fixed."
    if len(defined) == 1:
        return "sparse", "Collect more years before trusting this signal."
    if all(abs(value) < 1e-9 for value in defined):
        return "always_zero", "Review the formula or leave disabled until it shows real variation."

    range_value = max(defined) - min(defined)
    if len(defined) >= 3 and range_value <= FLAT_RANGE_THRESHOLD:
        return "flat", "Review calibration; disable until fixed if it does not track real events."
    if len(defined) >= 3 and min(defined) >= ALWAYS_HIGH_THRESHOLD:
        return "always_high", "Review calibration; this looks saturated and may be mis-scaled."
    return "variable", "Keep enabled and compare the turning points against known company events."


def _write_raw_csv(path: Path, records: list[RawSignalRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "filing_id",
                "filed_at",
                "year",
                "fiscal_quarter",
                "event_type",
                "confidence",
                "coverage_ratio",
                "signal_key",
                "signal_label",
                "signal_value",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.ticker,
                    record.filing_id,
                    record.filed_at.isoformat() if record.filed_at else "",
                    record.year,
                    record.fiscal_quarter,
                    record.event_type,
                    record.confidence or "",
                    record.coverage_ratio if record.coverage_ratio is not None else "",
                    record.signal_key,
                    record.signal_label,
                    record.signal_value if record.signal_value is not None else "",
                ]
            )


def _write_yearly_csv(path: Path, records: list[YearlySignalAggregate]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "year",
                "signal_key",
                "signal_label",
                "point_count",
                "non_null_points",
                "mean_value",
                "last_value",
                "min_value",
                "max_value",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.ticker,
                    record.year,
                    record.signal_key,
                    record.signal_label,
                    record.point_count,
                    record.non_null_points,
                    record.mean_value if record.mean_value is not None else "",
                    record.last_value if record.last_value is not None else "",
                    record.min_value if record.min_value is not None else "",
                    record.max_value if record.max_value is not None else "",
                ]
            )


def _write_flags_csv(path: Path, flags: list[SignalValidationFlag]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ticker",
                "signal_key",
                "signal_label",
                "yearly_points",
                "min_value",
                "max_value",
                "mean_value",
                "range_value",
                "verdict",
                "recommendation",
            ]
        )
        for flag in flags:
            writer.writerow(
                [
                    flag.ticker,
                    flag.signal_key,
                    flag.signal_label,
                    flag.yearly_points,
                    flag.min_value if flag.min_value is not None else "",
                    flag.max_value if flag.max_value is not None else "",
                    flag.mean_value if flag.mean_value is not None else "",
                    flag.range_value if flag.range_value is not None else "",
                    flag.verdict,
                    flag.recommendation,
                ]
            )


def _write_summary_markdown(
    path: Path,
    *,
    tickers: list[str],
    flags: list[SignalValidationFlag],
) -> None:
    grouped: dict[str, list[SignalValidationFlag]] = defaultdict(list)
    for flag in flags:
        grouped[flag.ticker].append(flag)

    lines = [
        "# Signal Validation Summary",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Tickers: {', '.join(tickers)}",
        "",
    ]

    for ticker in tickers:
        lines.append(f"## {ticker}")
        lines.append("")
        lines.append("| Signal | Verdict | Range | Recommendation |")
        lines.append("| --- | --- | --- | --- |")
        for flag in sorted(grouped.get(ticker, []), key=lambda row: row.signal_key):
            range_text = "" if flag.range_value is None else f"{flag.range_value:.3f}"
            lines.append(
                f"| {flag.signal_label} | {flag.verdict} | {range_text} | {flag.recommendation} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_company_svg(
    path: Path,
    *,
    ticker: str,
    yearly_records: list[YearlySignalAggregate],
    flags: list[SignalValidationFlag],
) -> None:
    company_records = [record for record in yearly_records if record.ticker == ticker]
    years = sorted({record.year for record in company_records})
    flag_map = {
        flag.signal_key: flag
        for flag in flags
        if flag.ticker == ticker
    }

    width = 1200
    height = 760
    left = 80
    top = 60
    right = 320
    bottom = 70
    inner_width = width - left - right
    inner_height = height - top - bottom

    if not years:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<text x="40" y="80" font-size="28" font-family="Arial">No yearly NCI data for {ticker}</text>
</svg>"""
        path.write_text(svg, encoding="utf-8")
        return

    def x_for_year(year: int) -> float:
        if len(years) == 1:
            return left + (inner_width / 2)
        year_index = years.index(year)
        return left + (inner_width * year_index / max(len(years) - 1, 1))

    def y_for_value(value: float) -> float:
        return top + ((1.0 - value) * inner_height)

    grid_lines: list[str] = []
    for step in (0.0, 0.25, 0.50, 0.75, 1.0):
        y = y_for_value(step)
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + inner_width}" y2="{y:.1f}" stroke="#dddddd" stroke-width="1"/>'
        )
        grid_lines.append(
            f'<text x="{left - 10}" y="{y + 5:.1f}" text-anchor="end" font-size="12" font-family="Arial" fill="#666">{step:.2f}</text>'
        )

    year_labels = [
        f'<text x="{x_for_year(year):.1f}" y="{top + inner_height + 24}" text-anchor="middle" font-size="12" font-family="Arial" fill="#444">{year}</text>'
        for year in years
    ]

    legend_lines: list[str] = []
    series_lines: list[str] = []

    for index, (column_name, signal_key, signal_label) in enumerate(SIGNAL_SPECS):
        color = SIGNAL_COLORS[index % len(SIGNAL_COLORS)]
        signal_records = [record for record in company_records if record.signal_key == signal_key]
        points = [
            (x_for_year(record.year), y_for_value(record.mean_value), record.mean_value, record.year)
            for record in signal_records
            if record.mean_value is not None
        ]
        if points:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in points)
            series_lines.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{point_text}"/>'
            )
            for x, y, value, year in points:
                series_lines.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"><title>{signal_label} {year}: {value:.3f}</title></circle>'
                )

        legend_y = top + 10 + (index * 28)
        verdict = flag_map.get(signal_key).verdict if signal_key in flag_map else "unknown"
        legend_lines.append(
            f'<line x1="{left + inner_width + 20}" y1="{legend_y:.1f}" x2="{left + inner_width + 45}" y2="{legend_y:.1f}" stroke="{color}" stroke-width="3"/>'
        )
        legend_lines.append(
            f'<text x="{left + inner_width + 55}" y="{legend_y + 4:.1f}" font-size="12" font-family="Arial" fill="#222">{signal_label} ({verdict})</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<text x="40" y="34" font-size="28" font-family="Arial" fill="#111">{ticker} Signal Validation</text>
<text x="40" y="54" font-size="13" font-family="Arial" fill="#666">Per-year mean values from filing-anchored NCI layer fields (0.0 to 1.0 scale)</text>
<rect x="{left}" y="{top}" width="{inner_width}" height="{inner_height}" fill="none" stroke="#bbbbbb" stroke-width="1"/>
{''.join(grid_lines)}
{''.join(year_labels)}
{''.join(series_lines)}
{''.join(legend_lines)}
</svg>"""
    path.write_text(svg, encoding="utf-8")


def _coerce_year(*, fiscal_year: int | None, filed_at: date | None) -> int:
    if fiscal_year is not None:
        return int(fiscal_year)
    if filed_at is not None:
        return int(filed_at.year)
    return int(datetime.now().year)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate per-year signal behavior across selected companies")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=["AAPL", "NKLA", "TSLA"],
        help="Ticker list to validate, e.g. --tickers AAPL NKLA TSLA",
    )
    parser.add_argument(
        "--output-dir",
        default=str(EXPORT_ROOT),
        help="Directory for CSV, Markdown, and SVG outputs",
    )
    return parser.parse_args()


def main(*, tickers: list[str] | None = None, output_dir: str | None = None) -> dict[str, Any]:
    args = _parse_args() if tickers is None else None
    selected_tickers = tickers or args.tickers
    selected_output_dir = Path(output_dir or (args.output_dir if args else EXPORT_ROOT))

    result = generate_signal_validation_report(
        tickers=selected_tickers,
        output_dir=selected_output_dir,
    )

    print("\nSignal Validation Report")
    print(f"  Tickers:       {', '.join(result['tickers'])}")
    print(f"  Raw CSV:       {result['raw_csv']}")
    print(f"  Yearly CSV:    {result['yearly_csv']}")
    print(f"  Flags CSV:     {result['flags_csv']}")
    print(f"  Summary MD:    {result['summary_md']}")
    print(f"  Charts:        {len(result['charts'])}")
    print(f"  Raw rows:      {result['row_count']}")
    print(f"  Yearly points: {result['yearly_count']}")
    print(f"  Flags:         {result['flag_count']}")
    return result


if __name__ == "__main__":
    main()
