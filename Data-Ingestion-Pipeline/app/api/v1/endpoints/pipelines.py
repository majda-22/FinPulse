from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.pipeline_jobs import get_pipeline_job, submit_pipeline_job
from app.api.v1.endpoints.score import _get_company_or_404
from app.api.v1.schemas import (
    BackfillCompanyRequest,
    CompanySignalsRunRequest,
    PipelineJobAcceptedResponse,
    PipelineJobStatusResponse,
)
from app.db.models.filing import Filing
from app.db.session import get_db_dependency
from pipelines.run_backfill_company import run_backfill_company
from pipelines.signals_pipeline import run_all_signals

router = APIRouter()

SIGNAL_ELIGIBLE_FORMS = {
    "10-K",
    "10-Q",
}


@router.post(
    "/backfill/company",
    response_model=PipelineJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_company_backfill(
    request: BackfillCompanyRequest,
    db: Session = Depends(get_db_dependency),
) -> PipelineJobAcceptedResponse:
    source = _resolve_backfill_source(db, request.identifier)
    status_url = _build_status_url_placeholder()
    job = submit_pipeline_job(
        pipeline_name="company_backfill",
        request_payload={
            **request.model_dump(mode="json"),
            **source,
        },
        status_url=status_url,
        runner=lambda: run_backfill_company(
            ticker=source["ticker"],
            cik=source["cik"],
            ten_k_max=request.ten_k_max,
            ten_q_max=request.ten_q_max,
            form4_max=request.form4_max,
            form4_parse_limit=request.form4_parse_limit,
            news_limit=request.news_limit,
            symbol=request.symbol,
            filing_start=request.filing_start,
            filing_end=request.filing_end,
            market_start=request.market_start,
            market_end=request.market_end,
            macro_start=request.macro_start,
            macro_end=request.macro_end,
            macro_series=request.macro_series,
            run_signals=request.run_signals,
        ),
    )
    return PipelineJobAcceptedResponse(**_with_real_status_url(job))


@router.post(
    "/signals/company",
    response_model=PipelineJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_company_signal_batch(
    request: CompanySignalsRunRequest,
    db: Session = Depends(get_db_dependency),
) -> PipelineJobAcceptedResponse:
    company = _get_company_or_404(db, request.identifier)
    form_types = _normalize_signal_form_types(request.form_types)

    query = (
        select(Filing.id)
        .where(
            Filing.company_id == company.id,
            Filing.form_type.in_(tuple(form_types)),
        )
        .order_by(Filing.filed_at.asc(), Filing.id.asc())
    )
    if request.limit is not None:
        query = query.limit(request.limit)

    filing_ids = list(db.scalars(query).all())
    if not filing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No signal-eligible filings were found for {company.ticker!r} "
                f"with form types {form_types!r}."
            ),
        )

    status_url = _build_status_url_placeholder()
    job = submit_pipeline_job(
        pipeline_name="company_signal_batch",
        request_payload={
            **request.model_dump(mode="json"),
            "form_types": form_types,
            "company_id": company.id,
            "ticker": company.ticker,
            "cik": company.cik,
            "selected_filing_count": len(filing_ids),
        },
        status_url=status_url,
        runner=lambda: _run_signal_batch(
            company_id=company.id,
            ticker=company.ticker,
            filing_ids=filing_ids,
        ),
    )
    return PipelineJobAcceptedResponse(**_with_real_status_url(job))


@router.post(
    "/signals/filing/{filing_id}",
    response_model=PipelineJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_filing_signal_run(
    filing_id: int,
    db: Session = Depends(get_db_dependency),
) -> PipelineJobAcceptedResponse:
    filing = db.get(Filing, filing_id)
    if filing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Filing id={filing_id} was not found in the database.",
        )
    if filing.form_type not in SIGNAL_ELIGIBLE_FORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Signals can only be run for anchor filings. "
                f"Got form_type={filing.form_type!r} for filing id={filing_id}."
            ),
        )

    status_url = _build_status_url_placeholder()
    job = submit_pipeline_job(
        pipeline_name="filing_signal_run",
        request_payload={
            "filing_id": filing.id,
            "company_id": filing.company_id,
            "accession_number": filing.accession_number,
            "form_type": filing.form_type,
        },
        status_url=status_url,
        runner=lambda: run_all_signals(filing.id),
    )
    return PipelineJobAcceptedResponse(**_with_real_status_url(job))


@router.get(
    "/jobs/{job_id}",
    response_model=PipelineJobStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_pipeline_job_status(job_id: str) -> PipelineJobStatusResponse:
    job = get_pipeline_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline job {job_id!r} was not found.",
        )
    return PipelineJobStatusResponse(**_with_real_status_url(job))


def _resolve_backfill_source(db: Session, identifier: str) -> dict[str, Any]:
    normalized = " ".join(identifier.split()).strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="identifier must not be empty",
        )

    try:
        company = _get_company_or_404(db, normalized)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        company = None

    if company is not None:
        ticker = company.ticker if company.ticker and not company.ticker.isdigit() else None
        cik = None if ticker else company.cik
        return {
            "ticker": ticker,
            "cik": cik,
            "resolved_company_id": company.id,
            "resolved_company_name": company.name,
        }

    if normalized.isdigit():
        return {
            "ticker": None,
            "cik": normalized.zfill(10),
            "resolved_company_id": None,
            "resolved_company_name": None,
        }

    return {
        "ticker": normalized.upper(),
        "cik": None,
        "resolved_company_id": None,
        "resolved_company_name": None,
    }


def _normalize_signal_form_types(form_types: list[str]) -> list[str]:
    normalized = sorted(
        {
            form_type.strip().upper()
            for form_type in form_types
            if form_type.strip()
        }
    )
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="form_types must include at least one supported filing type.",
        )

    unsupported = [form_type for form_type in normalized if form_type not in SIGNAL_ELIGIBLE_FORMS]
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Only 10-K and 10-Q filings are currently supported by the signal runner.",
                "unsupported_form_types": unsupported,
                "supported_form_types": sorted(SIGNAL_ELIGIBLE_FORMS),
            },
        )
    return normalized


def _run_signal_batch(
    *,
    company_id: int,
    ticker: str,
    filing_ids: list[int],
) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for filing_id in filing_ids:
        try:
            summary = run_all_signals(filing_id)
        except Exception as exc:
            failures.append(
                {
                    "filing_id": filing_id,
                    "error": str(exc),
                }
            )
            continue

        completed.append(
            {
                "filing_id": summary["filing_id"],
                "form_type": summary["form_type"],
                "processing_status": summary["processing_status"],
                "duration_ms": summary["duration_ms"],
                "stage_count": len(summary["stages"]),
            }
        )

    return {
        "company_id": company_id,
        "ticker": ticker,
        "selected": len(filing_ids),
        "processed": len(completed),
        "failed": len(failures),
        "results": completed,
        "failures": failures,
    }


def _build_status_url_placeholder() -> str:
    return "/api/v1/pipelines/jobs/__JOB_ID__"


def _with_real_status_url(job: dict[str, Any]) -> dict[str, Any]:
    return {
        **job,
        "status_url": job["status_url"].replace("__JOB_ID__", str(job["job_id"])),
    }
