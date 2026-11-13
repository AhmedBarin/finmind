from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import engine
from app.monitoring.routers import monitoring_router
from app.news.router import router as news_router
from app.monitoring.scheduler import (
    start_monitoring_scheduler,
    stop_monitoring_scheduler,
)
from app.news.scheduler import start_scheduler, stop_scheduler
from app.technical_analysis.router import router as technical_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    start_scheduler()
    start_monitoring_scheduler()
    try:
        yield
    finally:
        stop_monitoring_scheduler()
        stop_scheduler()
        await engine.dispose()


app = FastAPI(
    title="FinMind API",
    lifespan=lifespan,
)

app.include_router(news_router)
app.include_router(
    monitoring_router,
    prefix="/api/v1/monitoring",
    tags=["monitoring"],
)
app.include_router(technical_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
