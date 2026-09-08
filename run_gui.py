from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    app = root / "gui_app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app)]
    process = subprocess.Popen(command, cwd=root)
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        print("\nGUI остановлен пользователем.")
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return
    if return_code:
        raise SystemExit(return_code)


if __name__ == "__main__":
    main()
