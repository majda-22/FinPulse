from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.schemas import HealthResponse
from app.db.session import get_db

API_VERSION = "1.0.0"

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
def health_check() -> HealthResponse:
    try:
        with get_db() as db:
            db.execute(text("SELECT 1"))
        payload = HealthResponse(
            status="ok",
            db="connected",
            version=API_VERSION,
        )
        return payload
    except Exception:
        payload = HealthResponse(
            status="ok",
            db="error",
            version=API_VERSION,
        )
        return JSONResponse(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            content=payload.model_dump(),
        )
