from __future__ import annotations

import argparse
import json
import math
import re
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

MOEX = "https://iss.moex.com/iss"
HISTORY_URL = f"{MOEX}/history/engines/stock/markets/bonds/boards/TQCB/securities.json"
COLUMNS = (
    "SECID,SHORTNAME,WAPRICE,CLOSE,LEGALCLOSEPRICE,LASTPRICE,YIELD,YIELDTOOFFER,"
    "VALUE,NUMTRADES,FACEVALUE,ACCRUEDINT,MATDATE,OFFERDATE,COUPONPERCENT,FACEUNIT"
)


@dataclass
class Position:
    secid: str
    name: str
    quantity: int
    invested: float
    average_full_price: float
    last_full_price: float
    last_clean_price: float
    last_accrued: float
    last_yield: float
    last_spread_bp: float | None


@dataclass
class Operation:
    day: str
    action: str
    secid: str
    quantity: int
    full_price: float
    amount: float
    reason: str


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace(" ", "").replace(",", ".")
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", value.strip()) or "backtest"


def rows(block: dict[str, Any]) -> list[dict[str, Any]]:
    columns = block.get("columns") or []
    return [dict(zip(columns, item)) for item in block.get("data") or []]


class HistoricalStore:
    """Кэш исторических данных, полностью отделённый от ежедневного pipeline."""

    def __init__(self, root: Path, pause: float = 0.15) -> None:
        self.root = root
        self.cache = root / "cache" / "moex_history"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.pause = pause

    def path(self, day: date) -> Path:
        return self.cache / f"TQCB_{day:%Y-%m-%d}.json"

    def load_day(self, day: date) -> list[dict[str, Any]]:
        path = self.path(day)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

        result: list[dict[str, Any]] = []
        start = 0
        while True:
            response = requests.get(
                HISTORY_URL,
                params={
                    "date": day.isoformat(),
                    "iss.meta": "off",
                    "history.columns": COLUMNS,
                    "start": start,
                },
                timeout=40,
            )
            response.raise_for_status()
            payload = response.json()
            batch = rows(payload.get("history") or {})
            result.extend(batch)
            cursor = rows(payload.get("history.cursor") or {})
            if not cursor:
                break
            total = int(cursor[0].get("TOTAL") or len(result))
            page_size = int(cursor[0].get("PAGESIZE") or len(batch) or 100)
            start += page_size
            if start >= total or not batch:
                break
            time.sleep(self.pause)

        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result


def clean_price(row: dict[str, Any]) -> float | None:
    for key in ("WAPRICE", "CLOSE", "LEGALCLOSEPRICE", "LASTPRICE"):
        value = safe_float(row.get(key))
        if value and value > 0:
            return value
    return None


def full_price(row: dict[str, Any], slippage_pct: float, selling: bool = False) -> float | None:
    price = clean_price(row)
    face = safe_float(row.get("FACEVALUE"), 1000.0) or 1000.0
    accrued = safe_float(row.get("ACCRUEDINT"), 0.0) or 0.0
    if price is None:
        return None
    clean_rub = face * price / 100.0
    slip = clean_rub * slippage_pct / 100.0
    return clean_rub + accrued - slip if selling else clean_rub + accrued + slip


def effective_yield(row: dict[str, Any]) -> float | None:
    return safe_float(row.get("YIELDTOOFFER")) or safe_float(row.get("YIELD"))


def target_day(row: dict[str, Any], current: date) -> date | None:
    dates: list[date] = []
    for key in ("OFFERDATE", "MATDATE"):
        raw = str(row.get(key) or "")[:10]
        try:
            parsed = parse_day(raw)
            if parsed > current:
                dates.append(parsed)
        except ValueError:
            pass
    return min(dates) if dates else None


def is_ofz(row: dict[str, Any]) -> bool:
    return str(row.get("SECID") or "").upper().startswith("SU")


def ofz_curve(market: list[dict[str, Any]], day: date) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for row in market:
        if not is_ofz(row):
            continue
        expiry = target_day(row, day)
        yield_value = effective_yield(row)
        if expiry and yield_value is not None and yield_value > 0:
            points.append(((expiry - day).days, yield_value))
    return sorted(points)


def interpolate_curve(curve: list[tuple[int, float]], days: int) -> float | None:
    if not curve:
        return None
    if days <= curve[0][0]:
        return curve[0][1]
    if days >= curve[-1][0]:
        return curve[-1][1]
    for left, right in zip(curve, curve[1:]):
        if left[0] <= days <= right[0]:
            if right[0] == left[0]:
                return left[1]
            weight = (days - left[0]) / (right[0] - left[0])
            return left[1] + weight * (right[1] - left[1])
    return None


