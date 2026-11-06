"""Monitoring routers – combined APIRouter."""

from fastapi import APIRouter

from app.monitoring.routers.admin_router import router as admin_router
from app.monitoring.routers.alerts_router import router as alerts_router
from app.monitoring.routers.rules_router import router as rules_router

monitoring_router = APIRouter()
monitoring_router.include_router(rules_router)
monitoring_router.include_router(alerts_router)
monitoring_router.include_router(admin_router)

__all__ = ["monitoring_router"]
