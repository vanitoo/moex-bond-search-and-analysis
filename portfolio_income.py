from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import pandas as pd
import requests

from pipeline_common import safe_float
from portfolio_store import load_portfolio, safe_name

MOEX = "https://iss.moex.com/iss"


def _rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, row)) for row in section.get("data") or []]


def _date(value: Any) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def fetch_bond_cashflows(secid: str) -> dict[str, Any]:
    response = requests.get(
        f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json",
        params={"iss.meta": "off", "iss.only": "coupons,amortizations,offers"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "coupons": _rows(payload, "coupons"),
        "amortizations": _rows(payload, "amortizations"),
        "offers": _rows(payload, "offers"),
    }


def build_income_schedule(
    portfolio: dict[str, Any],
    *,
    today: date | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_bond_cashflows,
) -> tuple[list[dict[str, Any]], list[str]]:
    today = today or date.today()
    events: list[dict[str, Any]] = []
    errors: list[str] = []

    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or "").strip().upper()
        if not secid:
            continue
        quantity = int(position.get("quantity") or 0)
        if quantity <= 0:
            continue
        name = str(position.get("name") or secid)
        issuer = str(position.get("issuer") or "")
        try:
            payload = fetcher(secid)
        except Exception as exc:
            errors.append(f"{secid}: {exc}")
            continue

        for row in payload.get("coupons", []):
            event_date = _date(row.get("coupondate") or row.get("COUPONDATE"))
            if event_date is None or event_date < today:
                continue
            per_bond = safe_float(row.get("value") or row.get("VALUE"))
            events.append({
                "date": event_date.isoformat(),
                "type": "Купон",
                "secid": secid,
                "name": name,
                "issuer": issuer,
                "quantity": quantity,
                "per_bond": per_bond,
                "amount": round(per_bond * quantity, 2) if per_bond is not None else None,
                "known": per_bond is not None,
            })

        for row in payload.get("amortizations", []):
            event_date = _date(row.get("amortdate") or row.get("AMORTDATE"))
            if event_date is None or event_date < today:
                continue
            per_bond = safe_float(row.get("value") or row.get("VALUE"))
            events.append({
                "date": event_date.isoformat(),
                "type": "Погашение/амортизация",
                "secid": secid,
                "name": name,
                "issuer": issuer,
                "quantity": quantity,
                "per_bond": per_bond,
                "amount": round(per_bond * quantity, 2) if per_bond is not None else None,
                "known": per_bond is not None,
            })

        for row in payload.get("offers", []):
            event_date = _date(
                row.get("offerdate") or row.get("OFFERDATE") or row.get("enddate") or row.get("ENDDATE")
            )
            if event_date is None or event_date < today:
                continue
            events.append({
                "date": event_date.isoformat(),
                "type": "Оферта",
                "secid": secid,
                "name": name,
                "issuer": issuer,
                "quantity": quantity,
                "per_bond": None,
                "amount": None,
                "known": True,
            })

    events.sort(key=lambda item: (item["date"], item["type"], item["secid"]))
    return events, errors


