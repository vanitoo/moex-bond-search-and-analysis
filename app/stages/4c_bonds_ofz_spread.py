from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from pipeline_common import dated_name, latest, safe_float

MOEX_BASE = "https://iss.moex.com/iss"
OFZ_BOARD = "TQOB"
REQUEST_TIMEOUT = 30
REQUEST_ATTEMPTS = 3
RETRY_DELAY = 1.5


def rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, row)) for row in section.get("data") or []]


def request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX ISS вернул неожиданный формат данных")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < REQUEST_ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"MOEX ISS недоступен после {REQUEST_ATTEMPTS} попыток: {last_error}") from last_error


def duration_months(value: Any) -> float | None:
    days = safe_float(value)
    if days is None or days <= 0:
        return None
    return days / 30.4375


def market_yield(row: dict[str, Any]) -> float | None:
    for column in ("YIELD", "YIELDATWAP", "YIELDCLOSE"):
        value = safe_float(row.get(column))
        if value is not None and value > 0:
            return value
    return None


def fetch_ofz_curve() -> pd.DataFrame:
    url = f"{MOEX_BASE}/engines/stock/markets/bonds/boards/{OFZ_BOARD}/securities.json"
    payload = request_json(
        url,
        {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,SHORTNAME,MATDATE",
            "marketdata.columns": "SECID,YIELD,YIELDATWAP,YIELDCLOSE,DURATION,UPDATETIME",
        },
    )
    security_rows = {str(row.get("SECID")): row for row in rows(payload, "securities")}
    result: list[dict[str, Any]] = []
    for md in rows(payload, "marketdata"):
        secid = str(md.get("SECID") or "").strip()
        ytm = market_yield(md)
        months = duration_months(md.get("DURATION"))
        if not secid or ytm is None or months is None:
            continue
        security = security_rows.get(secid, {})
        result.append(
            {
                "SECID ОФЗ": secid,
                "Название ОФЗ": security.get("SHORTNAME") or secid,
                "Погашение ОФЗ": security.get("MATDATE") or "",
                "Дюрация ОФЗ, месяцев": months,
                "Доходность ОФЗ, %": ytm,
                "Время данных ОФЗ": md.get("UPDATETIME") or "",
            }
        )
    curve = pd.DataFrame(result)
    if curve.empty:
        raise RuntimeError("MOEX ISS не вернул пригодные данные по ОФЗ")
    return curve.sort_values("Дюрация ОФЗ, месяцев").reset_index(drop=True)


def interpolate_ofz_yield(curve: pd.DataFrame, target_months: float) -> dict[str, Any]:
    if target_months <= 0:
        raise ValueError("Дюрация корпоративной облигации должна быть положительной")

    lower = curve[curve["Дюрация ОФЗ, месяцев"] <= target_months].tail(1)
    upper = curve[curve["Дюрация ОФЗ, месяцев"] >= target_months].head(1)

    if lower.empty:
        row = upper.iloc[0]
        return {
            "Доходность сопоставимой ОФЗ, %": row["Доходность ОФЗ, %"],
            "ОФЗ сравнения": row["SECID ОФЗ"],
            "Метод сравнения с ОФЗ": "Ближайшая более длинная ОФЗ",
        }
    if upper.empty:
        row = lower.iloc[0]
        return {
            "Доходность сопоставимой ОФЗ, %": row["Доходность ОФЗ, %"],
            "ОФЗ сравнения": row["SECID ОФЗ"],
            "Метод сравнения с ОФЗ": "Ближайшая более короткая ОФЗ",
        }

    low = lower.iloc[0]
    high = upper.iloc[0]
    low_duration = float(low["Дюрация ОФЗ, месяцев"])
    high_duration = float(high["Дюрация ОФЗ, месяцев"])
    low_yield = float(low["Доходность ОФЗ, %"])
    high_yield = float(high["Доходность ОФЗ, %"])

    if high_duration == low_duration:
        interpolated = low_yield
        method = "Точное совпадение дюрации"
        comparison = str(low["SECID ОФЗ"])
    else:
        weight = (target_months - low_duration) / (high_duration - low_duration)
        interpolated = low_yield + weight * (high_yield - low_yield)
        method = "Линейная интерполяция по дюрации"
        comparison = f"{low['SECID ОФЗ']} / {high['SECID ОФЗ']}"

    return {
        "Доходность сопоставимой ОФЗ, %": interpolated,
        "ОФЗ сравнения": comparison,
        "Метод сравнения с ОФЗ": method,
    }


