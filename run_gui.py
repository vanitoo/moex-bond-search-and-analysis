from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    app = root / "gui_app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app)]
    raise SystemExit(subprocess.call(command, cwd=root))


if __name__ == "__main__":
    main()
