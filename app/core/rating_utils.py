from __future__ import annotations

import math
import re
from typing import Any


RATING_ORDER = (
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
)

_NULL_RATING_TEXT = {"", "nan", "none", "null", "—", "-"}


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def normalize_rating(value: Any) -> str:
    """Normalize Russian-scale credit ratings to the project's canonical grade."""
    if value is None or _is_nan(value):
        return ""
    raw = str(value).strip()
    if raw.lower() in _NULL_RATING_TEXT:
        return ""
    text = raw.upper().replace("(RU)", "").replace("RU", "")
    text = re.sub(r"[^A-Z+\-]", "", text)
    for grade in sorted(RATING_ORDER, key=len, reverse=True):
        if grade in text:
            return grade
    return ""


def rating_index(value: Any) -> int | None:
    grade = normalize_rating(value)
    if not grade:
        return None
    return RATING_ORDER.index(grade)


def rating_direction(current: Any, previous: Any) -> int:
    """Positive means upgrade, negative means downgrade."""
    current_index = rating_index(current)
    previous_index = rating_index(previous)
    if current_index is None or previous_index is None:
        return 0
    return current_index - previous_index


def rating_drop(previous: Any, current: Any) -> int:
    """Return downgrade depth in rating notches, or zero when not downgraded."""
    return max(0, -rating_direction(current, previous))
