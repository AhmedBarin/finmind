"""Notification dispatcher – delivers alert notifications.

Provides a base class and a no-op implementation that simply logs at
INFO level.  Concrete dispatchers (email, webhook, push) can subclass
``BaseNotificationDispatcher`` in the future.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.monitoring.models.alert import Alert

logger = logging.getLogger(__name__)


class BaseNotificationDispatcher(ABC):
    """Abstract base for notification delivery."""

    @abstractmethod
    async def dispatch(self, alert: Alert) -> None:  # pragma: no cover
        """Send a notification for *alert*."""


class NoOpNotificationDispatcher(BaseNotificationDispatcher):
    """Dispatcher that logs the alert at INFO level without sending anything."""

    async def dispatch(self, alert: Alert) -> None:
        logger.info(
            "Alert dispatched (no-op): id=%s rule_id=%s ticker=%s severity=%s reason=%s",
            alert.id,
            alert.rule_id,
            alert.ticker,
            alert.severity,
            alert.reason,
        )
