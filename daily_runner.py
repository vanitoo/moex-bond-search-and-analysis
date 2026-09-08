from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    print("\n> " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def latest_analysis_dir(root: Path) -> Path | None:
    candidates = [
        path for path in root.glob("bond_????_??_??")
        if path.is_dir() and (path / "decisions").exists()
    ]
    if not candidates:
        candidates = [path for path in root.glob("bond_????_??_??") if path.is_dir()]
    return max(candidates, key=lambda path: path.name) if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Ежедневный автопилот анализа облигаций")
    parser.add_argument(
        "mode",
        choices=["full", "monitor"],
        help="full — полный pipeline; monitor — лёгкое обновление и мониторинг только портфеля",
    )
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--config", default="configs/gui_active.json")
    parser.add_argument("--run-dir")
    parser.add_argument("--amount", type=float, default=50_000.0)
    parser.add_argument("--refresh-ratings", action="store_true")
    parser.add_argument(
        "--skip-portfolio-refresh",
        action="store_true",
        help="В monitor-режиме не обновлять новости/рейтинги/спреды, а только запустить монитор",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    python = sys.executable
    if args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
    elif args.mode == "full":
        run_dir = root / f"bond_{datetime.now():%Y_%m_%d}"
    else:
        run_dir = latest_analysis_dir(root)
        if run_dir is None:
            raise SystemExit("Не найдена ни одна папка полного анализа bond_YYYY_MM_DD. Сначала выполните full.")

    config = Path(args.config).expanduser().resolve()
    portfolio_dir = root / "data" / "virtual_portfolios"
    history_dir = root / "data" / "portfolio_monitor_history"
    report_dir = root / "reports"

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

        if not args.skip_portfolio_refresh:
            _run([
                python, str(root / "portfolio_daily_refresh.py"),
                "--name", args.portfolio,
                "--run-dir", str(run_dir),
                "--portfolio-dir", str(portfolio_dir),
                "--config", str(config),
            ], root)

        _run([
            python, str(root / "10_portfolio_monitor.py"), "daily",
            "--name", args.portfolio,
            "--run-dir", str(run_dir),
            "--portfolio-dir", str(portfolio_dir),
            "--history-dir", str(history_dir),
            "--report-dir", str(report_dir),
        ], root)

    _run([
        python, str(root / "daily_actions.py"),
        "--name", args.portfolio,
        "--run-dir", str(run_dir),
        "--portfolio-dir", str(portfolio_dir),
        "--history-dir", str(history_dir),
        "--report-dir", str(report_dir),
        "--amount", str(args.amount),
    ], root)

    print("\nАвтопилот завершён")
    print(f"Режим: {args.mode}")
    print(f"Портфель: {args.portfolio}")
    print(f"Базовый полный анализ: {run_dir}")


if __name__ == "__main__":
    main()
