from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "app"
APP_CORE = APP_ROOT / "core"
APP_PORTFOLIO = APP_ROOT / "portfolio"
SRC_ROOT = PROJECT_ROOT / "src"
for _path in (str(APP_CORE), str(APP_PORTFOLIO), str(APP_ROOT), str(SRC_ROOT), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from master_dataset import build_master_dataset
from runtime_env import build_subprocess_env
from run_paths import latest_pipeline_run, new_run_dir
from stage_registry import (
    MODULE_DESCRIPTIONS,
    PIPELINE_STAGE_SCRIPTS,
    resolve_market_script,
)
from pipeline_architecture import (
    BY_SCRIPT,
    append_event,
    collect_stage,
    is_enabled,
    load_config,
    module_config,
    record_disabled,
    write_summaries,
)

STAGES = list(PIPELINE_STAGE_SCRIPTS)
FIRST_STAGE = 1
LAST_STAGE = len(STAGES)
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
    arguments.append("--require-known-coupons" if settings.get("require_known_coupons", True) else "--no-require-known-coupons")
    return arguments


def stage_arguments(script_name: str, impact_share: float, project_root: Path, config: dict,
                    config_path: Path | None = None, refresh_ratings: bool = False,
                    ratings_cache_hours: float = DEFAULT_RATINGS_CACHE_HOURS) -> list[str]:
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
            provider_value = ",".join(str(item).strip() for item in providers if str(item).strip())
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
        if not refresh_ratings and ratings_cache_is_fresh(ratings_path, ratings_cache_hours):
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


def find_latest_run_dir(project_root: Path) -> Path | None:
    return latest_pipeline_run(project_root)


def resolve_run_dir(project_root: Path, requested: str | None, from_stage: int) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    if from_stage == 1:
        return new_run_dir(project_root, datetime.now().strftime("%Y_%m_%d"))
    latest_dir = find_latest_run_dir(project_root)
    if latest_dir is None:
        raise SystemExit("Не найдена папка предыдущего запуска с bond_search_*.xlsx. Запустите этап 1 или передайте --run-dir.")
    print(f"Продолжаем последний незавершённый запуск: {latest_dir}")
    return latest_dir


def run_portfolio_monitor(project_root: Path, run_dir: Path, portfolio_name: str) -> None:
    command = [sys.executable, str(project_root / "app" / "portfolio" / "portfolio_monitor.py"), "daily", "--name", portfolio_name,
               "--run-dir", str(run_dir), "--portfolio-dir", str(project_root / "data" / "virtual_portfolios"),
               "--history-dir", str(project_root / "data" / "portfolio_monitor_history"),
               "--report-dir", str(project_root / "reports")]
    subprocess.run(command, check=True, cwd=project_root)


def selected_stage_numbers(args: argparse.Namespace) -> list[int]:
    if not args.only_module:
        return list(range(args.from_stage, args.to_stage + 1))
    requested = set(args.only_module)
    known = {BY_SCRIPT[name].key for name in STAGES}
    unknown = sorted(requested - known)
    if unknown:
        raise SystemExit(f"Неизвестные модули: {', '.join(unknown)}. Доступны: {', '.join(sorted(known))}")
    return [index for index, script in enumerate(STAGES, 1) if BY_SCRIPT[script].key in requested]


def record_stage_error(run_dir: Path, spec, config: dict, exc: subprocess.CalledProcessError) -> None:
    mode = module_config(config, spec.key).get("mode", "information")
    append_event(run_dir, {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "module": spec.key,
        "status": "ERROR",
        "passed": None,
        "hard_stop": False,
        "score_delta": 0,
        "reason_code": "STAGE_PROCESS_ERROR",
        "reason": f"Модуль завершился с кодом {exc.returncode}",
        "mode": mode,
    })
    write_summaries(run_dir, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Полный конвейер анализа облигаций")
    parser.add_argument("--from-stage", type=int, default=FIRST_STAGE, choices=range(FIRST_STAGE, LAST_STAGE + 1))
    parser.add_argument("--to-stage", type=int, default=LAST_STAGE, choices=range(FIRST_STAGE, LAST_STAGE + 1))
    parser.add_argument("--only-module", action="append", default=[])
    parser.add_argument("--impact-share", type=float, default=0.10)
    parser.add_argument("--config")
    parser.add_argument("--refresh-ratings", action="store_true")
    parser.add_argument("--ratings-cache-hours", type=float, default=DEFAULT_RATINGS_CACHE_HOURS)
    parser.add_argument("--portfolio", action="append", default=[])
    parser.add_argument("--run-dir")
    parser.add_argument("--reset-trace", action="store_true")
    args = parser.parse_args()

    if args.from_stage > args.to_stage:
        raise SystemExit("--from-stage не может быть больше --to-stage")
    if args.ratings_cache_hours < 0:
        raise SystemExit("--ratings-cache-hours не может быть отрицательным")

    project_root = PROJECT_ROOT
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    config = load_config(config_path)
    numbers = selected_stage_numbers(args)
    if not numbers:
        raise SystemExit("Не выбран ни один модуль")
    run_dir = resolve_run_dir(project_root, args.run_dir, min(numbers))
    run_dir.mkdir(parents=True, exist_ok=True)

    trace_dir = run_dir / "decisions"
    if args.reset_trace and trace_dir.exists():
        shutil.rmtree(trace_dir)

    print(f"Папка текущего запуска: {run_dir}")
    print(f"Стратегия: {config.get('strategy')}")
    print(f"Сканер рынка: {module_config(config, 'market_search').get('version', 'v1').upper()}")
    if args.only_module:
        print("Точечный запуск модулей: " + ", ".join(args.only_module))

    soft_errors: list[str] = []
    for number in numbers:
        configured_name = STAGES[number - 1]
        script_name = actual_script(configured_name, config)
        spec = BY_SCRIPT[script_name]
        if not is_enabled(config, spec.key):
            print(f"\nЭтап {number}: {script_name} — ОТКЛЮЧЁН конфигурацией")
            record_disabled(run_dir, spec, config)
            continue
        command = [sys.executable, str(project_root / "app" / "stages" / script_name)]
        command += stage_arguments(script_name, args.impact_share, project_root, config, config_path,
                                   refresh_ratings=args.refresh_ratings,
                                   ratings_cache_hours=args.ratings_cache_hours)
        print("\n" + "=" * 72)
        print(f"Этап {number}: {script_name}")
        print(f"🔴 ЧТО ДЕЛАЕТ МОДУЛЬ: {MODULE_DESCRIPTIONS[script_name]}")
        if spec.key == "market_search":
            settings = module_config(config, "market_search")
            print(
                "Критерии: доходность "
                f"{settings.get('yield_more', 15)}–{settings.get('yield_less', 40)}%; "
                f"цена {settings.get('price_more', 70)}–{settings.get('price_less', 120)}%; "
                f"дюрация {settings.get('duration_more', 3)}–{settings.get('duration_less', 18)} мес."
            )
        mode = module_config(config, spec.key).get("mode", "information")
        print(f"Модуль: {spec.key}; режим: {mode}")
        print(f"Рабочая папка: {run_dir}")
        print("=" * 72)
        try:
            child_env = build_subprocess_env(project_root)
            subprocess.run(command, check=True, cwd=run_dir, env=child_env)
        except subprocess.CalledProcessError as exc:
            record_stage_error(run_dir, spec, config, exc)
            if mode == "information":
                soft_errors.append(spec.key)
                print(
                    f"\n⚠ Модуль {spec.key} недоступен/завершился с ошибкой, но имеет режим information. "
                    "Конвейер продолжает работу; зависимые модули должны трактовать эти данные как отсутствующие."
                )
                continue
            raise
        collect_stage(run_dir, spec, config)

    try:
        master_path = build_master_dataset(run_dir)
        print(f"\nЕдиный набор данных GUI обновлён: {master_path}")
    except Exception as exc:
        print(f"\n⚠ Не удалось собрать bonds_master.json: {exc}")

    if soft_errors:
        print("\n⚠ Конвейер завершён с неполными внешними данными: " + ", ".join(soft_errors))
    print(f"\nКонвейер завершён. Все результаты находятся в: {run_dir}")
    for portfolio_name in args.portfolio:
        run_portfolio_monitor(project_root, run_dir, portfolio_name)


if __name__ == "__main__":
    main()
