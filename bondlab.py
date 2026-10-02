from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI_DIR = ROOT / "app" / "cli"

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


def _run(script: Path, argv: list[str]) -> None:
    sys.argv = [str(script), *argv]
    runpy.run_path(str(script), run_name="__main__")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(USAGE)
        return

    command = sys.argv[1].strip().lower()
    rest = sys.argv[2:]

    if command == "gui":
        if rest:
            raise SystemExit("Команда gui не принимает дополнительные параметры")
        _run(CLI_DIR / "gui.py", [])
        return

    if command == "pipeline":
        _run(CLI_DIR / "pipeline.py", rest)
        return

    if command in {"full", "monitor"}:
        _run(CLI_DIR / "daily.py", [command, *rest])
        return

    raise SystemExit(f"Неизвестная команда: {command}\n\n{USAGE}")


if __name__ == "__main__":
    main()
