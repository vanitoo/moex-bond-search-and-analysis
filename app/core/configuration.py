from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, TypedDict

from app.core.project_paths import DEFAULT_CONFIG


class ModuleSettings(TypedDict, total=False):
    enabled: bool
    mode: str


class MarketSearchSettings(ModuleSettings, total=False):
    version: str
    yield_more: float
    yield_less: float
    price_more: float
    price_less: float
    duration_more: float
    duration_less: float
    volume_more: float
    bond_volume_more: float
    require_known_coupons: bool
    workers: int
    cache_hours: float
    selection_profile: str


class CreditSettings(ModuleSettings, total=False):
    minimum_rating: str
    fetch_financials: bool
    financial_cache_days: int
    financial_workers: int
    financial_delay_seconds: float
    financial_retries: int
    fetch_bank_metrics: bool
    bank_cache_days: int
    bank_delay_seconds: float


class HttpSettings(TypedDict, total=False):
    user_agent: str
    accept_language: str


class AppConfig(TypedDict, total=False):
    strategy: str
    http: HttpSettings
    modules: dict[str, dict[str, Any]]


DEFAULT_HTTP: HttpSettings = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "accept_language": "ru-RU,ru;q=0.9,en;q=0.8",
}


DEFAULT_MODULES: dict[str, dict[str, Any]] = {
    "market_search": {
        "enabled": True,
        "mode": "hard_filter",
        "version": "v1",
        "yield_more": 15.0,
        "yield_less": 40.0,
        "price_more": 70.0,
        "price_less": 120.0,
        "duration_more": 3.0,
        "duration_less": 18.0,
        "volume_more": 2000.0,
        "bond_volume_more": 60000.0,
        "require_known_coupons": True,
        "workers": 5,
        "cache_hours": 12.0,
    },
    "cashflow": {
        "enabled": True,
        "mode": "hard_filter",
        "require_complete": True,
    },
    "news_search": {
        "enabled": True,
        "mode": "information",
        "providers": ["google", "moex", "acra", "expert_ra"],
        "proxy_enabled": False,
        "proxy_env": "NEWS_PROXY",
        "minimum_successful_providers": 1,
    },
    "news": {
        "enabled": True,
        "mode": "hard_stop",
    },
    "liquidity": {
        "enabled": True,
        "mode": "score",
        "impact_share": 0.10,
    },
    "ofz_spread": {
        "enabled": True,
        "mode": "score",
        "warning_bp": 600,
        "critical_bp": 1000,
    },
    "analysis": {
        "enabled": True,
        "mode": "score",
    },
    "deep_analysis": {
        "enabled": True,
        "mode": "score",
    },
    "credit": {
        "enabled": True,
        "mode": "hard_filter",
        "minimum_rating": "BBB-",
        "fetch_financials": True,
        "financial_cache_days": 35,
        "financial_workers": 1,
        "financial_delay_seconds": 1.2,
        "financial_retries": 4,
        "fetch_bank_metrics": True,
        "bank_cache_days": 7,
        "bank_delay_seconds": 0.4,
    },
    "decision": {
        "enabled": True,
        "mode": "hard_filter",
    },
}


def default_config(strategy: str = "balanced") -> AppConfig:
    """Return a fresh canonical configuration.

    Configuration defaults live here rather than in GUI widgets, CLI argument
    builders and automation code. Callers may safely mutate the returned value.
    """

    return {
        "strategy": str(strategy or "balanced"),
        "http": deepcopy(DEFAULT_HTTP),
        "modules": deepcopy(DEFAULT_MODULES),
    }


def normalize_config(
    payload: dict[str, Any] | None,
    *,
    strategy_hint: str = "balanced",
) -> AppConfig:
    """Merge a partial persisted config onto the canonical schema defaults."""

    source = payload or {}
    if not isinstance(source, dict):
        raise ValueError("Конфигурация должна быть JSON-объектом")

    strategy = str(source.get("strategy") or strategy_hint or "balanced")
    result = default_config(strategy)

    http = source.get("http")
    if http is not None:
        if not isinstance(http, dict):
            raise ValueError("config.http должен быть объектом")
        result["http"].update(deepcopy(http))

    modules = source.get("modules")
    if modules is not None:
        if not isinstance(modules, dict):
            raise ValueError("config.modules должен быть объектом")
        for key, value in modules.items():
            if not isinstance(value, dict):
                raise ValueError(f"config.modules.{key} должен быть объектом")
            settings = result["modules"].setdefault(str(key), {})
            settings.update(deepcopy(value))

    # Preserve future top-level sections without making every caller aware of
    # them. Canonical sections above are normalized explicitly.
    for key, value in source.items():
        if key not in {"strategy", "http", "modules"}:
            result[key] = deepcopy(value)  # type: ignore[literal-required]

    return result


def load_config(path: Path | None = None) -> AppConfig:
    source = path or DEFAULT_CONFIG
    payload = json.loads(source.read_text(encoding="utf-8"))
    return normalize_config(payload, strategy_hint=source.stem)


def save_config(path: Path, config: dict[str, Any]) -> Path:
    normalized = normalize_config(config, strategy_hint=path.stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def module_config(config: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one module settings block with canonical defaults applied."""

    defaults = deepcopy(DEFAULT_MODULES.get(key, {}))
    modules = config.get("modules", {})
    if not isinstance(modules, dict):
        return defaults
    value = modules.get(key, {})
    if isinstance(value, dict):
        defaults.update(value)
    return defaults


def is_enabled(config: dict[str, Any], key: str) -> bool:
    return bool(module_config(config, key).get("enabled", True))
