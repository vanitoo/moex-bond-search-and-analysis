from __future__ import annotations

import argparse
from pathlib import Path

from app.core.data_quality import print_quality_summary
from app.core.project_paths import GUI_CONFIG
from app.core.repair import run_repair


def main() -> None:
    parser = argparse.ArgumentParser(description="Повторная загрузка проблемных данных в существующий run")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--module", choices=["market_search", "cashflow", "news", "liquidity", "ofz_spread", "analysis", "deep_analysis", "credit", "decision"])
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--config", default=str(GUI_CONFIG))
    args = parser.parse_args()

    result = run_repair(
        Path(args.run_dir),
        config=Path(args.config),
        module=args.module,
        attempts=args.attempts,
    )
    if not result["repaired"]:
        print("Повторная загрузка не требуется: retryable-проблем не найдено.")
    print_quality_summary(result["report"])


if __name__ == "__main__":
    main()
