"""Number grounding: every number the agent writes must come from a tool result.

A written number is grounded when some tool value rounds to it at the
precision it was written with (``56.2`` matches a stored ``56.2347``). Numbers
the agent derives itself (percent changes, differences) are not grounded.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_THOUSANDS = re.compile(r"(?<=\d)[,٬](?=\d{3}(?!\d))")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# Indicator window lengths appear in names ("SMA 20", "RSI 14"), not as claims.
INDICATOR_NAME_NUMBERS = frozenset({14.0, 20.0, 50.0})


def normalize_digits(text: str) -> str:
    return _THOUSANDS.sub("", text.translate(_DIGITS))


def extract_numbers(text: str) -> list[str]:
    return _NUMBER.findall(normalize_digits(text))


def collect_numbers(value: Any, into: set[float] | None = None) -> set[float]:
    """Every number in a JSON-like structure, including digits inside strings."""
    numbers = into if into is not None else set()
    if isinstance(value, bool) or value is None:
        return numbers
    if isinstance(value, (int, float)):
        numbers.add(abs(float(value)))
    elif isinstance(value, str):
        numbers.update(float(n) for n in extract_numbers(value))
    elif isinstance(value, dict):
        for item in value.values():
            collect_numbers(item, numbers)
    elif isinstance(value, (list, tuple)):
        for item in value:
            collect_numbers(item, numbers)
    return numbers


def _decimals(written: str) -> int:
    return len(written.split(".", 1)[1]) if "." in written else 0


def is_grounded(written: str, allowed: Iterable[float]) -> bool:
    """True when a tool value rounds (half up or half down) to ``written``."""
    target = float(written)
    tolerance = 0.5 * 10 ** (-_decimals(written)) + 1e-9
    return any(abs(value - target) <= tolerance for value in allowed)


def ungrounded_numbers(text: str, allowed: set[float]) -> list[str]:
    return [n for n in extract_numbers(text) if not is_grounded(n, allowed)]
