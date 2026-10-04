from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.core.configuration import module_config
from app.core.stage_registry import BY_SCRIPT, resolve_market_script


DEFAULT_RATINGS_CACHE_HOURS = 24


def selected_market_script(config: dict) -> str:
    version = module_config(config, "market_search")["version"]
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
        "--yield-more", str(settings["yield_more"]),
        "--yield-less", str(settings["yield_less"]),
        "--price-more", str(settings["price_more"]),
        "--price-less", str(settings["price_less"]),
        "--duration-more", str(settings["duration_more"]),
        "--duration-less", str(settings["duration_less"]),
        "--volume-more", str(settings["volume_more"]),
        "--bond-volume-more", str(settings["bond_volume_more"]),
    ]
    arguments.append(
        "--require-known-coupons"
        if settings["require_known_coupons"]
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
                "--workers", str(settings["workers"]),
                "--cache-hours", str(settings["cache_hours"]),
            ]
        return arguments

    if script_name == "3a_bonds_news_search.py":
        providers = settings["providers"]
        if isinstance(providers, str):
            provider_value = providers
        else:
            provider_value = ",".join(
                str(item).strip() for item in providers if str(item).strip()
            )
        arguments = [
            "--providers", provider_value or "google,moex,acra,expert_ra",
            "--proxy-env", str(settings["proxy_env"]),
        ]
        if settings["proxy_enabled"]:
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
        if settings["fetch_financials"] is False:
            arguments.append("--no-fetch-financials")
        if settings["fetch_bank_metrics"] is False:
            arguments.append("--no-fetch-bank-metrics")
        arguments += [
            "--financial-cache-days", str(settings["financial_cache_days"]),
            "--financial-workers", str(settings["financial_workers"]),
            "--financial-delay-seconds", str(settings["financial_delay_seconds"]),
            "--financial-retries", str(settings["financial_retries"]),
            "--bank-cache-days", str(settings["bank_cache_days"]),
            "--bank-delay-seconds", str(settings["bank_delay_seconds"]),
        ]
        return arguments

    if script_name == "8_bonds_decision.py":
        actual = config_path or (project_root / "configs" / "balanced.json")
        return ["--config", str(actual)]

    return []
