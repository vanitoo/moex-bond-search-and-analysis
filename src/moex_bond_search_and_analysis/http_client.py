from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
DEFAULT_ACCEPT_LANGUAGE = "ru-RU,ru;q=0.9,en;q=0.8"
_PATCHED = False
_ORIGINAL_SESSION_REQUEST = requests.sessions.Session.request


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _http_config() -> dict[str, str]:
    explicit = os.getenv("BOND_CONFIG", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    root = _project_root()
    candidates.extend([
        root / "configs" / "gui_active.json",
        root / "configs" / "balanced.json",
    ])
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        section = payload.get("http")
        if isinstance(section, dict):
            return {str(key): str(value) for key, value in section.items() if value is not None}
    return {}


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
