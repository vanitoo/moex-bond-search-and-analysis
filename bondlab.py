from __future__ import annotations

import sys
from collections.abc import Callable


USAGE = """MOEX Bond Lab

Usage:
  python bondlab.py gui
  python bondlab.py pipeline [pipeline options]
  python bondlab.py full --portfolio NAME [daily/full options]
  python bondlab.py monitor --portfolio NAME [daily/monitor options]

Examples:
  .\.venv\Scripts\python.exe .\bondlab.py gui
  .\.venv\Scripts\python.exe .\bondlab.py pipeline --from-stage 1 --to-stage 10 --config .\configs\gui_active.json
  .\.venv\Scripts\python.exe .\bondlab.py monitor --portfolio "Основной" --config .\configs\gui_active.json
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

    raise SystemExit(f"Неизвестная команда: {command}\n\n{USAGE}")


if __name__ == "__main__":
    main()
