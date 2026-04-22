from fastapi import APIRouter

from app.api.v1.endpoints import companies, embeddings, filings, health, pipelines, score, signals

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(pipelines.router, prefix="/pipelines", tags=["pipelines"])
api_router.include_router(score.router, prefix="/score", tags=["score"])
api_router.include_router(signals.router, prefix="/signals", tags=["signals"])
api_router.include_router(filings.router, prefix="/filings", tags=["filings"])
api_router.include_router(embeddings.router, prefix="/embeddings", tags=["embeddings"])
