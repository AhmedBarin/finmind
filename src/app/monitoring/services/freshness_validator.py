"""Data-freshness validation service."""

from __future__ import annotations

from datetime import UTC, datetime

from app.monitoring.schemas.market_data import MarketDataPoint, TechnicalSignals


class DataFreshnessValidator:
    """Check whether market data and technical signals are fresh enough."""

    @staticmethod
    def validate_freshness(
        market_data: MarketDataPoint | None,
        signals: TechnicalSignals | None,
        max_staleness_hours: int,
    ) -> tuple[bool, str]:
        """Return ``(is_fresh, reason)``.

        * If either input is ``None`` the data is considered stale.
        * Otherwise the most recent ``updated_at`` / ``calculated_at``
          timestamp is compared against *max_staleness_hours*.
        """
        now = datetime.now(tz=UTC)

        if market_data is None and signals is None:
            return False, "Both market data and technical signals are missing"

        if market_data is None:
            return False, "Market data is missing"

        if signals is None:
            return False, "Technical signals are missing"

        # Use the *oldest* of the two timestamps to decide freshness
        md_ts = market_data.updated_at
        sig_ts = signals.calculated_at

        # Ensure timezone-aware for comparison
        if md_ts.tzinfo is None:
            md_ts = md_ts.replace(tzinfo=UTC)
        if sig_ts.tzinfo is None:
            sig_ts = sig_ts.replace(tzinfo=UTC)

        oldest_ts = min(md_ts, sig_ts)
        age_hours = (now - oldest_ts).total_seconds() / 3600

        if age_hours > max_staleness_hours:
            return False, (
                f"Data is stale: oldest timestamp {oldest_ts.isoformat()} "
                f"is {age_hours:.1f}h old (max {max_staleness_hours}h)"
            )

        return True, "Data is fresh"
