from __future__ import annotations

import argparse
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from pipeline_common import clean_secid_rows, dated_name, latest, safe_float

MOEX = "https://iss.moex.com/iss"


def rows(payload: dict, block: str) -> list[dict]:
    section = payload.get(block) or {}
    return [dict(zip(section.get("columns") or [], row)) for row in section.get("data") or []]


def fetch(secid: str, impact_share: float) -> dict:
    time.sleep(0.35)
    url = f"{MOEX}/engines/stock/markets/bonds/securities/{quote(secid)}.json"
    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata,orderbook",
        "securities.columns": "SECID,FACEVALUE,ACCRUEDINT",
        "marketdata.columns": "SECID,LAST,MARKETPRICE,LCURRENTPRICE,BID,OFFER,SPREAD,VALTODAY,VOLTODAY",
        "orderbook.columns": "SECID,BUYSELL,PRICE,QUANTITY,VALUE",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    securities = rows(payload, "securities")
    marketdata = rows(payload, "marketdata")
    orderbook = rows(payload, "orderbook")

    face = next((safe_float(r.get("FACEVALUE")) for r in securities if safe_float(r.get("FACEVALUE"))), 1000.0) or 1000.0
    accrued = next((safe_float(r.get("ACCRUEDINT"), 0.0) for r in securities), 0.0) or 0.0
    md = marketdata[0] if marketdata else {}
    price_pct = safe_float(md.get("OFFER") or md.get("LAST") or md.get("MARKETPRICE") or md.get("LCURRENTPRICE"), 0.0) or 0.0
    bid = safe_float(md.get("BID"))
    offer = safe_float(md.get("OFFER"))
    spread_pct = ((offer - bid) / offer * 100.0) if offer and bid and offer > 0 else safe_float(md.get("SPREAD"))
    unit_cost = face * price_pct / 100.0 + accrued if price_pct > 0 else 0.0

    asks = [r for r in orderbook if str(r.get("BUYSELL") or "").upper() in {"S", "SELL"}]
    ask_qty = sum(int(safe_float(r.get("QUANTITY"), 0.0) or 0) for r in asks)
    ask_value = sum(safe_float(r.get("VALUE"), 0.0) or 0.0 for r in asks)
    turnover_value = safe_float(md.get("VALTODAY"), 0.0) or 0.0
    turnover_qty = safe_float(md.get("VOLTODAY"), 0.0) or 0.0

    orderbook_limit = ask_value * impact_share if ask_value > 0 else None
    turnover_limit = turnover_value * impact_share if turnover_value > 0 else None
    if orderbook_limit is not None and turnover_limit is not None:
        market_limit = min(orderbook_limit, turnover_limit)
        limit_source = "Минимум стакана и оборота"
    elif orderbook_limit is not None:
        market_limit = orderbook_limit
        limit_source = "Стакан"
    elif turnover_limit is not None:
        market_limit = turnover_limit
        limit_source = "Только оборот; стакан не получен"
    else:
        market_limit = 0.0
        limit_source = "Нет данных"

    max_qty = int(market_limit // unit_cost) if unit_cost > 0 else 0
    if ask_qty > 0:
        max_qty = min(max_qty, max(1, int(ask_qty * impact_share)))
    max_amount = max_qty * unit_cost

    if price_pct <= 0:
        liquidity = "Нет цены"
        data_quality = "Нет данных"
    elif ask_value <= 0:
        liquidity = "Неизвестно"
        data_quality = "Стакан не получен"
    elif spread_pct is not None and spread_pct > 2:
        liquidity = "Низкая"
        data_quality = "Полная"
    elif max_amount >= 100_000:
        liquidity = "Высокая"
        data_quality = "Полная"
    elif max_amount >= 30_000:
        liquidity = "Средняя"
        data_quality = "Полная"
    else:
        liquidity = "Низкая"
        data_quality = "Полная"

    return {
        "Код ценной бумаги": secid,
        "Цена покупки, %": round(price_pct, 4),
        "НКД, руб.": round(accrued, 2),
        "Стоимость одной бумаги, руб.": round(unit_cost, 2),
        "Bid, %": bid,
        "Offer, %": offer,
        "Спред, %": round(spread_pct, 4) if spread_pct is not None else None,
        "Объем предложения в стакане, шт.": ask_qty,
        "Объем предложения в стакане, руб.": round(ask_value, 2),
        "Лимит по стакану, руб.": round(orderbook_limit, 2) if orderbook_limit is not None else None,
        "Лимит по обороту, руб.": round(turnover_limit, 2) if turnover_limit is not None else None,
        "Источник лимита": limit_source,
        "Качество данных ликвидности": data_quality,
        "Максимум к покупке, шт.": max_qty,
        "Максимум к покупке, руб.": round(max_amount, 2),
        "Ликвидность покупки": liquidity,
        "Лимит влияния на рынок, %": round(impact_share * 100, 2),
        "Оборот сегодня, руб.": round(turnover_value, 2),
        "Оборот сегодня, шт.": round(turnover_qty, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--impact-share", type=float, default=0.10, help="Доля стакана/оборота, которую разрешено забирать")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not 0 < args.impact_share <= 1:
        raise SystemExit("--impact-share должен быть от 0 до 1")
    source = Path(args.input) if args.input else latest(Path("."), "bond_search_*.xlsx")
    df = clean_secid_rows(pd.read_excel(source, sheet_name="Результаты поиска"))
    result = []
    for index, secid in enumerate(df["Код ценной бумаги"].astype(str), 1):
        print(f"[{index}] liquidity {secid}")
        try:
            result.append(fetch(secid, args.impact_share))
        except Exception as exc:
            result.append({"Код ценной бумаги": secid, "Ошибка ликвидности": str(exc), "Ликвидность покупки": "Ошибка", "Качество данных ликвидности": "Ошибка", "Максимум к покупке, руб.": 0})
    output = Path(args.output or dated_name("bond_purchase_volume", "xlsx"))
    pd.DataFrame(result).drop_duplicates(subset=["Код ценной бумаги"]).to_excel(output, sheet_name="Объем покупки", index=False)
    print(output)


if __name__ == "__main__":
    main()
