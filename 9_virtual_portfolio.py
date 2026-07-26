from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

from pipeline_common import latest, safe_float

MOEX = "https://iss.moex.com/iss"
PORTFOLIO_DIR = Path("data/virtual_portfolios")
REPORT_DIR = Path("reports")
RATING_ORDER = ["D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA"]

STRATEGIES = {
    "cautious": {"title": "Осторожная", "min_rating": "A-", "min_score": 85, "max_positions": 12, "max_share": 0.10, "cash": 0.10, "yield_weight": 0.20},
    "balanced": {"title": "Сбалансированная", "min_rating": "BBB-", "min_score": 82, "max_positions": 10, "max_share": 0.12, "cash": 0.05, "yield_weight": 0.40},
    "aggressive": {"title": "Агрессивная", "min_rating": "BBB-", "min_score": 80, "max_positions": 8, "max_share": 0.15, "cash": 0.03, "yield_weight": 0.65},
}

@dataclass
class Position:
    secid: str
    name: str
    quantity: int
    average_price: float
    invested: float
    rating: str = ""
    decision_score: float = 0.0
    expected_yield: float = 0.0
    stage4_max_amount: float = 0.0
    stage4_max_quantity: int = 0
    last_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    current_decision: str = "Купить"

@dataclass
class Operation:
    timestamp: str
    type: str
    secid: str
    quantity: int
    price: float
    amount: float
    comment: str = ""

@dataclass
class Portfolio:
    name: str
    strategy: str
    created_at: str
    updated_at: str
    initial_cash: float
    contributed_cash: float
    cash: float
    positions: list[Position] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    source_candidates: str = ""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rating(value: Any) -> str:
    text = re.sub(r"[^A-Z+\-]", "", str(value or "").upper().replace("(RU)", "").replace("RU", ""))
    for item in sorted(RATING_ORDER, key=len, reverse=True):
        if item in text: return item
    return ""


