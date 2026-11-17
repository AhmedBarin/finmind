"""Request-scoped database dependency for recommendation endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal


async def get_recommendation_session() -> AsyncIterator[AsyncSession]:
    """Yield a session and commit successful request writes."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
