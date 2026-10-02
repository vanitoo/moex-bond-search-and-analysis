from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_CORE = PROJECT_ROOT / "app" / "core"
if str(APP_CORE) not in sys.path:
    sys.path.insert(0, str(APP_CORE))

from master_dataset import build_master_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Собрать единый bonds_master.json из результатов модулей")
    parser.add_argument("--run-dir", type=Path, required=True, help="Папка bond_YYYY_MM_DD")
    parser.add_argument("--output", type=Path, help="Необязательный путь результата")
    args = parser.parse_args()

    target = build_master_dataset(args.run_dir, args.output)
    print(f"Master dataset собран: {target}")


if __name__ == "__main__":
    main()