def classify_spread(spread_bp: float) -> str:
    if spread_bp < 0:
        return "Доходность ниже ОФЗ"
    if spread_bp < 100:
        return "Низкая премия"
    if spread_bp < 300:
        return "Умеренная премия"
    if spread_bp < 600:
        return "Повышенная премия"
    if spread_bp < 1000:
        return "Высокая премия / повышенный риск"
    return "Экстремальная премия / вероятный высокий риск"


def calculate_spreads(bonds: pd.DataFrame, curve: pd.DataFrame) -> pd.DataFrame:
    required = {"Код ценной бумаги", "Доходность", "Дюрация, месяцев"}
    missing = required.difference(bonds.columns)
    if missing:
        raise ValueError("Во входном файле отсутствуют колонки: " + ", ".join(sorted(missing)))

    result: list[dict[str, Any]] = []
    for _, row in bonds.iterrows():
        secid = str(row.get("Код ценной бумаги") or "").strip()
        corporate_yield = safe_float(row.get("Доходность"))
        corporate_duration = safe_float(row.get("Дюрация, месяцев"))
        base = {
            "Код ценной бумаги": secid,
            "Доходность облигации, %": corporate_yield,
            "Дюрация облигации, месяцев": corporate_duration,
            "Актуально на": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if corporate_yield is None or corporate_duration is None or corporate_duration <= 0:
            result.append(
                {
                    **base,
                    "Качество данных спреда": "НЕИЗВЕСТНО",
                    "Причина качества спреда": "Нет доходности или дюрации корпоративной облигации",
                }
            )
            continue
        try:
            benchmark = interpolate_ofz_yield(curve, corporate_duration)
            ofz_yield = float(benchmark["Доходность сопоставимой ОФЗ, %"])
            spread_pp = corporate_yield - ofz_yield
            spread_bp = spread_pp * 100.0
            result.append(
                {
                    **base,
                    **benchmark,
                    "Спред к ОФЗ, п.п.": round(spread_pp, 4),
                    "Спред к ОФЗ, б.п.": round(spread_bp, 1),
                    "Оценка премии к ОФЗ": classify_spread(spread_bp),
                    "Качество данных спреда": "ИЗВЕСТНО",
                    "Причина качества спреда": "Доходность ОФЗ рассчитана по кривой дюраций TQOB",
                }
            )
        except Exception as exc:
            result.append(
                {
                    **base,
                    "Качество данных спреда": "ОШИБКА",
                    "Причина качества спреда": str(exc),
                }
            )
    return pd.DataFrame(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Расчёт спреда доходности корпоративных облигаций к ОФЗ")
    parser.add_argument("--input", help="Файл bond_search_YYYY-MM-DD.xlsx")
    parser.add_argument("--output", help="Выходной XLSX")
    args = parser.parse_args()

    source = Path(args.input) if args.input else latest(Path("."), "bond_search_*.xlsx")
    bonds = pd.read_excel(source, sheet_name="Результаты поиска")
    curve = fetch_ofz_curve()
    spread = calculate_spreads(bonds, curve)

    output = Path(args.output or dated_name("bond_ofz_spread", "xlsx"))
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        spread.to_excel(writer, sheet_name="Спред к ОФЗ", index=False)
        curve.to_excel(writer, sheet_name="Кривая ОФЗ", index=False)
        pd.DataFrame(
            {
                "Параметр": ["Метод", "Доска ОФЗ", "Формула"],
                "Значение": [
                    "Линейная интерполяция доходности ОФЗ по дюрации",
                    OFZ_BOARD,
                    "Спред, б.п. = (доходность облигации − доходность сопоставимой ОФЗ) × 100",
                ],
            }
        ).to_excel(writer, sheet_name="Методика", index=False)
    print(f"Получено точек кривой ОФЗ: {len(curve)}")
    print(output)


if __name__ == "__main__":
    main()
