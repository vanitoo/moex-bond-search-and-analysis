from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from pipeline_common import dated_name, latest, safe_float

MOEX = "https://iss.moex.com/iss"


def rows(payload: dict, block: str) -> list[dict]:
    section = payload.get(block) or {}
    return [dict(zip(section.get("columns") or [], row)) for row in section.get("data") or []]


def fetch(secid: str) -> dict:
    time.sleep(0.35)
    url = f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json"
    response = requests.get(url, params={"iss.meta": "off", "iss.only": "coupons,amortizations,offers"}, timeout=30)
    response.raise_for_status()
    data = response.json()
    today = date.today()
    coupons = rows(data, "coupons")
    amortizations = rows(data, "amortizations")
    offers = rows(data, "offers")

    future_coupon_rows = []
    total_coupon = 0.0
    unknown = 0
    next_coupon = ""
    for row in coupons:
        dt = pd.to_datetime(row.get("coupondate") or row.get("COUPONDATE"), errors="coerce")
        if pd.isna(dt) or dt.date() < today:
            continue
        future_coupon_rows.append(row)
        value = safe_float(row.get("value") or row.get("VALUE"))
        if value is None:
            unknown += 1
        else:
            total_coupon += value
        if not next_coupon or dt.date().isoformat() < next_coupon:
            next_coupon = dt.date().isoformat()

    future_amort = []
    total_amort = 0.0
    for row in amortizations:
        dt = pd.to_datetime(row.get("amortdate") or row.get("AMORTDATE"), errors="coerce")
        if pd.isna(dt) or dt.date() < today:
            continue
        future_amort.append(row)
        total_amort += safe_float(row.get("value") or row.get("VALUE"), 0.0) or 0.0

    future_offer_dates = []
    for row in offers:
        dt = pd.to_datetime(row.get("offerdate") or row.get("OFFERDATE") or row.get("enddate") or row.get("ENDDATE"), errors="coerce")
        if not pd.isna(dt) and dt.date() >= today:
            future_offer_dates.append(dt.date().isoformat())

    return {
        "Код ценной бумаги": secid,
        "Будущих купонов": len(future_coupon_rows),
        "Неизвестных купонов": unknown,
        "Сумма известных будущих купонов, руб.": round(total_coupon, 2),
        "Ближайший купон": next_coupon,
        "Будущих амортизаций": len(future_amort),
        "Сумма будущих амортизаций, руб.": round(total_amort, 2),
        "Ближайшая оферта": min(future_offer_dates) if future_offer_dates else "",
        "Полнота cashflow": "Низкая" if unknown else "Высокая",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(".")
    source = Path(args.input) if args.input else latest(root, "bond_search_*.xlsx")
    df = pd.read_excel(source, sheet_name="Результаты поиска")
    result = []
    for index, secid in enumerate(df["Код ценной бумаги"].dropna().astype(str).unique(), 1):
        print(f"[{index}] cashflow {secid}")
        try:
            result.append(fetch(secid))
        except Exception as exc:
            result.append({"Код ценной бумаги": secid, "Ошибка cashflow": str(exc), "Полнота cashflow": "Ошибка"})
    output = Path(args.output or dated_name("bond_cashflow", "xlsx"))
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(result).to_excel(writer, sheet_name="Cashflow", index=False)
    print(output)


if __name__ == "__main__":
    main()
