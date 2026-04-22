from __future__ import annotations

import inspect
from datetime import datetime, timezone
from threading import Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

PipelineRunner = Callable[[], Any]

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = Lock()


def submit_pipeline_job(
    *,
    pipeline_name: str,
    request_payload: dict[str, Any],
    status_url: str,
    runner: PipelineRunner,
) -> dict[str, Any]:
    job_id = uuid4().hex
    record = {
        "job_id": job_id,
        "pipeline_name": pipeline_name,
        "status": "queued",
        "submitted_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "status_url": status_url,
        "request": jsonable_encoder(request_payload),
        "result": None,
        "error": None,
    }

    with _jobs_lock:
        _jobs[job_id] = record

    thread = Thread(
        target=_run_pipeline_job,
        args=(job_id, runner),
        daemon=True,
        name=f"pipeline-job-{job_id[:8]}",
    )
    thread.start()
    return get_pipeline_job(job_id)


def get_pipeline_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return dict(job)


def _run_pipeline_job(job_id: str, runner: PipelineRunner) -> None:
    _update_pipeline_job(
        job_id,
        status="running",
        started_at=_utc_now(),
        error=None,
    )

    try:
        result = runner()
        if inspect.isawaitable(result):
            import asyncio

            result = asyncio.run(result)
    except Exception as exc:
        _update_pipeline_job(
            job_id,
            status="failed",
            finished_at=_utc_now(),
            error=str(exc),
        )
        return

    _update_pipeline_job(
        job_id,
        status="completed",
        finished_at=_utc_now(),
        result=jsonable_encoder(result),
        error=None,
    )


def _update_pipeline_job(job_id: str, **updates: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(updates)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