def path_for(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", name.strip())
    if not safe: raise ValueError("Пустое имя портфеля")
    return PORTFOLIO_DIR / f"{safe}.json"


def save(portfolio: Portfolio) -> Path:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    portfolio.updated_at = now()
    path = path_for(portfolio.name)
    path.write_text(json.dumps(asdict(portfolio), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load(name: str) -> Portfolio:
    data = json.loads(path_for(name).read_text(encoding="utf-8"))
    data.setdefault("contributed_cash", data.get("initial_cash", 0.0))
    data["positions"] = [Position(**row) for row in data.get("positions", [])]
    data["operations"] = [Operation(**row) for row in data.get("operations", [])]
    return Portfolio(**data)


def load_candidates(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict): payload = payload.get("candidates") or payload.get("items") or []
    result = []
    for row in payload:
        secid = str(row.get("Код ценной бумаги") or row.get("secid") or "").strip()
        if not secid: continue
        result.append({
            "secid": secid,
            "name": str(row.get("Полное наименование") or row.get("name") or secid),
            "yield": safe_float(row.get("Доходность"), 0.0) or 0.0,
            "rating": rating(row.get("Рейтинг")),
            "score": safe_float(row.get("Финальный балл") or row.get("Итоговый кредитный балл"), 0.0) or 0.0,
            "max_share_text": str(row.get("Максимальная доля") or ""),
            "max_amount": safe_float(row.get("Максимум к покупке, руб."), 0.0) or 0.0,
            "max_qty": int(safe_float(row.get("Максимум к покупке, шт."), 0.0) or 0),
            "spread": safe_float(row.get("Спред, %")),
        })
    return result


def moex_cost(secid: str) -> tuple[float, float]:
    time.sleep(0.25)
    response = requests.get(f"{MOEX}/securities/{quote(secid)}.json", params={"iss.meta": "off", "iss.only": "marketdata,securities", "marketdata.columns": "LAST,MARKETPRICE,LCURRENTPRICE,OFFER", "securities.columns": "FACEVALUE,ACCRUEDINT"}, timeout=25)
    response.raise_for_status(); payload = response.json()
    def rows(block: str) -> list[dict]:
        section = payload.get(block) or {}; return [dict(zip(section.get("columns") or [], row)) for row in section.get("data") or []]
    market, securities = rows("marketdata"), rows("securities")
    price = next((safe_float(r.get("OFFER") or r.get("LAST") or r.get("MARKETPRICE") or r.get("LCURRENTPRICE")) for r in market if safe_float(r.get("OFFER") or r.get("LAST") or r.get("MARKETPRICE") or r.get("LCURRENTPRICE"))), None)
    face = next((safe_float(r.get("FACEVALUE")) for r in securities if safe_float(r.get("FACEVALUE"))), 1000.0) or 1000.0
    accrued = next((safe_float(r.get("ACCRUEDINT"), 0.0) for r in securities), 0.0) or 0.0
    if not price: raise ValueError("MOEX не вернула цену")
    return face * price / 100.0 + accrued, price


def strategy_candidates(items: list[dict], strategy: dict) -> list[dict]:
    min_index = RATING_ORDER.index(strategy["min_rating"])
    eligible = []
    for item in items:
        if item["rating"] not in RATING_ORDER or RATING_ORDER.index(item["rating"]) < min_index: continue
        if item["score"] < strategy["min_score"] or item["max_amount"] <= 0 or item["max_qty"] <= 0: continue
        quality = item["score"] / 100
        yield_norm = min(max(item["yield"], 0), 40) / 40
        item = dict(item); item["rank"] = quality * (1 - strategy["yield_weight"]) + yield_norm * strategy["yield_weight"]
        eligible.append(item)
    return sorted(eligible, key=lambda x: x["rank"], reverse=True)[:strategy["max_positions"]]


def share_limit(text: str, fallback: float) -> float:
    values = re.findall(r"\d+(?:[.,]\d+)?", text)
    return min(fallback, (safe_float(values[-1], fallback * 100) or fallback * 100) / 100) if values else fallback


def allocate(items: list[dict], amount: float, strategy: dict, existing: dict[str, Position] | None = None) -> tuple[list[tuple[dict, int, float, float]], float]:
    existing = existing or {}
    investable = amount * (1 - strategy["cash"])
    priced = []
    for item in items:
        try:
            cost, price_pct = moex_cost(item["secid"])
        except Exception as exc:
            print(f"Пропуск {item['secid']}: {exc}"); continue
        already_amount = existing.get(item["secid"]).invested if item["secid"] in existing else 0.0
        already_qty = existing.get(item["secid"]).quantity if item["secid"] in existing else 0
        strategy_cap = investable * share_limit(item["max_share_text"], strategy["max_share"])
        remaining_stage4_amount = max(0.0, item["max_amount"] - already_amount)
        remaining_stage4_qty = max(0, item["max_qty"] - already_qty)
        cap = min(strategy_cap, remaining_stage4_amount, remaining_stage4_qty * cost)
        if cap >= cost:
            row = dict(item); row.update(cost=cost, price_pct=price_pct, cap=cap); priced.append(row)
    allocations = {x["secid"]: 0 for x in priced}; spent = {x["secid"]: 0.0 for x in priced}; remaining = investable
    while True:
        changed = False
        for item in priced:
            if item["cost"] <= remaining and spent[item["secid"]] + item["cost"] <= item["cap"] + 1e-6:
                allocations[item["secid"]] += 1; spent[item["secid"]] += item["cost"]; remaining -= item["cost"]; changed = True
        if not changed: break
    purchases = [(item, allocations[item["secid"]], item["cost"], spent[item["secid"]]) for item in priced if allocations[item["secid"]] > 0]
    return purchases, amount - sum(x[3] for x in purchases)


def apply(portfolio: Portfolio, purchases: list[tuple[dict, int, float, float]], op_type: str) -> None:
    by_id = {p.secid: p for p in portfolio.positions}
    for item, qty, unit, total in purchases:
        if item["secid"] in by_id:
            pos = by_id[item["secid"]]; new_qty = pos.quantity + qty
            pos.average_price = (pos.invested + total) / new_qty; pos.quantity = new_qty; pos.invested += total
            pos.stage4_max_amount = item["max_amount"]; pos.stage4_max_quantity = item["max_qty"]
        else:
            pos = Position(item["secid"], item["name"], qty, unit, total, item["rating"], item["score"], item["yield"], item["max_amount"], item["max_qty"])
            portfolio.positions.append(pos); by_id[pos.secid] = pos
        portfolio.operations.append(Operation(now(), op_type, item["secid"], qty, unit, total, "Лимиты стратегии и этапа 4 соблюдены"))
        portfolio.cash -= total


def create_cmd(args: argparse.Namespace) -> None:
    if args.strategy not in STRATEGIES: raise ValueError("Неизвестная стратегия")
    if path_for(args.name).exists(): raise FileExistsError("Портфель уже существует")
    source = Path(args.candidates) if args.candidates else latest(Path("."), "bond_candidates_*.json")
    items = strategy_candidates(load_candidates(source), STRATEGIES[args.strategy])
    portfolio = Portfolio(args.name, args.strategy, now(), now(), args.amount, args.amount, args.amount, source_candidates=source.name)
    purchases, _ = allocate(items, args.amount, STRATEGIES[args.strategy])
    apply(portfolio, purchases, "BUY")
    print(save(portfolio))


def add_cmd(args: argparse.Namespace) -> None:
    portfolio = load(args.name); portfolio.cash += args.amount; portfolio.contributed_cash += args.amount
    portfolio.operations.append(Operation(now(), "ADD_CASH", "", 0, 0, args.amount, "Пополнение"))
    source = Path(args.candidates) if args.candidates else latest(Path("."), "bond_candidates_*.json")
    items = strategy_candidates(load_candidates(source), STRATEGIES[portfolio.strategy])
    purchases, _ = allocate(items, portfolio.cash, STRATEGIES[portfolio.strategy], {p.secid: p for p in portfolio.positions})
    apply(portfolio, purchases, "BUY_ADD")
    portfolio.source_candidates = source.name
    print(save(portfolio))


def analyze_cmd(args: argparse.Namespace) -> None:
    portfolio = load(args.name)
    decisions_path = latest(Path("."), "bond_decisions_*.xlsx", required=False)
    decisions = {}
    if decisions_path:
        df = pd.read_excel(decisions_path, sheet_name="Решения")
        decisions = {str(r["Код ценной бумаги"]): str(r["Финальное решение"]) for _, r in df.iterrows()}
    for pos in portfolio.positions:
        try:
            cost, price_pct = moex_cost(pos.secid); pos.last_price = price_pct; pos.market_value = cost * pos.quantity; pos.unrealized_pnl = pos.market_value - pos.invested
        except Exception as exc:
            print(f"{pos.secid}: {exc}")
        pos.current_decision = decisions.get(pos.secid, "Нет в свежем решении")
    save(portfolio)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [asdict(p) for p in portfolio.positions]
    report = REPORT_DIR / f"virtual_portfolio_{re.sub(r'[^a-zA-Zа-яА-Я0-9_.-]+', '_', portfolio.name)}_{datetime.now():%Y-%m-%d}.html"
    summary = f"Внесено: {portfolio.contributed_cash:,.2f} ₽; кэш: {portfolio.cash:,.2f} ₽; стоимость позиций: {sum(p.market_value for p in portfolio.positions):,.2f} ₽"
    report.write_text(f"<h1>{portfolio.name}</h1><p>{summary}</p>" + pd.DataFrame(rows).to_html(index=False), encoding="utf-8")
    print(report)


def show_cmd(args: argparse.Namespace) -> None:
    p = load(args.name)
    print(f"{p.name} | {STRATEGIES[p.strategy]['title']} | внесено {p.contributed_cash:.2f} ₽ | кэш {p.cash:.2f} ₽")
    for x in p.positions: print(f"{x.secid}: {x.quantity} шт., вложено {x.invested:.2f} ₽, лимит этапа 4 {x.stage4_max_amount:.2f} ₽/{x.stage4_max_quantity} шт.")


def history_cmd(args: argparse.Namespace) -> None:
    for op in load(args.name).operations: print(op.timestamp, op.type, op.secid, op.quantity, f"{op.amount:.2f} ₽", op.comment)


def rebalance_cmd(args: argparse.Namespace) -> None:
    p = load(args.name); total = p.cash + sum(x.market_value or x.invested for x in p.positions)
    for x in p.positions:
        value = x.market_value or x.invested; share = value / total if total else 0
        action = "Продать/сократить" if x.current_decision in {"Не покупать", "Недостаточно данных"} else "Не докупать" if x.invested >= x.stage4_max_amount else "Держать"
        print(f"{x.secid}: {share:.1%} — {action}")


def main() -> None:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create"); create.add_argument("--name", required=True); create.add_argument("--strategy", required=True, choices=STRATEGIES); create.add_argument("--amount", required=True, type=float); create.add_argument("--candidates")
    add = sub.add_parser("add"); add.add_argument("--name", required=True); add.add_argument("--amount", required=True, type=float); add.add_argument("--candidates")
    for name in ("analyze", "show", "history", "rebalance"):
        cmd = sub.add_parser(name); cmd.add_argument("--name", required=True)
    args = parser.parse_args(); {"create": create_cmd, "add": add_cmd, "analyze": analyze_cmd, "show": show_cmd, "history": history_cmd, "rebalance": rebalance_cmd}[args.command](args)

if __name__ == "__main__": main()
