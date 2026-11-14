from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.core.config import settings
from app.db.session import engine
from app.investor.checkpointer import open_postgres_checkpointer
from app.investor.graph import build_interview_graph
from app.investor.llm_extraction import build_default_extractor
from app.investor.router import router as investor_router
from app.monitoring.routers import monitoring_router
from app.news.router import router as news_router
from app.monitoring.scheduler import (
    start_monitoring_scheduler,
    stop_monitoring_scheduler,
)
from app.news.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            open_postgres_checkpointer(settings.database_url, setup=True)
        )
        app.state.investor_graph = build_interview_graph(
            checkpointer=checkpointer,
            extractor=build_default_extractor(
                ollama_base_url=settings.ollama_base_url,
                model=settings.investor_llm_model,
                timeout_seconds=settings.investor_llm_timeout_seconds,
                think=settings.investor_llm_think,
                num_ctx=settings.investor_llm_num_ctx,
            ),
        )
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
app.include_router(investor_router)


_INVESTOR_CHAT_PAGE = Path(__file__).parent / "investor" / "static" / "chat.html"


@app.get("/investor/chat", include_in_schema=False)
async def investor_chat_page() -> FileResponse:
    """Developer chat page for trying the Investor Agent interview."""
    return FileResponse(_INVESTOR_CHAT_PAGE, media_type="text/html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
