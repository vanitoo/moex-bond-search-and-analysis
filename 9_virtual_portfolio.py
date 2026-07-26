# 📁 Виртуальный портфель облигаций
#
# Пункт 4 дорожной карты.
# Команды:
#   create   — создать портфель по стратегии и сумме;
#   add      — докупить бумаги на дополнительную сумму;
#   analyze  — переоценить портфель и проверить текущие решения;
#   show     — показать текущее состояние;
#   history  — показать историю виртуальных операций;
#   rebalance — показать план выравнивания без совершения операций.
#
# Источник кандидатов: последний bond_candidates_YYYY-MM-DD.json,
# созданный скриптом 8_bonds_decision.py.
# Портфели хранятся в data/virtual_portfolios/<имя>.json.

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

MOEX_BASE = "https://iss.moex.com/iss"
REQUEST_TIMEOUT = 25
REQUEST_DELAY = 0.35
PORTFOLIO_DIR = Path("data/virtual_portfolios")
REPORT_DIR = Path("reports")


@dataclass(frozen=True)
class Strategy:
    code: str
    title: str
    min_rating_index: int
    min_score: int
    max_positions: int
    max_position_share: float
    cash_reserve: float
    yield_weight: float
    quality_weight: float


RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]

STRATEGIES = {
    "cautious": Strategy("cautious", "Осторожная", RATING_ORDER.index("A-"), 85, 12, 0.10, 0.10, 0.20, 0.80),
    "balanced": Strategy("balanced", "Сбалансированная", RATING_ORDER.index("BBB-"), 82, 10, 0.12, 0.05, 0.40, 0.60),
    "aggressive": Strategy("aggressive", "Агрессивная", RATING_ORDER.index("BBB-"), 80, 8, 0.15, 0.03, 0.65, 0.35),
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
    cash: float
    positions: list[Position] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    source_candidates: str = ""


def normalize_rating(value: Any) -> str:
    text = str(value or "").upper().replace("(RU)", "").replace("RU", "").strip()
    text = re.sub(r"[^A-Z+\-]", "", text)
    for rating in sorted(RATING_ORDER, key=len, reverse=True):
        if rating in text:
            return rating
    return ""


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return default


def rub(value: float) -> str:
    return f"{value:,.2f} ₽".replace(",", " ").replace(".", ",")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def portfolio_path(name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", name.strip())
    if not safe_name:
        raise ValueError("Имя портфеля не может быть пустым")
    return PORTFOLIO_DIR / f"{safe_name}.json"


def find_latest_candidates(root: Path) -> Path:
    files = [p for p in root.glob("bond_candidates_*.json") if not p.name.startswith("~$")]
    if not files:
        files = [p for p in root.glob("reports/bond_candidates_*.json")]
    if not files:
        raise FileNotFoundError("Не найден bond_candidates_YYYY-MM-DD.json. Сначала запустите скрипт №8.")
    return max(files, key=lambda p: p.stat().st_mtime)


def load_candidates(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        for key in ("candidates", "items", "bonds"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError("JSON кандидатов должен содержать список бумаг")
    result: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        secid = str(raw.get("Код ценной бумаги") or raw.get("secid") or raw.get("code") or "").strip()
        if not secid:
            continue
        result.append({
            "secid": secid,
            "name": str(raw.get("Полное наименование") or raw.get("name") or raw.get("Название") or secid),
            "yield": safe_float(raw.get("Доходность") or raw.get("yield")),
            "rating": normalize_rating(raw.get("Рейтинг") or raw.get("rating")),
            "score": safe_float(raw.get("Итоговый кредитный балл") or raw.get("Кредитный балл") or raw.get("score")),
            "max_share": str(raw.get("Максимальная доля") or raw.get("max_share") or ""),
            "confidence": str(raw.get("Уверенность") or raw.get("confidence") or ""),
        })
    if not result:
        raise ValueError("В файле кандидатов нет пригодных бумаг")
    return result


def moex_price(secid: str) -> tuple[float, float, float]:
    """Возвращает цену в процентах, НКД и номинал."""
    time.sleep(REQUEST_DELAY)
    url = f"{MOEX_BASE}/securities/{quote(secid)}.json"
    params = {"iss.meta": "off", "iss.only": "marketdata,securities", "marketdata.columns": "SECID,LAST,MARKETPRICE,LCURRENTPRICE", "securities.columns": "SECID,FACEVALUE,ACCRUEDINT"}
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    def rows(block: str) -> list[dict[str, Any]]:
        section = data.get(block) or {}
        cols = section.get("columns") or []
        return [dict(zip(cols, row)) for row in section.get("data") or []]

    market = rows("marketdata")
    security = rows("securities")
    price = 0.0
    for row in market:
        price = safe_float(row.get("LAST") or row.get("MARKETPRICE") or row.get("LCURRENTPRICE"))
        if price > 0:
            break
    face = next((safe_float(r.get("FACEVALUE")) for r in security if safe_float(r.get("FACEVALUE")) > 0), 1000.0)
    accrued = next((safe_float(r.get("ACCRUEDINT")) for r in security), 0.0)
    if price <= 0:
        raise ValueError("MOEX не вернула текущую цену")
    return price, accrued, face


def unit_cost(secid: str) -> tuple[float, float]:
    price_pct, accrued, face = moex_price(secid)
    return face * price_pct / 100.0 + accrued, price_pct


def strategy_filter(candidates: list[dict[str, Any]], strategy: Strategy) -> list[dict[str, Any]]:
    eligible = []
    for item in candidates:
        rating = item["rating"]
        rating_index = RATING_ORDER.index(rating) if rating in RATING_ORDER else -1
        if rating_index < strategy.min_rating_index or item["score"] < strategy.min_score:
            continue
        quality = item["score"] / 100.0
        yield_norm = min(max(item["yield"], 0.0), 40.0) / 40.0
        item = dict(item)
        item["rank"] = quality * strategy.quality_weight + yield_norm * strategy.yield_weight
        eligible.append(item)
    return sorted(eligible, key=lambda x: (x["rank"], x["score"], x["yield"]), reverse=True)[:strategy.max_positions]


def parse_max_share(text: str, fallback: float) -> float:
    values = re.findall(r"\d+(?:[.,]\d+)?", str(text))
    if not values:
        return fallback
    return min(fallback, safe_float(values[-1]) / 100.0)


def allocate(candidates: list[dict[str, Any]], amount: float, strategy: Strategy) -> tuple[list[tuple[dict[str, Any], int, float, float]], float]:
    if amount <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    investable = amount * (1.0 - strategy.cash_reserve)
    priced: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        try:
            cost, price_pct = unit_cost(item["secid"])
            item = dict(item)
            item["unit_cost"] = cost
            item["price_pct"] = price_pct
            item["cap"] = investable * parse_max_share(item.get("max_share", ""), strategy.max_position_share)
            priced.append(item)
            print(f"[{index}/{len(candidates)}] {item['secid']}: одна бумага ≈ {rub(cost)}")
        except Exception as exc:
            print(f"Пропуск {item['secid']}: {exc}")

    if not priced:
        raise ValueError("Не удалось получить цены ни по одной бумаге")

    allocations: dict[str, int] = {item["secid"]: 0 for item in priced}
    spent: dict[str, float] = {item["secid"]: 0.0 for item in priced}
    remaining = investable

    # Покупаем по одной бумаге за проход, соблюдая лимит позиции.
    while True:
        changed = False
        for item in priced:
            cost = item["unit_cost"]
            secid = item["secid"]
            if cost <= remaining and spent[secid] + cost <= item["cap"] + 1e-6:
                allocations[secid] += 1
                spent[secid] += cost
                remaining -= cost
                changed = True
        if not changed:
            break

    result = []
    for item in priced:
        qty = allocations[item["secid"]]
        if qty:
            result.append((item, qty, item["unit_cost"], spent[item["secid"]]))
    return result, amount - sum(x[3] for x in result)


def save_portfolio(portfolio: Portfolio) -> Path:
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    portfolio.updated_at = now()
    path = portfolio_path(portfolio.name)
    path.write_text(json.dumps(asdict(portfolio), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_portfolio(name: str) -> Portfolio:
    path = portfolio_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Портфель не найден: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["positions"] = [Position(**row) for row in data.get("positions", [])]
    data["operations"] = [Operation(**row) for row in data.get("operations", [])]
    return Portfolio(**data)


def apply_purchases(portfolio: Portfolio, purchases: list[tuple[dict[str, Any], int, float, float]], operation_type: str) -> None:
    by_secid = {p.secid: p for p in portfolio.positions}
    for item, qty, unit_price, total in purchases:
        existing = by_secid.get(item["secid"])
        if existing:
            new_qty = existing.quantity + qty
            existing.average_price = (existing.invested + total) / new_qty
            existing.quantity = new_qty
            existing.invested += total
            existing.rating = item["rating"]
            existing.decision_score = item["score"]
            existing.expected_yield = item["yield"]
        else:
            existing = Position(
                secid=item["secid"], name=item["name"], quantity=qty,
                average_price=unit_price, invested=total, rating=item["rating"],
                decision_score=item["score"], expected_yield=item["yield"],
            )
            portfolio.positions.append(existing)
            by_secid[existing.secid] = existing
        portfolio.operations.append(Operation(now(), operation_type, item["secid"], qty, unit_price, total, f"Стратегия: {portfolio.strategy}"))
        portfolio.cash -= total


def create_command(args: argparse.Namespace) -> None:
    if portfolio_path(args.name).exists() and not args.force:
        raise FileExistsError("Портфель уже существует. Используйте другое имя или --force.")
    source = Path(args.candidates) if args.candidates else find_latest_candidates(Path("."))
    candidates = load_candidates(source)
    strategy = STRATEGIES[args.strategy]
    selected = strategy_filter(candidates, strategy)
    if not selected:
        raise ValueError("Ни одна бумага не прошла ограничения выбранной стратегии")
    purchases, cash = allocate(selected, args.amount, strategy)
    portfolio = Portfolio(args.name, strategy.code, now(), now(), args.amount, args.amount, source_candidates=str(source))
    apply_purchases(portfolio, purchases, "BUY")
    portfolio.cash = cash
    path = save_portfolio(portfolio)
    print_summary(portfolio)
    print(f"Сохранено: {path}")


def add_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(args.name)
    strategy = STRATEGIES[portfolio.strategy]
    source = Path(args.candidates) if args.candidates else find_latest_candidates(Path("."))
    selected = strategy_filter(load_candidates(source), strategy)
    portfolio.cash += args.amount
    portfolio.initial_cash += args.amount
    purchases, remaining = allocate(selected, args.amount + (portfolio.cash - args.amount), strategy)
    apply_purchases(portfolio, purchases, "ADD")
    portfolio.cash = remaining
    portfolio.source_candidates = str(source)
    save_portfolio(portfolio)
    print_summary(portfolio)


def refresh_prices(portfolio: Portfolio) -> None:
    for index, position in enumerate(portfolio.positions, start=1):
        try:
            cost, _ = unit_cost(position.secid)
            position.last_price = cost
            position.market_value = cost * position.quantity
            position.unrealized_pnl = position.market_value - position.invested
            print(f"[{index}/{len(portfolio.positions)}] {position.secid}: {rub(cost)}")
        except Exception as exc:
            print(f"Цена {position.secid} не обновлена: {exc}")
            position.market_value = position.invested
            position.unrealized_pnl = 0.0


def load_latest_decisions() -> dict[str, str]:
    files = list(Path(".").glob("bond_decisions_*.xlsx")) + list(Path("reports").glob("bond_decisions_*.xlsx"))
    if not files:
        return {}
    path = max(files, key=lambda p: p.stat().st_mtime)
    try:
        df = pd.read_excel(path, sheet_name="Решения")
    except Exception:
        return {}
    return {str(row.get("Код ценной бумаги", "")).strip(): str(row.get("Решение", "")) for _, row in df.iterrows()}


def analyze_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(args.name)
    refresh_prices(portfolio)
    decisions = load_latest_decisions()
    for position in portfolio.positions:
        position.current_decision = decisions.get(position.secid, "Нет в свежем анализе")
    save_portfolio(portfolio)
    write_report(portfolio)
    print_summary(portfolio)
    print("Решения по позициям:")
    for position in portfolio.positions:
        print(f"  {position.secid}: {position.current_decision}")


def show_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(args.name)
    print_summary(portfolio)
    for p in portfolio.positions:
        value = p.market_value or p.invested
        print(f"  {p.secid:<14} {p.quantity:>4} шт.  {rub(value):>16}  {p.current_decision}")


def history_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(args.name)
    if not portfolio.operations:
        print("История операций пуста")
        return
    for op in portfolio.operations:
        print(f"{op.timestamp}  {op.type:<5} {op.secid:<14} {op.quantity:>4} шт.  {rub(op.amount)}  {op.comment}")


def rebalance_command(args: argparse.Namespace) -> None:
    portfolio = load_portfolio(args.name)
    refresh_prices(portfolio)
    total = portfolio.cash + sum(p.market_value for p in portfolio.positions)
    active = [p for p in portfolio.positions if p.current_decision not in {"Не покупать", "Недостаточно данных"}]
    if not active:
        active = portfolio.positions
    target = (total * (1 - STRATEGIES[portfolio.strategy].cash_reserve) / len(active)) if active else 0
    print(f"Общая стоимость: {rub(total)}; ориентир на позицию: {rub(target)}")
    for p in portfolio.positions:
        delta = target - p.market_value
        action = "докупить" if delta > 0 else "сократить"
        print(f"  {p.secid}: {action} примерно на {rub(abs(delta))}")
    print("Это только предварительный план. Операции не записаны.")


def print_summary(portfolio: Portfolio) -> None:
    invested = sum(p.invested for p in portfolio.positions)
    market = sum((p.market_value or p.invested) for p in portfolio.positions)
    total = market + portfolio.cash
    pnl = market - invested
    print(f"\nПортфель: {portfolio.name} ({STRATEGIES[portfolio.strategy].title})")
    print(f"Позиций: {len(portfolio.positions)}")
    print(f"Внесено: {rub(portfolio.initial_cash)}")
    print(f"В бумагах: {rub(market)}")
    print(f"Кэш: {rub(portfolio.cash)}")
    print(f"Итого: {rub(total)}")
    print(f"Нереализованный результат: {rub(pnl)}")


def write_report(portfolio: Portfolio) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORT_DIR / f"virtual_portfolio_{portfolio.name}_{datetime.now():%Y-%m-%d}.html"
    rows = []
    for p in sorted(portfolio.positions, key=lambda x: x.market_value, reverse=True):
        rows.append(f"<tr><td>{p.secid}</td><td>{p.name}</td><td>{p.quantity}</td><td>{rub(p.average_price)}</td><td>{rub(p.last_price)}</td><td>{rub(p.market_value)}</td><td>{rub(p.unrealized_pnl)}</td><td>{p.current_decision}</td></tr>")
    invested = sum(p.invested for p in portfolio.positions)
    market = sum(p.market_value for p in portfolio.positions)
    output.write_text(f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{portfolio.name}</title><style>body{{font-family:Arial;background:#f5f7fa;color:#17202a;margin:0}}main{{max-width:1400px;margin:auto;padding:24px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card{{background:white;border:1px solid #e4e7ec;border-radius:12px;padding:16px}}table{{width:100%;border-collapse:collapse;background:white;margin-top:20px}}th,td{{padding:10px;border-bottom:1px solid #e4e7ec;text-align:left}}th{{background:#f9fafb}}@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}table{{font-size:12px}}}}</style></head><body><main><h1>{portfolio.name}</h1><p>Стратегия: {STRATEGIES[portfolio.strategy].title}. Обновлено: {portfolio.updated_at}</p><div class='cards'><div class='card'><b>Внесено</b><div>{rub(portfolio.initial_cash)}</div></div><div class='card'><b>Стоимость бумаг</b><div>{rub(market)}</div></div><div class='card'><b>Кэш</b><div>{rub(portfolio.cash)}</div></div><div class='card'><b>Результат</b><div>{rub(market-invested)}</div></div></div><table><thead><tr><th>Код</th><th>Название</th><th>Количество</th><th>Средняя цена</th><th>Текущая цена</th><th>Стоимость</th><th>Результат</th><th>Решение</th></tr></thead><tbody>{''.join(rows)}</tbody></table></main></body></html>""", encoding="utf-8")
    print(f"HTML-отчёт: {output}")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Виртуальные портфели облигаций")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Создать новый портфель")
    create.add_argument("--name", required=True, help="Имя портфеля")
    create.add_argument("--strategy", choices=STRATEGIES, required=True)
    create.add_argument("--amount", type=float, required=True, help="Начальная сумма в рублях")
    create.add_argument("--candidates", help="Путь к bond_candidates_*.json")
    create.add_argument("--force", action="store_true", help="Перезаписать существующий портфель")
    create.set_defaults(func=create_command)

    add = sub.add_parser("add", help="Внести деньги и докупить бумаги")
    add.add_argument("--name", required=True)
    add.add_argument("--amount", type=float, required=True, help="Дополнительная сумма в рублях")
    add.add_argument("--candidates", help="Путь к свежему списку кандидатов")
    add.set_defaults(func=add_command)

    analyze = sub.add_parser("analyze", help="Обновить цены и проверить решения")
    analyze.add_argument("--name", required=True)
    analyze.set_defaults(func=analyze_command)

    show = sub.add_parser("show", help="Показать портфель")
    show.add_argument("--name", required=True)
    show.set_defaults(func=show_command)

    history = sub.add_parser("history", help="Показать историю операций")
    history.add_argument("--name", required=True)
    history.set_defaults(func=history_command)

    rebalance = sub.add_parser("rebalance", help="Предварительный план ребалансировки")
    rebalance.add_argument("--name", required=True)
    rebalance.set_defaults(func=rebalance_command)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("Операция прервана пользователем")
        return 130
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