def summarize_income(
    portfolio: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    horizon = today + timedelta(days=365)
    invested = sum(safe_float(item.get("invested"), 0.0) or 0.0 for item in portfolio.get("positions", []))

    coupons_12m = 0.0
    principal_12m = 0.0
    unknown_coupon_events = 0
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"coupons": 0.0, "principal": 0.0})
    payment_dates: list[str] = []

    for event in events:
        event_date = _date(event.get("date"))
        if event_date is None or event_date > horizon:
            continue
        amount = safe_float(event.get("amount"))
        month = event_date.strftime("%Y-%m")
        if event.get("type") == "Купон":
            if amount is None:
                unknown_coupon_events += 1
            else:
                coupons_12m += amount
                monthly[month]["coupons"] += amount
                payment_dates.append(event_date.isoformat())
        elif event.get("type") == "Погашение/амортизация" and amount is not None:
            principal_12m += amount
            monthly[month]["principal"] += amount
            payment_dates.append(event_date.isoformat())

    monthly_rows = [
        {
            "month": month,
            "coupons": round(values["coupons"], 2),
            "principal": round(values["principal"], 2),
            "total": round(values["coupons"] + values["principal"], 2),
        }
        for month, values in sorted(monthly.items())
    ]
    income_months = sum(1 for row in monthly_rows if row["coupons"] > 0)
    coupon_cash_yield = (coupons_12m / invested * 100.0) if invested > 0 else None

    positions = [item for item in portfolio.get("positions", []) if isinstance(item, dict)]
    total_invested = invested or 0.0
    issue_shares: list[tuple[str, float]] = []
    issuer_amounts: dict[str, float] = defaultdict(float)
    for item in positions:
        amount = safe_float(item.get("invested"), 0.0) or 0.0
        secid = str(item.get("secid") or "")
        issuer = str(item.get("issuer") or item.get("name") or secid)
        if total_invested > 0:
            issue_shares.append((secid, amount / total_invested * 100.0))
            issuer_amounts[issuer] += amount

    rebalance_reasons: list[str] = []
    for secid, share in issue_shares:
        if share > 20:
            rebalance_reasons.append(f"Доля выпуска {secid} {share:.1f}% > 20%")
    for issuer, amount in issuer_amounts.items():
        share = amount / total_invested * 100.0 if total_invested else 0.0
        if share > 25:
            rebalance_reasons.append(f"Доля эмитента {issuer} {share:.1f}% > 25%")
    if principal_12m > total_invested * 0.25 and total_invested > 0:
        rebalance_reasons.append(
            f"В ближайшие 12 месяцев вернётся номиналом/амортизацией около {principal_12m / total_invested:.0%} вложенной суммы"
        )
    if income_months < 6 and coupons_12m > 0:
        rebalance_reasons.append(f"Купонные поступления распределены только по {income_months} месяцам из ближайших 12")

    return {
        "invested": round(invested, 2),
        "coupons_12m": round(coupons_12m, 2),
        "principal_12m": round(principal_12m, 2),
        "cashflow_12m": round(coupons_12m + principal_12m, 2),
        "coupon_cash_yield_percent": round(coupon_cash_yield, 2) if coupon_cash_yield is not None else None,
        "average_coupon_month": round(coupons_12m / 12.0, 2),
        "income_months": income_months,
        "unknown_coupon_events": unknown_coupon_events,
        "next_payment_date": min(payment_dates) if payment_dates else None,
        "monthly": monthly_rows,
        "rebalance_needed": bool(rebalance_reasons),
        "rebalance_reasons": rebalance_reasons,
    }


def analyze_portfolio_income(
    portfolio: dict[str, Any],
    *,
    today: date | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_bond_cashflows,
) -> dict[str, Any]:
    events, errors = build_income_schedule(portfolio, today=today, fetcher=fetcher)
    summary = summarize_income(portfolio, events, today=today)
    return {
        "portfolio": portfolio.get("name") or "portfolio",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "events": events,
        "errors": errors,
    }


def write_report(payload: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(str(payload.get("portfolio") or "portfolio"))
    latest_json = report_dir / f"portfolio_income_{name}_latest.json"
    latest_xlsx = report_dir / f"portfolio_income_{name}_latest.xlsx"
    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    events = pd.DataFrame(payload.get("events", []))
    monthly = pd.DataFrame((payload.get("summary") or {}).get("monthly", []))
    summary = pd.DataFrame([{
        key: value for key, value in (payload.get("summary") or {}).items()
        if key not in {"monthly", "rebalance_reasons"}
    }])
    reasons = pd.DataFrame({"Причина ребалансировки": (payload.get("summary") or {}).get("rebalance_reasons", [])})
    with pd.ExcelWriter(latest_xlsx, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Сводка", index=False)
        monthly.to_excel(writer, sheet_name="По месяцам", index=False)
        events.to_excel(writer, sheet_name="Календарь", index=False)
        reasons.to_excel(writer, sheet_name="Ребалансировка", index=False)
    return latest_json, latest_xlsx


def main() -> None:
    parser = argparse.ArgumentParser(description="Доходный календарь и ребалансировка облигационного портфеля")
    parser.add_argument("--name", required=True)
    parser.add_argument("--portfolio-dir", default="data/virtual_portfolios")
    parser.add_argument("--report-dir", default="reports")
    args = parser.parse_args()

    portfolio = load_portfolio(Path(args.portfolio_dir), args.name)
    payload = analyze_portfolio_income(portfolio)
    json_path, xlsx_path = write_report(payload, Path(args.report_dir))
    summary = payload["summary"]
    print(f"Портфель: {args.name}")
    print(f"Купоны 12 мес.: {summary['coupons_12m']:.2f} руб.")
    print(f"Возврат номинала/амортизация 12 мес.: {summary['principal_12m']:.2f} руб.")
    print(f"Месяцев с купонами: {summary['income_months']}/12")
    print(f"Ребалансировка: {'НУЖНА ПРОВЕРКА' if summary['rebalance_needed'] else 'явных причин нет'}")
    print("JSON:", json_path)
    print("XLSX:", xlsx_path)


if __name__ == "__main__":
    main()
