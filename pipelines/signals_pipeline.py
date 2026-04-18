"""
signals_pipeline.py

End-to-end signal pipeline for one 10-K or 10-Q filing. This pipeline runs
text, XBRL, insider, and composite signals in order and persists the final
signal state for the filing.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models.filing import Filing
from app.db.session import get_db
from ingestion.company_repo import log_event
from signals.composite_signals import compute_and_store_composite_signals
from signals.insider_signals import compute_and_store_insider_signals
from signals.market_signals import compute_and_store_market_signals
from signals.section_signals import compute_and_store_section_signals
from signals.sentiment_signals import compute_and_store_sentiment_signals
from signals.xbrl_signals import compute_and_store_xbrl_signals

logger = logging.getLogger("pipelines.signals_pipeline")

SignalStageRunner = Callable[..., list[dict[str, Any]]]

SIGNAL_STAGES: tuple[tuple[str, SignalStageRunner], ...] = (
    ("text", compute_and_store_section_signals),
    ("xbrl", compute_and_store_xbrl_signals),
    ("insider", compute_and_store_insider_signals),
    ("market", compute_and_store_market_signals),
    ("sentiment", compute_and_store_sentiment_signals),
    ("composite", compute_and_store_composite_signals),
)


@dataclass(slots=True)
class StageRunSummary:
    stage: str
    signal_count: int
    signal_names: list[str]
    not_available: list[str]
    processing_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SignalRunSummary:
    filing_id: int
    company_id: int
    accession_number: str
    form_type: str
    processing_status: str
    is_text_signal_scored: bool
    is_numeric_signal_scored: bool
    is_insider_signal_scored: bool
    is_composite_signal_scored: bool
    is_signal_scored: bool
    duration_ms: int
    stages: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalPipelineError(RuntimeError):
    def __init__(self, *, filing_id: int, stage: str, error: Exception) -> None:
        self.filing_id = filing_id
        self.stage = stage
        self.error = error
        super().__init__(f"Signal stage {stage!r} failed for filing id={filing_id}: {error}")


def run_all_signals(
    filing_id: int,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    if db is None:
        try:
            with get_db() as session:
                return run_all_signals(filing_id, db=session)
        except SignalPipelineError as exc:
            _mark_failed_in_new_session(filing_id=filing_id, error=str(exc), stage=exc.stage)
            raise
        except Exception as exc:
            _mark_failed_in_new_session(filing_id=filing_id, error=str(exc), stage="run_signals")
            raise

    try:
        return _run_all_signals_inner(filing_id=filing_id, db=db)
    except SignalPipelineError as exc:
        _mark_failed(db, filing_id=filing_id, error=str(exc), stage=exc.stage)
        raise
    except Exception as exc:
        _mark_failed(db, filing_id=filing_id, error=str(exc), stage="run_signals")
        raise


def _run_all_signals_inner(
    *,
    filing_id: int,
    db: Session,
) -> dict[str, Any]:
    t0 = time.monotonic()

    filing = db.get(Filing, filing_id)
    if filing is None:
        raise RuntimeError(f"Filing id={filing_id} not found in database")
    if filing.form_type not in {"10-K", "10-Q"}:
        raise RuntimeError(
            f"run_signals should target a 10-K or 10-Q, got {filing.form_type!r} "
            f"for filing id={filing.id}"
        )

    logger.info(
        "Running full signal pipeline for filing id=%d  %s  %s",
        filing.id,
        filing.form_type,
        filing.accession_number,
    )

    stage_summaries: list[dict[str, Any]] = []

    for stage_name, runner in SIGNAL_STAGES:
        logger.info("Running %s signals for filing %d", stage_name, filing.id)

        try:
            signals = runner(filing.id, db=db)
        except Exception as exc:
            raise SignalPipelineError(filing_id=filing.id, stage=stage_name, error=exc) from exc

        stage_summaries.append(
            StageRunSummary(
                stage=stage_name,
                signal_count=len(signals),
                signal_names=[str(signal["signal_name"]) for signal in signals],
                not_available=[
                    str(signal["signal_name"])
                    for signal in signals
                    if signal.get("signal_value") is None
                ],
                processing_status=filing.processing_status,
            ).to_dict()
        )

    filing.processing_status = "signal_scored"
    filing.last_error_message = None
    db.flush()

    duration_ms = int((time.monotonic() - t0) * 1000)
    log_event(
        db,
        event_type="signal_scored",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        duration_ms=duration_ms,
        detail={
            "step": "run_signals",
            "stages": [summary["stage"] for summary in stage_summaries],
            "stage_signal_counts": {
                summary["stage"]: summary["signal_count"] for summary in stage_summaries
            },
            "not_available": {
                summary["stage"]: summary["not_available"] for summary in stage_summaries
            },
        },
    )

    summary = SignalRunSummary(
        filing_id=filing.id,
        company_id=filing.company_id,
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        processing_status=filing.processing_status,
        is_text_signal_scored=filing.is_text_signal_scored,
        is_numeric_signal_scored=filing.is_numeric_signal_scored,
        is_insider_signal_scored=filing.is_insider_signal_scored,
        is_composite_signal_scored=filing.is_composite_signal_scored,
        is_signal_scored=filing.is_signal_scored,
        duration_ms=duration_ms,
        stages=stage_summaries,
    )

    logger.info(
        "Completed full signal pipeline for filing %d in %dms",
        filing.id,
        duration_ms,
    )
    return summary.to_dict()


def _mark_failed(
    db: Session,
    *,
    filing_id: int,
    error: str,
    stage: str,
) -> None:
    filing = db.get(Filing, filing_id)
    if filing is None:
        return

    filing.processing_status = "failed"
    filing.last_error_message = error

    log_event(
        db,
        event_type="failed",
        layer="processing",
        company_id=filing.company_id,
        filing_id=filing.id,
        detail={
            "step": "run_signals",
            "stage": stage,
            "error": error,
        },
    )


def _mark_failed_in_new_session(
    *,
    filing_id: int,
    error: str,
    stage: str,
) -> None:
    try:
        with get_db() as db:
            _mark_failed(db, filing_id=filing_id, error=error, stage=stage)
    except Exception:
        logger.exception("Failed to persist run_signals failure state for filing %d", filing_id)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full signal pipeline for one filing")
    parser.add_argument("--filing-id", type=int, required=True, help="Database filing id")
    return parser.parse_args()


def main(filing_id: int) -> dict[str, Any]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    result = run_all_signals(filing_id)
    print(result)
    return result


if __name__ == "__main__":
    args = _parse_args()
    main(args.filing_id)
