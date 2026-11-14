"""Technical API database dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal


async def get_technical_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped async database session."""
    async with SessionLocal() as session:
        yield session
