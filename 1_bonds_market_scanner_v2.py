from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from moex_bond_search_and_analysis.market_scanner_v2 import ScannerConfig, run_scan
from moex_bond_search_and_analysis.market_scanner_v2.models import DEFAULT_CACHE_HOURS, DEFAULT_WORKERS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Пакетный сканер рынка облигаций MOEX V2")
    parser.add_argument("--yield-more", type=float, default=15)
    parser.add_argument("--yield-less", type=float, default=40)
    parser.add_argument("--price-more", type=float, default=70)
    parser.add_argument("--price-less", type=float, default=120)
    parser.add_argument("--duration-more", type=float, default=3)
    parser.add_argument("--duration-less", type=float, default=18)
    parser.add_argument("--volume-more", type=float, default=2000)
    parser.add_argument("--bond-volume-more", type=float, default=60000)
    parser.add_argument("--require-known-coupons", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--cache-hours", type=float, default=DEFAULT_CACHE_HOURS)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--log-file", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ScannerConfig(**vars(args))
    try:
        run_scan(config, PROJECT_ROOT)
    except ValueError as exc:
        raise SystemExit(f"Ошибка параметров: {exc}") from exc


if __name__ == "__main__":
    main()
