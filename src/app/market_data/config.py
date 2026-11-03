"""Market-data quality settings; the calendar is provisional until holidays are added."""

from datetime import date


# Python weekday numbers: Monday=0 ... Sunday=6. EGX currently trades Sunday–Thursday.
EGX_TRADING_WEEKDAYS = frozenset({6, 0, 1, 2, 3})
EGX_HOLIDAYS: frozenset[date] = frozenset()

MINIMUM_HISTORY_SESSIONS = 200
PERCENTILE_HISTORY_SESSIONS = 252
ZERO_VOLUME_LOOKBACK_SESSIONS = 20
MAX_ABS_PRICE_CHANGE = 0.15