def prepare_market(market: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    curve = ofz_curve(market, day)
    prepared: list[dict[str, Any]] = []
    for source in market:
        row = dict(source)
        expiry = target_day(row, day)
        ytm = effective_yield(row)
        row["_clean"] = clean_price(row)
        row["_yield"] = ytm
        row["_days"] = (expiry - day).days if expiry else None
        ofz_yield = interpolate_curve(curve, row["_days"]) if row["_days"] else None
        row["_ofz_yield"] = ofz_yield
        row["_spread_bp"] = (ytm - ofz_yield) * 100 if ytm is not None and ofz_yield is not None else None
        prepared.append(row)
    return prepared


def score_candidate(row: dict[str, Any], min_value: float, min_trades: int) -> float | None:
    if is_ofz(row) or str(row.get("FACEUNIT") or "SUR") not in {"SUR", "RUB"}:
        return None
    price = safe_float(row.get("_clean"))
    ytm = safe_float(row.get("_yield"))
    days = int(row.get("_days") or 0)
    value = safe_float(row.get("VALUE"), 0.0) or 0.0
    trades = int(safe_float(row.get("NUMTRADES"), 0.0) or 0)
    spread = safe_float(row.get("_spread_bp"))
    if price is None or ytm is None or not (70 <= price <= 120):
        return None
    if not (30 <= days <= 730) or value < min_value or trades < min_trades:
        return None
    if not (5 <= ytm <= 60):
        return None

    liquidity = min(value / max(min_value, 1.0), 5.0) * 4 + min(trades / max(min_trades, 1), 5.0) * 2
    yield_score = min(max(ytm - 10, 0), 25) * 1.2
    spread_score = 0.0
    if spread is not None:
        if 100 <= spread < 300:
            spread_score = 5
        elif 300 <= spread < 600:
            spread_score = 10
        elif 600 <= spread < 1000:
            spread_score = 2
        elif spread >= 1000:
            spread_score = -15
        elif spread < 0:
            spread_score = -8
    duration_score = 8 if 90 <= days <= 540 else 3
    return round(40 + liquidity + yield_score + spread_score + duration_score, 2)


def select_candidates(
    market: list[dict[str, Any]],
    day: date,
    count: int,
    min_value: float,
    min_trades: int,
    excluded: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = excluded or set()
    ranked: list[dict[str, Any]] = []
    for row in prepare_market(market, day):
        secid = str(row.get("SECID") or "")
        if not secid or secid in excluded:
            continue
        score = score_candidate(row, min_value, min_trades)
        if score is None:
            continue
        item = dict(row)
        item["_score"] = score
        ranked.append(item)
    return sorted(ranked, key=lambda x: (x["_score"], safe_float(x.get("VALUE"), 0.0) or 0.0), reverse=True)[:count]


def buy(
    selected: list[dict[str, Any]],
    cash: float,
    slots: int,
    slippage_pct: float,
    commission_pct: float,
    day: date,
    operations: list[Operation],
) -> tuple[list[Position], float]:
    positions: list[Position] = []
    remaining = cash
    for index, row in enumerate(selected[:slots]):
        remaining_slots = max(1, min(slots - index, len(selected) - index))
        budget = remaining / remaining_slots
        unit = full_price(row, slippage_pct, selling=False)
        if unit is None:
            continue
        unit_with_fee = unit * (1 + commission_pct / 100.0)
        qty = int(budget // unit_with_fee)
        if qty <= 0:
            continue
        amount = qty * unit_with_fee
        secid = str(row.get("SECID"))
        position = Position(
            secid=secid,
            name=str(row.get("SHORTNAME") or secid),
            quantity=qty,
            invested=amount,
            average_full_price=unit_with_fee,
            last_full_price=unit,
            last_clean_price=safe_float(row.get("_clean"), 0.0) or 0.0,
            last_accrued=safe_float(row.get("ACCRUEDINT"), 0.0) or 0.0,
            last_yield=safe_float(row.get("_yield"), 0.0) or 0.0,
            last_spread_bp=safe_float(row.get("_spread_bp")),
        )
        positions.append(position)
        remaining -= amount
        operations.append(Operation(day.isoformat(), "BUY", secid, qty, unit_with_fee, amount, f"Исторический отбор, балл {row['_score']:.1f}"))
    return positions, remaining


def monitor_signal(position: Position, row: dict[str, Any]) -> tuple[str, str]:
    current_clean = safe_float(row.get("_clean"))
    current_spread = safe_float(row.get("_spread_bp"))
    current_yield = safe_float(row.get("_yield"))
    if current_clean is None:
        return "CHECK", "Нет исторической цены"
    reasons: list[str] = []
    soft = 0
    if position.last_clean_price > 0 and (position.last_clean_price - current_clean) / position.last_clean_price >= 0.08:
        soft += 1
        reasons.append("цена упала не менее чем на 8% с прошлого торгового дня")
    if current_spread is not None and position.last_spread_bp is not None and current_spread - position.last_spread_bp >= 300:
        soft += 1
        reasons.append("спред вырос не менее чем на 300 б.п.")
    if current_spread is not None and current_spread >= 1000:
        soft += 2
        reasons.append("спред не менее 1000 б.п.")
    elif current_spread is not None and current_spread >= 600:
        soft += 1
        reasons.append("спред не менее 600 б.п.")
    if current_yield is not None and current_yield >= 50:
        soft += 2
        reasons.append("доходность не менее 50%")
    if soft >= 3:
        return "SELL", "; ".join(reasons)
    if soft >= 1:
        return "WATCH", "; ".join(reasons)
    return "HOLD", "рыночных сигналов ухудшения нет"


def run_backtest(args: argparse.Namespace) -> Path:
    start = parse_day(args.start)
    end = parse_day(args.end)
    if start >= end:
        raise SystemExit("--start должен быть раньше --end")

    project_root = Path(__file__).resolve().parent
    run_id = safe_name(args.name or f"{start}_{end}_{args.amount:.0f}")
    root = project_root / "data" / "backtests" / run_id
    reports = project_root / "reports" / "backtests" / run_id
    root.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    store = HistoricalStore(root)

    config = vars(args).copy()
    config["created_at"] = datetime.now().isoformat(timespec="seconds")
    (root / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    operations: list[Operation] = []
    daily: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    cash = float(args.amount)
    positions: list[Position] = []
    current = start
    last_month: tuple[int, int] | None = None

    while current <= end:
        raw_market = store.load_day(current)
        if not raw_market:
            current += timedelta(days=1)
            continue
        market = prepare_market(raw_market, current)
        by_id = {str(row.get("SECID")): row for row in market}

        if not positions:
            selected = select_candidates(market, current, args.positions, args.min_value, args.min_trades)
            for rank, row in enumerate(selected, 1):
                selections.append({"Дата": current.isoformat(), "Место": rank, "Код": row.get("SECID"), "Название": row.get("SHORTNAME"), "Баллы": row.get("_score"), "Доходность": row.get("_yield"), "Спред, б.п.": row.get("_spread_bp"), "Объём, руб.": row.get("VALUE")})
            positions, cash = buy(selected, cash, args.positions, args.slippage, args.commission, current, operations)
            last_month = (current.year, current.month)

        coupon_cash = 0.0
        sell_ids: set[str] = set()
        market_value = 0.0
        for position in positions:
            row = by_id.get(position.secid)
            if row is None:
                signals.append({"Дата": current.isoformat(), "Код": position.secid, "Сигнал": "CHECK", "Причина": "Бумага отсутствует в итогах торгов"})
                market_value += position.last_full_price * position.quantity
                continue

            accrued = safe_float(row.get("ACCRUEDINT"), 0.0) or 0.0
            if position.last_accrued - accrued > 1.0:
                coupon = (position.last_accrued - accrued) * position.quantity
                cash += coupon
                coupon_cash += coupon
                operations.append(Operation(current.isoformat(), "COUPON_ESTIMATE", position.secid, position.quantity, position.last_accrued - accrued, coupon, "Оценка купона по сбросу НКД"))

            unit = full_price(row, args.slippage, selling=True) or position.last_full_price
            market_value += unit * position.quantity
            signal, reason = monitor_signal(position, row)
            signals.append({"Дата": current.isoformat(), "Код": position.secid, "Сигнал": signal, "Причина": reason, "Цена, %": row.get("_clean"), "Доходность": row.get("_yield"), "Спред, б.п.": row.get("_spread_bp")})
            if signal == "SELL":
                sell_ids.add(position.secid)

            position.last_full_price = unit
            position.last_clean_price = safe_float(row.get("_clean"), position.last_clean_price) or position.last_clean_price
            position.last_accrued = accrued
            position.last_yield = safe_float(row.get("_yield"), position.last_yield) or position.last_yield
            position.last_spread_bp = safe_float(row.get("_spread_bp"), position.last_spread_bp)

        month = (current.year, current.month)
        monthly_day = last_month is not None and month != last_month
        if args.rebalance == "monthly" and monthly_day:
            for position in list(positions):
                if position.secid not in sell_ids:
                    continue
                row = by_id.get(position.secid)
                unit = full_price(row, args.slippage, selling=True) if row else position.last_full_price
                unit = (unit or 0.0) * (1 - args.commission / 100.0)
                amount = unit * position.quantity
                cash += amount
                operations.append(Operation(current.isoformat(), "SELL", position.secid, position.quantity, unit, amount, "Ежемесячная реализация сигнала SELL"))
                positions.remove(position)

            missing = args.positions - len(positions)
            if missing > 0 and cash > 0:
                held = {p.secid for p in positions}
                selected = select_candidates(market, current, missing, args.min_value, args.min_trades, held)
                for rank, row in enumerate(selected, 1):
                    selections.append({"Дата": current.isoformat(), "Место": rank, "Код": row.get("SECID"), "Название": row.get("SHORTNAME"), "Баллы": row.get("_score"), "Доходность": row.get("_yield"), "Спред, б.п.": row.get("_spread_bp"), "Объём, руб.": row.get("VALUE")})
                bought, cash = buy(selected, cash, missing, args.slippage, args.commission, current, operations)
                positions.extend(bought)
            last_month = month

        total = cash + market_value
        daily.append({"Дата": current.isoformat(), "Кэш, руб.": round(cash, 2), "Позиции, руб.": round(market_value, 2), "Портфель, руб.": round(total, 2), "Доходность, %": round((total / args.amount - 1) * 100, 3), "Оценка купонов за день, руб.": round(coupon_cash, 2), "Количество позиций": len(positions)})
        current += timedelta(days=1)

    if not daily:
        raise SystemExit("MOEX не вернула исторические данные за выбранный период")

    daily_df = pd.DataFrame(daily)
    operations_df = pd.DataFrame([asdict(item) for item in operations])
    signals_df = pd.DataFrame(signals)
    selections_df = pd.DataFrame(selections)
    final_value = float(daily_df.iloc[-1]["Портфель, руб."])
    peak = daily_df["Портфель, руб."].cummax()
    drawdown = daily_df["Портфель, руб."] / peak - 1
    summary = pd.DataFrame([{
        "Дата начала": start.isoformat(),
        "Дата конца": end.isoformat(),
        "Начальный капитал, руб.": args.amount,
        "Итоговая стоимость, руб.": round(final_value, 2),
        "Итоговая доходность, %": round((final_value / args.amount - 1) * 100, 3),
        "Максимальная просадка, %": round(float(drawdown.min()) * 100, 3),
        "Операций покупки": int((operations_df.get("action", pd.Series(dtype=str)) == "BUY").sum()),
        "Операций продажи": int((operations_df.get("action", pd.Series(dtype=str)) == "SELL").sum()),
        "Сигналов SELL": int((signals_df.get("Сигнал", pd.Series(dtype=str)) == "SELL").sum()),
        "Режим": "Рыночный исторический бэктест MOEX; без исторических рейтингов, новостей и отчётности",
    }])

    output = reports / "backtest_report.xlsx"
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Сводка", index=False)
        selections_df.to_excel(writer, sheet_name="Исторический отбор", index=False)
        daily_df.to_excel(writer, sheet_name="Динамика", index=False)
        operations_df.to_excel(writer, sheet_name="Операции", index=False)
        signals_df.to_excel(writer, sheet_name="Сигналы", index=False)
        pd.DataFrame([config]).to_excel(writer, sheet_name="Параметры", index=False)

    daily_df.to_csv(root / "daily_values.csv", index=False, encoding="utf-8-sig")
    operations_df.to_csv(root / "operations.csv", index=False, encoding="utf-8-sig")
    signals_df.to_csv(root / "signals.csv", index=False, encoding="utf-8-sig")
    (root / "final_positions.json").write_text(json.dumps([asdict(item) for item in positions], ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Изолированный исторический бэктест облигационного портфеля")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--amount", type=float, default=300000.0)
    parser.add_argument("--positions", type=int, default=5)
    parser.add_argument("--name", help="Имя отдельного запуска бэктеста")
    parser.add_argument("--rebalance", choices=("none", "monthly"), default="monthly")
    parser.add_argument("--min-value", type=float, default=500000.0, help="Минимальный дневной оборот, руб.")
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument("--slippage", type=float, default=0.25, help="Проскальзывание, % от чистой цены")
    parser.add_argument("--commission", type=float, default=0.05, help="Комиссия, %")
    args = parser.parse_args()
    if args.amount <= 0 or args.positions <= 0:
        raise SystemExit("Капитал и количество позиций должны быть положительными")
    run_backtest(args)


if __name__ == "__main__":
    main()
