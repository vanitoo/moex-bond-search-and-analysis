from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

STAGES = [
    "1_bonds_search_by_criteria.py",
    "2b_bonds_cashflow.py",
    "3a_bonds_news_search.py",
    "3b_bonds_news.py",
    "4b_bonds_purchase_volume.py",
    "4c_bonds_ofz_spread.py",
    "5_bonds_analysis.py",
    "6_bonds_deep_analysis.py",
    "7_bonds_credit_analysis.py",
    "8_bonds_decision.py",
]

FIRST_STAGE = 1
LAST_STAGE = len(STAGES)
DEFAULT_RATINGS_CACHE_HOURS = 24


def ratings_cache_is_fresh(path: Path, max_age_hours: float) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modified <= timedelta(hours=max_age_hours)


def stage_arguments(
    script_name: str,
    impact_share: float,
    project_root: Path,
    refresh_ratings: bool = False,
    ratings_cache_hours: float = DEFAULT_RATINGS_CACHE_HOURS,
) -> list[str]:
    if script_name == "4b_bonds_purchase_volume.py":
        return ["--impact-share", str(impact_share)]
    if script_name == "7_bonds_credit_analysis.py":
        arguments = ["--data-dir", str(project_root / "data")]
        ratings_path = project_root / "data" / "issuer_ratings.xlsx"
        if not refresh_ratings and ratings_cache_is_fresh(
            ratings_path, ratings_cache_hours
        ):
            arguments.append("--no-fetch-ratings")
        return arguments
    return []


def find_latest_run_dir(project_root: Path) -> Path | None:
    """Находит последнюю папку запуска, в которой есть результат этапа 1."""
    candidates = [
        folder
        for folder in project_root.glob("bond_????_??_??")
        if folder.is_dir() and any(folder.glob("bond_search_*.xlsx"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda folder: folder.stat().st_mtime)


def resolve_run_dir(project_root: Path, requested: str | None, from_stage: int) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()

    if from_stage == 1:
        return project_root / f"bond_{datetime.now():%Y_%m_%d}"

    latest = find_latest_run_dir(project_root)
    if latest is None:
        raise SystemExit(
            "Не найдена папка предыдущего запуска с bond_search_*.xlsx. "
            "Запустите pipeline с этапа 1 или передайте --run-dir."
        )

    print(f"Продолжаем последний незавершённый запуск: {latest}")
    return latest


def run_portfolio_monitor(project_root: Path, run_dir: Path, portfolio_name: str) -> None:
    command = [
        sys.executable,
        str(project_root / "10_portfolio_monitor.py"),
        "daily",
        "--name",
        portfolio_name,
        "--run-dir",
        str(run_dir),
        "--portfolio-dir",
        str(project_root / "data" / "virtual_portfolios"),
        "--history-dir",
        str(project_root / "data" / "portfolio_monitor_history"),
        "--report-dir",
        str(project_root / "reports"),
    ]
    print("\n" + "=" * 72)
    print(f"Ежедневный мониторинг портфеля: {portfolio_name}")
    print("=" * 72)
    subprocess.run(command, check=True, cwd=project_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Полный конвейер анализа облигаций")
    parser.add_argument(
        "--from-stage",
        type=int,
        default=FIRST_STAGE,
        choices=range(FIRST_STAGE, LAST_STAGE + 1),
    )
    parser.add_argument(
        "--to-stage",
        type=int,
        default=LAST_STAGE,
        choices=range(FIRST_STAGE, LAST_STAGE + 1),
    )
    parser.add_argument("--impact-share", type=float, default=0.10)
    parser.add_argument(
        "--refresh-ratings",
        action="store_true",
        help="Принудительно обновить рейтинги «Эксперт РА», игнорируя свежий кэш",
    )
    parser.add_argument(
        "--ratings-cache-hours",
        type=float,
        default=DEFAULT_RATINGS_CACHE_HOURS,
        help="Сколько часов считать issuer_ratings.xlsx свежим",
    )
    parser.add_argument(
        "--portfolio",
        action="append",
        default=[],
        help=(
            "После pipeline запустить ежедневный мониторинг указанного виртуального "
            "портфеля. Параметр можно указать несколько раз."
        ),
    )
    parser.add_argument(
        "--run-dir",
        help=(
            "Папка запуска. При старте с этапа 1 по умолчанию создаётся "
            "bond_YYYY_MM_DD. При продолжении выбирается последняя папка "
            "с результатом этапа 1."
        ),
    )
    args = parser.parse_args()

    if args.from_stage > args.to_stage:
        raise SystemExit("--from-stage не может быть больше --to-stage")
    if args.ratings_cache_hours < 0:
        raise SystemExit("--ratings-cache-hours не может быть отрицательным")

    project_root = Path(__file__).resolve().parent
    run_dir = resolve_run_dir(project_root, args.run_dir, args.from_stage)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Папка текущего запуска: {run_dir}")
    print(f"Общие справочные данные: {project_root / 'data'}")

    for number in range(args.from_stage, args.to_stage + 1):
        script_name = STAGES[number - 1]
        script_path = project_root / script_name
        command = [sys.executable, str(script_path)]
        command += stage_arguments(
            script_name,
            args.impact_share,
            project_root,
            refresh_ratings=args.refresh_ratings,
            ratings_cache_hours=args.ratings_cache_hours,
        )

        print("\n" + "=" * 72)
        print(f"Этап {number}: {script_name}")
        print(f"Рабочая папка: {run_dir}")
        print("=" * 72)
        subprocess.run(command, check=True, cwd=run_dir)

    final_file = run_dir / f"bond_candidates_{datetime.now():%Y-%m-%d}.json"
    print(f"\nКонвейер завершён. Все результаты находятся в: {run_dir}")
    print(f"Финальный вход портфеля: {final_file}")

    for portfolio_name in args.portfolio:
        run_portfolio_monitor(project_root, run_dir, portfolio_name)


if __name__ == "__main__":
    main()
