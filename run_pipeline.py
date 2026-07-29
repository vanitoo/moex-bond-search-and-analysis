from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pipeline_architecture import BY_SCRIPT, collect_stage, is_enabled, load_config, module_config, record_disabled

STAGES = [
    "1_bonds_search_by_criteria.py",
    "2_bonds_cashflow.py",
    "3a_bonds_news_search.py",
    "3b_bonds_news.py",
    "4b_bonds_purchase_volume.py",
    "4c_bonds_ofz_spread.py",
    "5_bonds_analysis.py",
    "6_bonds_deep_analysis.py",
    "7_bonds_credit_analysis.py",
    "8_bonds_decision.py",
]

MODULE_DESCRIPTIONS = {
    "1_bonds_search_by_criteria.py": "V1: старый последовательный сканер рынка MOEX. Оставлен как контрольный и резервный вариант.",
    "1_bonds_market_scanner_v2.py": "V2: пакетная загрузка рынка, локальная фильтрация, дисковый кэш и ограниченный параллелизм.",
    "2_bonds_cashflow.py": "Получает и анализирует будущие купоны, амортизации, оферты и полноту денежных потоков.",
    "3a_bonds_news_search.py": "Определяет эмитентов найденных выпусков и скачивает свежие новости в локальную папку.",
    "3b_bonds_news.py": "Анализирует новости, выявляет негативные и позитивные события и формирует новостные стоп-факторы.",
    "4b_bonds_purchase_volume.py": "Проверяет цену, стакан, оборот и ликвидность, затем рассчитывает допустимый объём покупки.",
    "4c_bonds_ofz_spread.py": "Сравнивает доходность облигации с сопоставимой ОФЗ и рассчитывает премию за риск.",
    "5_bonds_analysis.py": "Объединяет результаты доступных модулей и выполняет первичную рыночную оценку облигаций.",
    "6_bonds_deep_analysis.py": "Выполняет углублённый скоринг с учётом структуры выпуска, новостей, ликвидности и полноты данных.",
    "7_bonds_credit_analysis.py": "Проверяет рейтинги и финансовые показатели эмитента и оценивает кредитный риск.",
    "8_bonds_decision.py": "Формирует итоговое решение по каждой облигации на основании включённых модулей и доступных данных.",
}

FIRST_STAGE = 1
LAST_STAGE = len(STAGES)
DEFAULT_RATINGS_CACHE_HOURS = 24


def selected_market_script(config: dict) -> str:
    version = str(module_config(config, "market_search").get("version", "v1")).strip().lower()
    if version not in {"v1", "v2"}:
        raise SystemExit("market_search.version должен быть v1 или v2")
    return "1_bonds_market_scanner_v2.py" if version == "v2" else "1_bonds_search_by_criteria.py"


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
    if script_name == "4b_bonds_purchase_volume.py":
        return ["--impact-share", str(settings.get("impact_share", impact_share))]
    if script_name == "7_bonds_credit_analysis.py":
        arguments = ["--data-dir", str(project_root / "data")]
        ratings_path = project_root / "data" / "issuer_ratings.xlsx"
        if not refresh_ratings and ratings_cache_is_fresh(ratings_path, ratings_cache_hours):
            arguments.append("--no-fetch-ratings")
        return arguments
    if script_name == "8_bonds_decision.py":
        actual = config_path or (project_root / "configs" / "balanced.json")
        return ["--config", str(actual)]
    return []


def find_latest_run_dir(project_root: Path) -> Path | None:
    candidates = [folder for folder in project_root.glob("bond_????_??_??")
                  if folder.is_dir() and any(folder.glob("bond_search_*.xlsx"))]
    return max(candidates, key=lambda folder: folder.stat().st_mtime) if candidates else None


def resolve_run_dir(project_root: Path, requested: str | None, from_stage: int) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    if from_stage == 1:
        return project_root / f"bond_{datetime.now():%Y_%m_%d}"
    latest_dir = find_latest_run_dir(project_root)
    if latest_dir is None:
        raise SystemExit("Не найдена папка предыдущего запуска с bond_search_*.xlsx. Запустите этап 1 или передайте --run-dir.")
    print(f"Продолжаем последний незавершённый запуск: {latest_dir}")
    return latest_dir


def run_portfolio_monitor(project_root: Path, run_dir: Path, portfolio_name: str) -> None:
    command = [sys.executable, str(project_root / "10_portfolio_monitor.py"), "daily", "--name", portfolio_name,
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

    project_root = Path(__file__).resolve().parent
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

    for number in numbers:
        configured_name = STAGES[number - 1]
        script_name = actual_script(configured_name, config)
        spec = BY_SCRIPT[script_name]
        if not is_enabled(config, spec.key):
            print(f"\nЭтап {number}: {script_name} — ОТКЛЮЧЁН конфигурацией")
            record_disabled(run_dir, spec, config)
            continue
        command = [sys.executable, str(project_root / script_name)]
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
        print(f"Модуль: {spec.key}; режим: {module_config(config, spec.key).get('mode', 'information')}")
        print(f"Рабочая папка: {run_dir}")
        print("=" * 72)
        subprocess.run(command, check=True, cwd=run_dir)
        collect_stage(run_dir, spec, config)

    print(f"\nКонвейер завершён. Все результаты находятся в: {run_dir}")
    for portfolio_name in args.portfolio:
        run_portfolio_monitor(project_root, run_dir, portfolio_name)


if __name__ == "__main__":
    main()
