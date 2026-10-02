from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
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
from stage_arguments import (
    DEFAULT_RATINGS_CACHE_HOURS,
    actual_script,
    market_search_arguments,
    ratings_cache_is_fresh,
    selected_market_script,
    stage_arguments,
)
from stage_registry import MODULE_DESCRIPTIONS, PIPELINE_STAGE_SCRIPTS
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
