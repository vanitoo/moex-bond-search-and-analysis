from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    print("\n> " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ежедневный автопилот анализа облигаций")
    parser.add_argument("mode", choices=["full", "monitor"], help="full — полный pipeline; monitor — внутридневной мониторинг портфеля")
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--config", default="configs/gui_active.json")
    parser.add_argument("--run-dir")
    parser.add_argument("--amount", type=float, default=50_000.0)
    parser.add_argument("--refresh-ratings", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    python = sys.executable
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else root / f"bond_{datetime.now():%Y_%m_%d}"
    config = Path(args.config).expanduser().resolve()

    if args.mode == "full":
        command = [
            python, str(root / "run_pipeline.py"),
            "--from-stage", "1",
            "--to-stage", "10",
            "--run-dir", str(run_dir),
            "--config", str(config),
            "--portfolio", args.portfolio,
        ]
        if args.refresh_ratings:
            command.append("--refresh-ratings")
        _run(command, root)
    else:
        if not run_dir.exists():
            raise SystemExit(f"Папка анализа не найдена: {run_dir}. Сначала выполните full или укажите --run-dir.")
        _run([
            python, str(root / "10_portfolio_monitor.py"), "daily",
            "--name", args.portfolio,
            "--run-dir", str(run_dir),
            "--portfolio-dir", str(root / "data" / "virtual_portfolios"),
            "--history-dir", str(root / "data" / "portfolio_monitor_history"),
            "--report-dir", str(root / "reports"),
        ], root)

    _run([
        python, str(root / "daily_actions.py"),
        "--name", args.portfolio,
        "--run-dir", str(run_dir),
        "--portfolio-dir", str(root / "data" / "virtual_portfolios"),
        "--history-dir", str(root / "data" / "portfolio_monitor_history"),
        "--report-dir", str(root / "reports"),
        "--amount", str(args.amount),
    ], root)

    print("\nАвтопилот завершён")
    print(f"Режим: {args.mode}")
    print(f"Портфель: {args.portfolio}")
    print(f"Папка анализа: {run_dir}")


if __name__ == "__main__":
    main()
