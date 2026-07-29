# 🔴 ЧТО ДЕЛАЕТ МОДУЛЬ: последовательно сканирует рынок облигаций MOEX и отбирает
# выпуски по общим критериям поиска. V1 оставлен как контрольный и резервный сканер.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT / "src"))

from cli import start
from moex_bond_search_and_analysis.schemas import SearchByCriteriaConditions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Контрольный последовательный сканер облигаций MOEX V1")
    parser.add_argument("--yield-more", type=float, default=15, help="Доходность от, %%")
    parser.add_argument("--yield-less", type=float, default=40, help="Доходность до, %%")
    parser.add_argument("--price-more", type=float, default=70, help="Цена от, %% от номинала")
    parser.add_argument("--price-less", type=float, default=120, help="Цена до, %% от номинала")
    parser.add_argument("--duration-more", type=float, default=3, help="Дюрация от, месяцев")
    parser.add_argument("--duration-less", type=float, default=18, help="Дюрация до, месяцев")
    parser.add_argument("--volume-more", type=float, default=2000, help="Минимальный объём каждого дня, шт.")
    parser.add_argument("--bond-volume-more", type=float, default=60000, help="Совокупный объём за 15 дней, шт.")
    parser.add_argument(
        "--require-known-coupons",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Учитывать только выпуски с известными купонами до погашения",
    )
    args = parser.parse_args()

    if args.yield_more > args.yield_less:
        parser.error("Доходность ОТ не может быть больше доходности ДО")
    if args.price_more > args.price_less:
        parser.error("Цена ОТ не может быть больше цены ДО")
    if args.duration_more > args.duration_less:
        parser.error("Дюрация ОТ не может быть больше дюрации ДО")
    if args.volume_more < 0 or args.bond_volume_more < 0:
        parser.error("Объёмы торгов не могут быть отрицательными")
    return args


def main() -> None:
    args = parse_args()
    search_conditions = SearchByCriteriaConditions(
        yield_more=args.yield_more,
        yield_less=args.yield_less,
        price_more=args.price_more,
        price_less=args.price_less,
        duration_more=args.duration_more,
        duration_less=args.duration_less,
        volume_more=args.volume_more,
        bond_volume_more=args.bond_volume_more,
        offer_yes_no="ДА" if args.require_known_coupons else "НЕТ",
    )
    start(1, search_conditions=search_conditions)


if __name__ == "__main__":
    main()
