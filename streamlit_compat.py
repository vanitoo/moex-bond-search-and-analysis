from __future__ import annotations

from functools import wraps
from typing import Any, Callable

import streamlit as st


def _translate_use_container_width(kwargs: dict[str, Any]) -> dict[str, Any]:
    if "use_container_width" not in kwargs:
        return kwargs
    value = kwargs.pop("use_container_width")
    kwargs.setdefault("width", "stretch" if value else "content")
    return kwargs


def _wrap(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return function(*args, **_translate_use_container_width(kwargs))

    return wrapper


def install_streamlit_width_compat() -> None:
    """Translate deprecated use_container_width=... to width=... globally.

    The existing GUI modules still contain use_container_width in a number of
    call sites. Installing this shim before importing them keeps the current
    code working on newer Streamlit releases without deprecation warnings.
    """
    for name in (
        "button",
        "dataframe",
        "data_editor",
        "download_button",
        "plotly_chart",
        "altair_chart",
        "line_chart",
        "area_chart",
        "bar_chart",
    ):
        function = getattr(st, name, None)
        if function is not None and not getattr(function, "_moex_width_compat", False):
            wrapped = _wrap(function)
            setattr(wrapped, "_moex_width_compat", True)
            setattr(st, name, wrapped)
