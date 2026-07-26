from __future__ import annotations

import argparse
import subprocess
import sys

STAGES = [
    "1_bonds_search_by_criteria.py",
    "2_bonds_cashflow.py",
    "3_bonds_news.py",
    "4_bonds_purchase_volume.py",
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
    args = parser.parse_args()
    if args.from_stage > args.to_stage:
        raise SystemExit("--from-stage не может быть больше --to-stage")
    for number in range(args.from_stage, args.to_stage + 1):
        script = STAGES[number - 1]
        command = [sys.executable, script]
        if number == 4:
            command += ["--impact-share", str(args.impact_share)]
        print("\n" + "=" * 72)
        print(f"Этап {number}: {script}")
        print("=" * 72)
        subprocess.run(command, check=True)
    print("\nКонвейер завершён. Финальный вход портфеля: bond_candidates_YYYY-MM-DD.json")


if __name__ == "__main__":
    main()
