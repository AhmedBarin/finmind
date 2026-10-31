from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.db.session import engine
from app.news.router import router as news_router
from app.news.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        await engine.dispose()


app = FastAPI(
    title="FinMind API",
    lifespan=lifespan,
)

app.include_router(news_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}