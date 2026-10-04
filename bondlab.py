from __future__ import annotations

import sys
from collections.abc import Callable


USAGE = r"""MOEX Bond Lab

Usage:
  python bondlab.py gui
  python bondlab.py pipeline [pipeline options]
  python bondlab.py full --portfolio NAME [daily/full options]
  python bondlab.py monitor --portfolio NAME [daily/monitor options]
  python bondlab.py portfolio create --name NAME
  python bondlab.py portfolio show --name NAME
  python bondlab.py portfolio ledger --name NAME
  python bondlab.py invest --portfolio NAME --amount RUB [--refresh]

Examples:
  .\.venv\Scripts\python.exe .\bondlab.py gui
  .\.venv\Scripts\python.exe .\bondlab.py pipeline --from-stage 1 --to-stage 10 --config .\configs\gui_active.json
  .\.venv\Scripts\python.exe .\bondlab.py monitor --portfolio "Основной" --config .\configs\gui_active.json
  .\.venv\Scripts\python.exe .\bondlab.py portfolio create --name "Основной"
  .\.venv\Scripts\python.exe .\bondlab.py invest --portfolio "Основной" --amount 50000 --refresh
"""


def _invoke(main_func: Callable[[], None], argv: list[str]) -> None:
    """Run an internal CLI while preserving the outer process argv."""

    previous = sys.argv[:]
    try:
        sys.argv = [previous[0], *argv]
        main_func()
    finally:
        sys.argv = previous


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(USAGE)
        return

    command = sys.argv[1].strip().lower()
    rest = sys.argv[2:]

    if command == "gui":
        if rest:
            raise SystemExit("Команда gui не принимает дополнительные параметры")
        from app.cli.gui import main as gui_main

        _invoke(gui_main, [])
        return

    if command == "pipeline":
        from app.cli.pipeline import main as pipeline_main

        _invoke(pipeline_main, rest)
        return

    if command in {"full", "monitor"}:
        from app.cli.daily import main as daily_main

        _invoke(daily_main, [command, *rest])
        return

    if command == "portfolio":
        from app.cli.portfolio import main as portfolio_main

        _invoke(portfolio_main, rest)
        return

    if command == "invest":
        from app.cli.portfolio import main as portfolio_main

        translated = list(rest)
        if "--portfolio" in translated:
            index = translated.index("--portfolio")
            translated[index] = "--name"
        _invoke(portfolio_main, ["invest", *translated])
        return

    raise SystemExit(f"Неизвестная команда: {command}\n\n{USAGE}")


if __name__ == "__main__":
    main()
