from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import requests

from app.core.configuration import (
    DEFAULT_HTTP,
    http_config,
    load_runtime_config,
)

DEFAULT_BROWSER_USER_AGENT = str(DEFAULT_HTTP["user_agent"])
DEFAULT_ACCEPT_LANGUAGE = str(DEFAULT_HTTP["accept_language"])
_PATCHED = False
_ORIGINAL_SESSION_REQUEST = requests.sessions.Session.request


@lru_cache(maxsize=1)
def _http_config() -> dict[str, str]:
    """Expose effective HTTP settings while keeping legacy helper semantics."""

    try:
        return dict(http_config(load_runtime_config()))
    except (OSError, ValueError):
        return dict(http_config({}))


def user_agent() -> str:
    value = os.getenv("BOND_HTTP_USER_AGENT", "").strip()
    if value:
        return value
    configured = _http_config().get("user_agent", "").strip()
    return configured or DEFAULT_BROWSER_USER_AGENT


def accept_language() -> str:
    value = os.getenv("BOND_HTTP_ACCEPT_LANGUAGE", "").strip()
    if value:
        return value
    configured = _http_config().get("accept_language", "").strip()
    return configured or DEFAULT_ACCEPT_LANGUAGE


def browser_headers(*, referer: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": accept_language(),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    if extra:
        headers.update(extra)
    return headers


def browser_session(*, trust_env: bool = False) -> requests.Session:
    session = requests.Session()
    session.trust_env = trust_env
    session.headers.update(browser_headers())
    return session


def install_browser_defaults() -> None:
    """Добавляет браузерные заголовки ко всем requests-запросам проекта.

    Явно переданные заголовки имеют приоритет. Патч устанавливается один раз на процесс.
    Это покрывает старые модули, которые пока вызывают requests.get/post напрямую.
    """
    global _PATCHED
    if _PATCHED:
        return

    def request_with_browser_defaults(
        session: requests.Session,
        method: str,
        url: str,
        *args: Any,
        **kwargs: Any,
    ) -> requests.Response:
        supplied = kwargs.get("headers") or {}
        merged = browser_headers()
        merged.update({str(key): str(value) for key, value in supplied.items()})
        kwargs["headers"] = merged
        return _ORIGINAL_SESSION_REQUEST(session, method, url, *args, **kwargs)

    requests.sessions.Session.request = request_with_browser_defaults
    _PATCHED = True
