from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

STAGES = [
    "1_bonds_search_by_criteria.py",
    "2b_bonds_cashflow.py",
    "3b_bonds_news.py",
    "4b_bonds_purchase_volume.py",
    "5_bonds_analysis.py",
    "6_bonds_deep_analysis.py",
    "7_bonds_credit_analysis.py",
    "8_bonds_decision.py",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Полный конвейер анализа облигаций")
    parser.add_argument("--from-stage", type=int, default=1, choices=range(1, 9))
    parser.add_argument("--to-stage", type=int, default=8, choices=range(1, 9))
    parser.add_argument("--impact-share", type=float, default=0.10)
    parser.add_argument(
        "--run-dir",
        help="Папка запуска. По умолчанию bond_YYYY_MM_DD в корне проекта",
    )
    args = parser.parse_args()

    if args.from_stage > args.to_stage:
        raise SystemExit("--from-stage не может быть больше --to-stage")

    project_root = Path(__file__).resolve().parent
    run_dir = (
        Path(args.run_dir).expanduser().resolve()
        if args.run_dir
        else project_root / f"bond_{datetime.now():%Y_%m_%d}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Папка текущего запуска: {run_dir}")
    print(f"Общие справочные данные: {project_root / 'data'}")

    for number in range(args.from_stage, args.to_stage + 1):
        script_name = STAGES[number - 1]
        script_path = project_root / script_name
        command = [sys.executable, str(script_path)]

        if number == 4:
            command += ["--impact-share", str(args.impact_share)]
        elif number == 7:
            # Рейтинги и финансовая отчётность общие для всех запусков,
            # поэтому data остаётся в корне проекта, а не копируется по датам.
            command += ["--data-dir", str(project_root / "data")]

        print("\n" + "=" * 72)
        print(f"Этап {number}: {script_name}")
        print(f"Рабочая папка: {run_dir}")
        print("=" * 72)
        subprocess.run(command, check=True, cwd=run_dir)

    final_file = run_dir / f"bond_candidates_{datetime.now():%Y-%m-%d}.json"
    print(f"\nКонвейер завершён. Все результаты находятся в: {run_dir}")
    print(f"Финальный вход портфеля: {final_file}")


if __name__ == "__main__":
    main()
