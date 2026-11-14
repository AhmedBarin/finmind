from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from app.api.error_handlers import safe_unhandled_error
from app.api.middleware import TraceIdMiddleware
from app.api.middleware import check_news_agent_rate_limit
from app.core.security import require_news_agent_auth

from app.db.session import engine
from app.monitoring.routers import monitoring_router
from app.news.router import router as news_router
from app.monitoring.scheduler import (
    start_monitoring_scheduler,
    stop_monitoring_scheduler,
)
from app.news.scheduler import start_scheduler, stop_scheduler


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
app.add_middleware(TraceIdMiddleware)
app.add_exception_handler(Exception, safe_unhandled_error)

app.include_router(news_router)
app.include_router(
    news_router,
    prefix="/api/v1",
    dependencies=[Depends(require_news_agent_auth), Depends(check_news_agent_rate_limit)],
)
app.include_router(
    monitoring_router,
    prefix="/api/v1/monitoring",
    tags=["monitoring"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    from app.core.config import settings

    if not settings.groq_api_key or not settings.news_analysis_model:
        raise HTTPException(status_code=503, detail="News analysis configuration is unavailable")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ready"}
