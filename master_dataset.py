from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


MODULE_SOURCES: dict[str, tuple[str, list[str]]] = {
    "market_search": ("bond_search_*.xlsx", ["Результаты поиска"]),
    "cashflow": ("bond_cashflow_*.xlsx", ["Cashflow", "Денежные потоки", "Исходные данные"]),
    "news": ("bond_news_*.xlsx", ["Новости"]),
    "liquidity": ("bond_purchase_volume_*.xlsx", ["Объем покупки", "Объём покупки"]),
    "ofz_spread": ("bond_ofz_spread_*.xlsx", ["Спред к ОФЗ", "Результаты"]),
    "analysis": ("bond_analysis_*.xlsx", ["Анализ", "Результаты"]),
    "deep_analysis": ("bond_deep_analysis_*.xlsx", ["Глубокий анализ", "Результаты"]),
    "credit": ("bond_credit_analysis_*.xlsx", ["Кредитный анализ"]),
    "decision": ("bond_decisions_*.xlsx", ["Решения"]),
}

SECID_ALIASES = ("Код ценной бумаги", "SECID", "secid")
NAME_ALIASES = ("Полное наименование", "Краткое наименование", "Наименование", "SHORTNAME", "SECNAME")


def latest_file(run_dir: Path, pattern: str) -> Path | None:
    files = [p for p in run_dir.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return clean_value(value.item())
        except Exception:
            pass
    return str(value).strip() if not isinstance(value, str) else value.strip()


def row_to_dict(row: pd.Series) -> dict[str, Any]:
    return {str(column): clean_value(value) for column, value in row.items() if clean_value(value) is not None}


def find_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    for name in aliases:
        if name in frame.columns:
            return name
    lowered = {str(column).strip().lower(): str(column) for column in frame.columns}
    for name in aliases:
        found = lowered.get(name.strip().lower())
        if found:
            return found
    return None


def read_module_frame(path: Path, preferred_sheets: list[str]) -> pd.DataFrame:
    book = pd.ExcelFile(path)
    sheet = next((name for name in preferred_sheets if name in book.sheet_names), book.sheet_names[0])
    return pd.read_excel(path, sheet_name=sheet)


def first(raw: dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        value = raw.get(alias)
        if value not in (None, ""):
            return value
    lowered = {str(key).strip().lower(): value for key, value in raw.items()}
    for alias in aliases:
        value = lowered.get(alias.strip().lower())
        if value not in (None, ""):
            return value
    return None


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value).replace(" ", "").replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def as_bool_text(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"да", "yes", "true", "1", "y"}:
        return True
    if text in {"нет", "no", "false", "0", "n"}:
        return False
    return None


def normalized_blocks(raw_modules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    market = raw_modules.get("market_search", {})
    cashflow = raw_modules.get("cashflow", {})
    news = raw_modules.get("news", {})
    liquidity = raw_modules.get("liquidity", {})
    ofz = raw_modules.get("ofz_spread", {})
    analysis = raw_modules.get("analysis", {})
    deep = raw_modules.get("deep_analysis", {})
    credit = raw_modules.get("credit", {})
    decision = raw_modules.get("decision", {})

    return {
        "market": {
            "yield": as_float(first(market, "Доходность", "Доходность, %", "YIELD")),
            "price": as_float(first(market, "Цена, %", "Цена", "Цена, % от номинала")),
            "duration_months": as_float(first(market, "Дюрация, месяцев", "Дюрация, мес.")),
            "duration_days": as_float(first(market, "Дюрация, дней", "DURATION")),
            "maturity_date": first(market, "Дата погашения", "MATDATE"),
            "face_value": as_float(first(market, "Номинал", "FACEVALUE")),
            "volume_15d": as_float(first(market, "Объем за 15 дней, шт.", "Объем торгов за 15 дней", "Объём за 15 дней, шт.")),
            "min_daily_volume": as_float(first(market, "Минимальный дневной объем, шт.", "Минимальный дневной объём, шт.")),
            "trades_15d": as_float(first(market, "Количество сделок за 15 дней", "Сделок за 15 дней")),
            "qualified_only": as_bool_text(first(market, "Для квалифицированных инвесторов", "ISQUALIFIEDINVESTORS")),
        },
        "cashflow": {
            "completeness": first(cashflow, "Полнота cashflow", "Полнота денежных потоков"),
            "future_coupons": as_float(first(cashflow, "Будущих купонов", "Количество будущих купонов")),
            "unknown_coupons": as_float(first(cashflow, "Неизвестных будущих купонов", "Неизвестных купонов")),
            "next_coupon_date": first(cashflow, "Ближайший купон", "Дата ближайшего купона", "Ближайшая дата купона"),
            "next_coupon_amount": as_float(first(cashflow, "Сумма ближайшего купона", "Ближайший купон, руб.")),
            "next_offer_date": first(cashflow, "Ближайшая оферта", "Дата ближайшей оферты"),
        },
        "news": {
            "files": as_float(first(news, "Новостных файлов", "Количество новостей")),
            "completeness": first(news, "Полнота новостей"),
            "negative": first(news, "Негативные события"),
            "positive": first(news, "Позитивные события"),
            "critical_stop": as_bool_text(first(news, "Критический новостной стоп")),
        },
        "liquidity": {
            "bid": as_float(first(liquidity, "Bid", "BID")),
            "offer": as_float(first(liquidity, "Offer", "OFFER", "Ask")),
            "spread_percent": as_float(first(liquidity, "Bid/Ask спред, %", "Спред Bid/Ask, %", "Спред, %")),
            "max_purchase_rub": as_float(first(liquidity, "Максимум к покупке, руб.", "Максимальная сумма покупки, руб.")),
            "orderbook_offer_rub": as_float(first(liquidity, "Объём предложения в стакане, руб.", "Объем предложения в стакане, руб.")),
            "quality": first(liquidity, "Качество данных ликвидности", "Ликвидность покупки", "Ликвидность"),
        },
        "ofz_spread": {
            "ofz_yield": as_float(first(ofz, "Доходность ОФЗ, %", "Доходность сопоставимой ОФЗ", "Доходность ОФЗ")),
            "spread_bp": as_float(first(ofz, "Спред, б.п.", "Спред к ОФЗ, б.п.")),
            "spread_percent": as_float(first(ofz, "Спред, %", "Спред к ОФЗ, %")),
            "risk_class": first(ofz, "Оценка спреда", "Класс спреда", "Интерпретация"),
        },
        "analysis": {
            "score": as_float(first(analysis, "Оценка", "Итоговый балл", "Баллы", "Score")),
            "recommendation": first(analysis, "Рекомендация", "Решение", "Итог"),
        },
        "deep_analysis": {
            "score": as_float(first(deep, "Итоговый балл", "Оценка", "Баллы", "Score")),
            "recommendation": first(deep, "Рекомендация", "Решение", "Итог"),
        },
        "credit": {
            "rating": first(credit, "Рейтинг", "Кредитный рейтинг"),
            "agency": first(credit, "Рейтинговое агентство", "Агентство"),
            "score": as_float(first(credit, "Кредитный балл", "Итоговый кредитный балл", "Оценка кредитного риска")),
            "missing_data": first(credit, "Недостающие данные"),
        },
        "decision": {
            "score": as_float(first(decision, "Финальный балл", "Итоговый балл", "Оценка")),
            "status": first(decision, "Финальное решение", "Решение"),
            "admitted": as_bool_text(first(decision, "Допущена в портфель")),
            "max_share_percent": as_float(first(decision, "Максимальная доля, %", "Максимальная доля")),
            "reasons": first(decision, "Причины"),
            "blockers": first(decision, "Блокеры"),
            "completeness": first(decision, "Полнота оценки"),
        },
    }


def read_latest_trace(run_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    path = run_dir / "decisions" / "module_results.jsonl"
    latest: dict[str, dict[str, dict[str, Any]]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        secid = str(event.get("secid") or "").strip()
        module = str(event.get("module") or "").strip()
        if secid and module:
            latest.setdefault(secid, {})[module] = event
    return latest


def build_master_dataset(run_dir: Path, output: Path | None = None) -> Path:
    run_dir = run_dir.expanduser().resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Папка анализа не найдена: {run_dir}")

    bonds: dict[str, dict[str, Any]] = {}
    source_files: dict[str, str] = {}

    for module, (pattern, sheets) in MODULE_SOURCES.items():
        source = latest_file(run_dir, pattern)
        if source is None:
            continue
        source_files[module] = source.name
        try:
            frame = read_module_frame(source, sheets)
        except Exception as exc:
            source_files[module] = f"{source.name} [ошибка чтения: {exc}]"
            continue
        secid_column = find_column(frame, SECID_ALIASES)
        if secid_column is None:
            continue
        name_column = find_column(frame, NAME_ALIASES)
        for _, row in frame.iterrows():
            secid = str(row.get(secid_column) or "").strip()
            if not secid.startswith("RU") or len(secid) != 12:
                continue
            item = bonds.setdefault(secid, {"secid": secid, "name": "", "raw": {}, "modules": {}})
            if name_column and not item["name"]:
                value = clean_value(row.get(name_column))
                if value:
                    item["name"] = str(value)
            item["raw"][module] = row_to_dict(row)

    trace = read_latest_trace(run_dir)
    for secid, modules in trace.items():
        item = bonds.setdefault(secid, {"secid": secid, "name": "", "raw": {}, "modules": {}})
        item["modules"] = modules

    for item in bonds.values():
        if not item["name"]:
            for raw in item["raw"].values():
                name = first(raw, *NAME_ALIASES)
                if name:
                    item["name"] = str(name)
                    break
        item.update(normalized_blocks(item["raw"]))

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": run_dir.name,
        "run_date": run_dir.name.replace("bond_", "").replace("_", "-"),
        "source_files": source_files,
        "bond_count": len(bonds),
        "bonds": sorted(bonds.values(), key=lambda item: (item.get("name") or "", item["secid"])),
    }

    target = output or run_dir / "decisions" / "bonds_master.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return target
