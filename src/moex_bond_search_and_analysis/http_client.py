from __future__ import annotations

import os

import requests

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT_LANGUAGE = "ru-RU,ru;q=0.9,en;q=0.8"


def user_agent() -> str:
    value = os.getenv("BOND_HTTP_USER_AGENT", "").strip()
    return value or DEFAULT_BROWSER_USER_AGENT


def accept_language() -> str:
    value = os.getenv("BOND_HTTP_ACCEPT_LANGUAGE", "").strip()
    return value or DEFAULT_ACCEPT_LANGUAGE


def browser_headers(*, referer: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": accept_language(),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
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
