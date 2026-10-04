from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any) -> float | None:
    """Parse a finite float from user/data-source values.

    Spaces and decimal commas are accepted. NaN/Inf are treated as missing so
    presentation and portfolio calculations do not accidentally propagate
    non-finite values.
    """
    try:
        if value is None or value == "":
            return None
        result = float(str(value).replace(" ", "").replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def deep_get(item: dict[str, Any], dotted_path: str) -> Any:
    """Read a dotted path from nested dictionaries without raising."""
    value: Any = item
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
