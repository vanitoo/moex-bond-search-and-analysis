from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from pipeline_common import safe_float
from portfolio_store import load_portfolio, save_portfolio, upsert_position

MOEX = "https://iss.moex.com/iss"


def _rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, row)) for row in section.get("data") or []]


def lookup_bond(secid: str) -> dict[str, Any]:
    secid = str(secid or "").strip().upper()
    if not secid:
        raise ValueError("Не указан SECID")

    search = requests.get(
        f"{MOEX}/securities.json",
        params={
            "q": secid,
            "iss.meta": "off",
            "securities.columns": "secid,shortname,name,emitent_title",
        },
        timeout=25,
    )
    search.raise_for_status()
    rows = _rows(search.json(), "securities")
    match = next((row for row in rows if str(row.get("secid") or "").upper() == secid), None)
    if match is None:
        raise ValueError(f"MOEX не нашла облигацию {secid}")

    market = requests.get(
        f"{MOEX}/engines/stock/markets/bonds/securities/{quote(secid)}.json",
        params={
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,SHORTNAME,SECNAME,FACEVALUE,ACCRUEDINT,MATDATE",
            "marketdata.columns": "SECID,LAST,MARKETPRICE,LCURRENTPRICE,BID,OFFER,YIELD,UPDATETIME",
        },
        timeout=25,
    )
    market.raise_for_status()
    payload = market.json()
    securities = _rows(payload, "securities")
    marketdata = _rows(payload, "marketdata")
    sec = next((row for row in securities if str(row.get("SECID") or "").upper() == secid), securities[0] if securities else {})
    md = next((row for row in marketdata if str(row.get("SECID") or "").upper() == secid), marketdata[0] if marketdata else {})

    face = safe_float(sec.get("FACEVALUE"), 1000.0) or 1000.0
    accrued = safe_float(sec.get("ACCRUEDINT"), 0.0) or 0.0
    price = safe_float(md.get("OFFER") or md.get("LAST") or md.get("MARKETPRICE") or md.get("LCURRENTPRICE"))
    return {
        "secid": secid,
        "name": sec.get("SECNAME") or sec.get("SHORTNAME") or match.get("name") or match.get("shortname") or secid,
        "shortname": sec.get("SHORTNAME") or match.get("shortname") or secid,
        "issuer": match.get("emitent_title") or "",
        "face_value": face,
        "accrued_interest": accrued,
        "maturity_date": sec.get("MATDATE") or "",
        "market_price_percent": price,
        "yield": safe_float(md.get("YIELD")),
        "market_time": md.get("UPDATETIME") or "",
    }


def make_position(
    bond: dict[str, Any],
    *,
    quantity: int,
    purchase_price_percent: float | None = None,
    invested: float | None = None,
    purchase_date: str | date | None = None,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("Количество должно быть больше нуля")
    face = safe_float(bond.get("face_value"), 1000.0) or 1000.0
    accrued = safe_float(bond.get("accrued_interest"), 0.0) or 0.0
    price = safe_float(purchase_price_percent)
    if price is None:
        price = safe_float(bond.get("market_price_percent"))
    if price is None or price <= 0:
        raise ValueError("Нужно указать цену покупки")
    calculated = quantity * (face * price / 100.0 + accrued)
    invested_value = safe_float(invested)
    if invested_value is None:
        invested_value = calculated
    if invested_value <= 0:
        raise ValueError("Сумма вложений должна быть больше нуля")
    if isinstance(purchase_date, date):
        purchase_date = purchase_date.isoformat()
    purchase_date = str(purchase_date or date.today().isoformat())
    return {
        "secid": bond["secid"],
        "name": bond.get("name") or bond["secid"],
        "issuer": bond.get("issuer") or "",
        "quantity": int(quantity),
        "purchase_price_percent": float(price),
        "purchase_date": purchase_date,
        "invested": round(float(invested_value), 2),
        "yield": bond.get("yield"),
        "face_value": face,
        "maturity_date": bond.get("maturity_date") or "",
        "source": "manual",
    }


def add_manual_position(
    portfolio: dict[str, Any],
    secid: str,
    *,
    quantity: int,
    purchase_price_percent: float | None = None,
    invested: float | None = None,
    purchase_date: str | date | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bond = lookup_bond(secid)
    position = make_position(
        bond,
        quantity=quantity,
        purchase_price_percent=purchase_price_percent,
        invested=invested,
        purchase_date=purchase_date,
    )
    return upsert_position(portfolio, position), bond


def main() -> None:
    parser = argparse.ArgumentParser(description="Добавить произвольную облигацию MOEX в виртуальный портфель")
    parser.add_argument("--name", required=True)
    parser.add_argument("--secid", required=True)
    parser.add_argument("--quantity", type=int, required=True)
    parser.add_argument("--purchase-price", type=float)
    parser.add_argument("--invested", type=float)
    parser.add_argument("--purchase-date")
    parser.add_argument("--portfolio-dir", default="data/virtual_portfolios")
    args = parser.parse_args()

    portfolio_dir = Path(args.portfolio_dir)
    portfolio = load_portfolio(portfolio_dir, args.name)
    updated, bond = add_manual_position(
        portfolio,
        args.secid,
        quantity=args.quantity,
        purchase_price_percent=args.purchase_price,
        invested=args.invested,
        purchase_date=args.purchase_date,
    )
    path = save_portfolio(portfolio_dir, updated)
    print(f"Добавлено/обновлено: {bond['secid']} — {bond['name']}")
    print(path)


if __name__ == "__main__":
    main()
