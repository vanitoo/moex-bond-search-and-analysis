from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

from pipeline_common import latest, safe_float
from moex_bond_search_and_analysis.rating_signal import build_rating_signal, load_rating_events

MOEX = "https://iss.moex.com/iss"
RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]
HARD_SELL_DECISIONS = {"Не покупать"}
REVIEW_DECISIONS = {"Недостаточно данных", "Рассматривать", "Требуется ручная проверка"}


def normalize(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def normalize_rating(value: Any) -> str:
    raw = str(value or "").upper().replace("(RU)", "").replace("RU", "")
    text = re.sub(r"[^A-Z+\-]", "", raw)
    for item in sorted(RATING_ORDER, key=len, reverse=True):
        if item in text:
            return item
    return ""


def rating_drop(previous: str, current: str) -> int:
    if previous not in RATING_ORDER or current not in RATING_ORDER:
        return 0
    return max(0, RATING_ORDER.index(previous) - RATING_ORDER.index(current))


def safe_name(value: str) -> str:
    result = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", value.strip())
    if not result:
        raise ValueError("Пустое имя портфеля")
    return result


def load_portfolio(name: str, portfolio_dir: Path) -> dict[str, Any]:
    path = portfolio_dir / f"{safe_name(name)}.json"
    if not path.exists():
        raise FileNotFoundError(f"Портфель не найден: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, row)) for row in section.get("data") or []]


def fetch_market(secid: str) -> dict[str, Any]:
    time.sleep(0.2)
    response = requests.get(
        f"{MOEX}/engines/stock/markets/bonds/securities/{quote(secid)}.json",
        params={
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,FACEVALUE,ACCRUEDINT",
            "marketdata.columns": "SECID,LAST,MARKETPRICE,LCURRENTPRICE,BID,OFFER,YIELD,SPREAD,UPDATETIME",
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    securities = rows(payload, "securities")
    marketdata = rows(payload, "marketdata")
    md = next((item for item in marketdata if str(item.get("SECID")) == secid), marketdata[0] if marketdata else {})
    sec = next((item for item in securities if str(item.get("SECID")) == secid), securities[0] if securities else {})
    face = safe_float(sec.get("FACEVALUE"), 1000.0) or 1000.0
    accrued = safe_float(sec.get("ACCRUEDINT"), 0.0) or 0.0
    price_pct = safe_float(md.get("BID") or md.get("LAST") or md.get("MARKETPRICE") or md.get("LCURRENTPRICE"))
    if price_pct is None or price_pct <= 0:
        raise ValueError("MOEX не вернула цену продажи/BID")
    return {
        "Цена, %": price_pct,
        "Bid, %": safe_float(md.get("BID")),
        "Offer, %": safe_float(md.get("OFFER")),
        "Доходность рынка, %": safe_float(md.get("YIELD")),
        "Биржевой спред, %": safe_float(md.get("SPREAD")),
        "Стоимость одной бумаги, руб.": face * price_pct / 100.0 + accrued,
        "Время рынка": md.get("UPDATETIME") or "",
    }


def load_decisions(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = latest(run_dir, "bond_decisions_*.xlsx", required=False)
    if path is None:
        return {}
    df = pd.read_excel(path, sheet_name="Решения")
    return {
        str(row.get("Код ценной бумаги") or "").strip(): row.to_dict()
        for _, row in df.iterrows()
        if str(row.get("Код ценной бумаги") or "").strip()
    }


def load_ofz_spreads(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = latest(run_dir, "bond_ofz_spread_*.xlsx", required=False)
    if path is None:
        return {}
    df = pd.read_excel(path, sheet_name="Спред к ОФЗ")
    return {
        str(row.get("Код ценной бумаги") or "").strip(): row.to_dict()
        for _, row in df.iterrows()
        if str(row.get("Код ценной бумаги") or "").strip()
    }


def latest_previous_snapshot(history_dir: Path, portfolio_name: str) -> dict[str, dict[str, Any]]:
    files = sorted(history_dir.glob(f"{safe_name(portfolio_name)}_*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        return {}
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    return {str(row.get("Код ценной бумаги")): row for row in payload.get("positions", [])}


def classify_action(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    soft = 0
    decision = str(current.get("Финальное решение") or "")
    rating = normalize_rating(current.get("Рейтинг"))
    blockers = normalize(current.get("Блокеры"))
    hard_stop = normalize(current.get("Жёсткий стоп")) in {"да", "true", "1"}
    rating_action = str(current.get("Последнее рейтинговое действие") or "").upper()
    rating_forecast = normalize(current.get("Прогноз рейтинга"))

    if decision in HARD_SELL_DECISIONS:
        reasons.append(f"Финальное решение: {decision}")
    if hard_stop:
        reasons.append("Сработал жёсткий стоп")
    if rating in {"D", "C", "CC", "CCC"}:
        reasons.append(f"Критический рейтинг {rating}")
    if any(marker in blockers for marker in ("дефолт", "просроч", "банкрот", "не выплачен", "критический рейтинг")):
        reasons.append("Критический блокер/событие")
    if reasons:
        return "ПРОДАТЬ", reasons

    if rating_action == "ПОНИЖЕН":
        soft += 2
        reasons.append("Свежий рейтинговый downgrade")
    elif rating_action == "ОТОЗВАН":
        soft += 1
        reasons.append("Рейтинг отозван: требуется перепроверка причины")
    if "негатив" in rating_forecast or "развива" in rating_forecast:
        soft += 1
        reasons.append(f"Негативный рейтинговый прогноз: {current.get('Прогноз рейтинга')}")

    if decision in REVIEW_DECISIONS:
        soft += 1
        reasons.append(f"Решение ухудшилось до «{decision}»")
    if not decision:
        soft += 1
        reasons.append("Бумага отсутствует в свежем решении pipeline")

    if previous:
        score = safe_float(current.get("Финальный балл"))
        previous_score = safe_float(previous.get("Финальный балл"))
        if score is not None and previous_score is not None and previous_score - score >= 15:
            soft += 1
            reasons.append(f"Баллы снизились на {previous_score - score:.0f}")

        previous_rating = normalize_rating(previous.get("Рейтинг"))
        downgrade = rating_drop(previous_rating, rating)
        if downgrade >= 2:
            soft += 2
            reasons.append(f"Рейтинг упал на {downgrade} ступени: {previous_rating} → {rating}")
        elif downgrade == 1:
            soft += 1
            reasons.append(f"Рейтинг снижен: {previous_rating} → {rating}")

        spread = safe_float(current.get("Спред к ОФЗ, б.п."))
        previous_spread = safe_float(previous.get("Спред к ОФЗ, б.п."))
        if spread is not None and previous_spread is not None and spread - previous_spread >= 300:
            soft += 1
            reasons.append(f"Спред к ОФЗ вырос на {spread - previous_spread:.0f} б.п.")

        price = safe_float(current.get("Цена, %"))
        previous_price = safe_float(previous.get("Цена, %"))
        if price is not None and previous_price and (previous_price - price) / previous_price >= 0.08:
            soft += 1
            reasons.append(f"Цена упала на {(previous_price - price) / previous_price:.1%}")

    spread = safe_float(current.get("Спред к ОФЗ, б.п."))
    if spread is not None and spread >= 1000:
        soft += 2
        reasons.append(f"Экстремальный спред к ОФЗ: {spread:.0f} б.п.")
    elif spread is not None and spread >= 600:
        soft += 1
        reasons.append(f"Высокий спред к ОФЗ: {spread:.0f} б.п.")

    if soft >= 3:
        return "СОКРАТИТЬ НА 50%", reasons
    if soft >= 1:
        return "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ", reasons
    return "ДЕРЖАТЬ", ["Критических ухудшений не обнаружено"]


def build_daily_rows(
    portfolio: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
    spreads: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    rating_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or "").strip()
        current: dict[str, Any] = {
            "Код ценной бумаги": secid,
            "Название": position.get("name") or secid,
            "Количество": int(position.get("quantity") or 0),
            "Вложено, руб.": safe_float(position.get("invested"), 0.0) or 0.0,
            "Дата мониторинга": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            current.update(fetch_market(secid))
            current["Рыночная стоимость, руб."] = round(
                (safe_float(current.get("Стоимость одной бумаги, руб."), 0.0) or 0.0)
                * current["Количество"],
                2,
            )
            current["Нереализованный результат, руб."] = round(
                current["Рыночная стоимость, руб."] - current["Вложено, руб."], 2
            )
            current["Качество рыночных данных"] = "ИЗВЕСТНО"
        except Exception as exc:
            current["Качество рыночных данных"] = "ОШИБКА"
            current["Ошибка рынка"] = str(exc)

        decision = decisions.get(secid, {})
        signal = build_rating_signal(rating_events, secid)
        current.update({
            "Финальное решение": decision.get("Финальное решение") or "",
            "Финальный балл": decision.get("Финальный балл"),
            "Рейтинг": decision.get("Рейтинг") or signal.latest_rating or position.get("rating") or "",
            "Прогноз": decision.get("Прогноз") or "",
            "Прогноз рейтинга": decision.get("Прогноз рейтинга") or signal.latest_forecast or "",
            "Последнее рейтинговое действие": decision.get("Последнее рейтинговое действие") or signal.latest_action or "",
            "Рейтинговое агентство": decision.get("Рейтинговое агентство") or signal.latest_agency or "",
            "Дата рейтингового события": decision.get("Дата рейтингового события") or signal.latest_event_date or "",
            "Корректировка за рейтинг": decision.get("Корректировка за рейтинг") if decision else signal.bonus - signal.penalty,
            "Уверенность": decision.get("Уверенность") or "",
            "Жёсткий стоп": decision.get("Жёсткий стоп") or ("ДА" if signal.hard_stop else ""),
            "Блокеры": decision.get("Блокеры") or "; ".join(signal.reasons) or "",
            "Ручные проверки": decision.get("Ручные проверки") or "",
        })
        spread = spreads.get(secid, {})
        current["Спред к ОФЗ, б.п."] = spread.get("Спред к ОФЗ, б.п.")
        current["Качество данных спреда"] = spread.get("Качество данных спреда") or "НЕИЗВЕСТНО"

        action, reasons = classify_action(current, previous.get(secid))
        current["Рекомендация мониторинга"] = action
        current["Причины рекомендации"] = "; ".join(reasons)
        result.append(current)
    return result


def write_daily_report(name: str, rows_data: list[dict[str, Any]], history_dir: Path, report_dir: Path) -> tuple[Path, Path, Path]:
    history_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = f"{safe_name(name)}_{stamp}"
    json_path = history_dir / f"{base}.json"
    xlsx_path = report_dir / f"portfolio_monitor_{base}.xlsx"
    html_path = report_dir / f"portfolio_monitor_{base}.html"
    payload = {"portfolio": name, "created_at": datetime.now().isoformat(timespec="seconds"), "positions": rows_data}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    df = pd.DataFrame(rows_data)
    summary = df["Рекомендация мониторинга"].value_counts().rename_axis("Рекомендация").reset_index(name="Количество") if not df.empty else pd.DataFrame()
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Мониторинг", index=False)
        summary.to_excel(writer, sheet_name="Сводка", index=False)
    html_path.write_text(
        "<meta charset='utf-8'><h1>Мониторинг портфеля: " + name + "</h1>" + summary.to_html(index=False) + df.to_html(index=False),
        encoding="utf-8",
    )
    return json_path, xlsx_path, html_path


def daily_cmd(args: argparse.Namespace) -> list[dict[str, Any]]:
    portfolio_dir = Path(args.portfolio_dir)
    history_dir = Path(args.history_dir)
    report_dir = Path(args.report_dir)
    run_dir = Path(args.run_dir)
    portfolio = load_portfolio(args.name, portfolio_dir)
    previous = latest_previous_snapshot(history_dir, args.name)
    rating_events = load_rating_events(run_dir)
    rows_data = build_daily_rows(
        portfolio,
        load_decisions(run_dir),
        load_ofz_spreads(run_dir),
        previous,
        rating_events,
    )
    paths = write_daily_report(args.name, rows_data, history_dir, report_dir)
    for row in rows_data:
        print(f"{row['Код ценной бумаги']}: {row['Рекомендация мониторинга']} — {row['Причины рекомендации']}")
    print("JSON:", paths[0])
    print("XLSX:", paths[1])
    print("HTML:", paths[2])
    return rows_data


def monthly_cmd(args: argparse.Namespace) -> None:
    history_dir = Path(args.history_dir)
    files = sorted(history_dir.glob(f"{safe_name(args.name)}_*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        raise FileNotFoundError("Нет истории мониторинга")
    snapshots = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("positions", []):
            item = dict(row)
            item["Снимок"] = payload.get("created_at")
            snapshots.append(item)
    df = pd.DataFrame(snapshots)
    report_dir = Path(args.report_dir); report_dir.mkdir(parents=True, exist_ok=True)
    output = report_dir / f"portfolio_monthly_{safe_name(args.name)}_{datetime.now():%Y-%m}.xlsx"
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="История", index=False)
        if not df.empty and "Рекомендация мониторинга" in df.columns:
            pivot = df.groupby(["Код ценной бумаги", "Рекомендация мониторинга"]).size().reset_index(name="Количество")
            pivot.to_excel(writer, sheet_name="Сводка", index=False)
    print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Мониторинг портфеля облигаций")
    sub = parser.add_subparsers(dest="command", required=True)

    daily = sub.add_parser("daily")
    daily.add_argument("--name", required=True)
    daily.add_argument("--run-dir", required=True)
    daily.add_argument("--portfolio-dir", default="data/virtual_portfolios")
    daily.add_argument("--history-dir", default="data/portfolio_monitor_history")
    daily.add_argument("--report-dir", default="reports")
    daily.set_defaults(func=daily_cmd)

    monthly = sub.add_parser("monthly")
    monthly.add_argument("--name", required=True)
    monthly.add_argument("--history-dir", default="data/portfolio_monitor_history")
    monthly.add_argument("--report-dir", default="reports")
    monthly.set_defaults(func=monthly_cmd)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
