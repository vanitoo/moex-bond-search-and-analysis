from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pipeline_architecture import module_config
from stage_registry import BY_SCRIPT, resolve_market_script


DEFAULT_RATINGS_CACHE_HOURS = 24


def selected_market_script(config: dict) -> str:
    version = module_config(config, "market_search").get("version", "v1")
    try:
        return resolve_market_script(str(version))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def actual_script(script_name: str, config: dict) -> str:
    if script_name == "1_bonds_search_by_criteria.py":
        return selected_market_script(config)
    return script_name


def ratings_cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modified <= timedelta(hours=max_age_hours)


def market_search_arguments(settings: dict) -> list[str]:
    arguments = [
        "--yield-more", str(settings.get("yield_more", 15)),
        "--yield-less", str(settings.get("yield_less", 40)),
        "--price-more", str(settings.get("price_more", 70)),
        "--price-less", str(settings.get("price_less", 120)),
        "--duration-more", str(settings.get("duration_more", 3)),
        "--duration-less", str(settings.get("duration_less", 18)),
        "--volume-more", str(settings.get("volume_more", 2000)),
        "--bond-volume-more", str(settings.get("bond_volume_more", 60000)),
    ]
    arguments.append(
        "--require-known-coupons"
        if settings.get("require_known_coupons", True)
        else "--no-require-known-coupons"
    )
    return arguments


def stage_arguments(
    script_name: str,
    impact_share: float,
    project_root: Path,
    config: dict,
    config_path: Path | None = None,
    refresh_ratings: bool = False,
    ratings_cache_hours: float = DEFAULT_RATINGS_CACHE_HOURS,
) -> list[str]:
    spec = BY_SCRIPT[script_name]
    settings = module_config(config, spec.key)

    if script_name in {"1_bonds_search_by_criteria.py", "1_bonds_market_scanner_v2.py"}:
        arguments = market_search_arguments(settings)
        if script_name == "1_bonds_market_scanner_v2.py":
            arguments += [
                "--workers", str(settings.get("workers", 5)),
                "--cache-hours", str(settings.get("cache_hours", 12)),
            ]
        return arguments

    if script_name == "3a_bonds_news_search.py":
        providers = settings.get("providers", ["google", "moex", "acra", "expert_ra"])
        if isinstance(providers, str):
            provider_value = providers
        else:
            provider_value = ",".join(
                str(item).strip() for item in providers if str(item).strip()
            )
        arguments = [
            "--providers", provider_value or "google,moex,acra,expert_ra",
            "--proxy-env", str(settings.get("proxy_env", "NEWS_PROXY")),
        ]
        if settings.get("proxy_enabled", False):
            arguments.append("--use-proxy")
        if "max_failure_share" in settings:
            arguments += ["--max-failure-share", str(settings["max_failure_share"])]
        return arguments

    if script_name == "4b_bonds_purchase_volume.py":
        return ["--impact-share", str(settings.get("impact_share", impact_share))]

    if script_name == "7_bonds_credit_analysis.py":
        arguments = ["--data-dir", str(project_root / "data")]
        ratings_path = project_root / "data" / "issuer_ratings.xlsx"
        if not refresh_ratings and ratings_cache_is_fresh(
            ratings_path,
            ratings_cache_hours,
        ):
            arguments.append("--no-fetch-ratings")
        if settings.get("fetch_financials", True) is False:
            arguments.append("--no-fetch-financials")
        if settings.get("fetch_bank_metrics", True) is False:
            arguments.append("--no-fetch-bank-metrics")
        arguments += [
            "--financial-cache-days", str(settings.get("financial_cache_days", 35)),
            "--financial-workers", str(settings.get("financial_workers", 1)),
            "--financial-delay-seconds", str(settings.get("financial_delay_seconds", 1.2)),
            "--financial-retries", str(settings.get("financial_retries", 4)),
            "--bank-cache-days", str(settings.get("bank_cache_days", 7)),
            "--bank-delay-seconds", str(settings.get("bank_delay_seconds", 0.4)),
        ]
        return arguments

    if script_name == "8_bonds_decision.py":
        actual = config_path or (project_root / "configs" / "balanced.json")
        return ["--config", str(actual)]

    return []
