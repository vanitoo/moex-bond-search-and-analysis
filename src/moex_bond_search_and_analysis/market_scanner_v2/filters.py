from __future__ import annotations

from typing import Any

import pandas as pd

from .models import MIN_HISTORY_SESSIONS, ScannerConfig
from .moex_client import safe_float


def choose_best_board(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["_turnover"] = pd.to_numeric(frame.get("VALTODAY"), errors="coerce").fillna(0)
    frame["_price_sort"] = pd.to_numeric(frame.get("OFFER"), errors="coerce").fillna(
        pd.to_numeric(frame.get("LAST"), errors="coerce")
    ).fillna(0)
    return (
        frame.sort_values(["SECID", "_turnover", "_price_sort"], ascending=[True, False, False])
        .drop_duplicates("SECID")
        .drop(columns=["_turnover", "_price_sort"])
    )


def local_filter(frame: pd.DataFrame, config: ScannerConfig) -> pd.DataFrame:
    frame = choose_best_board(frame)
    for column in ("YIELD", "YIELDATWAP", "YIELDCLOSE", "OFFER", "LAST", "MARKETPRICE", "LCURRENTPRICE", "DURATION"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["_yield"] = frame.get("YIELD").fillna(frame.get("YIELDATWAP")).fillna(frame.get("YIELDCLOSE"))
    frame["_price"] = frame.get("OFFER").fillna(frame.get("LAST")).fillna(frame.get("MARKETPRICE")).fillna(frame.get("LCURRENTPRICE"))
    frame["_duration_months"] = frame.get("DURATION") / 30.4375
    mask = (
        frame["SECID"].astype(str).str.fullmatch(r"RU[A-Z0-9]{10}", na=False)
        & frame["_yield"].between(config.yield_more, config.yield_less, inclusive="both")
        & frame["_price"].between(config.price_more, config.price_less, inclusive="both")
        & frame["_duration_months"].between(config.duration_more, config.duration_less, inclusive="both")
    )
    return frame.loc[mask].copy()


def output_row(row: dict[str, Any]) -> dict[str, Any]:
    duration_days = safe_float(row.get("DURATION"))
    yield_value = safe_float(row.get("YIELD")) or safe_float(row.get("YIELDATWAP")) or safe_float(row.get("YIELDCLOSE"))
    price = safe_float(row.get("OFFER")) or safe_float(row.get("LAST")) or safe_float(row.get("MARKETPRICE")) or safe_float(row.get("LCURRENTPRICE"))
    qualified_raw = str(row.get("ISQUALIFIEDINVESTORS") or "0").upper()
    return {
        "Код ценной бумаги": row.get("SECID"),
        "Краткое наименование": row.get("SHORTNAME") or "",
        "Полное наименование": row.get("SECNAME") or row.get("SHORTNAME") or "",
        "Режим торгов": row.get("BOARDID") or "",
        "Доходность": yield_value,
        "Цена, %": price,
        "Цена": price,
        "Дюрация, месяцев": round(duration_days / 30.4375, 2) if duration_days else None,
        "Дюрация, дней": duration_days,
        "Дата погашения": row.get("MATDATE") or "",
        "Номинал": safe_float(row.get("FACEVALUE")),
        "Торговых дней": row.get("Торговых дней", 0),
        "История достаточна": row.get("История достаточна", "НЕТ"),
        "Объем торгов за 15 дней": row.get("Объем за 15 дней, шт.", 0),
        "Объем за 15 дней, шт.": row.get("Объем за 15 дней, шт.", 0),
        "Минимальный дневной объем, шт.": row.get("Минимальный дневной объем, шт.", 0),
        "Количество сделок за 15 дней": row.get("Сделок за 15 дней", 0),
        "Для квалифицированных инвесторов": "ДА" if qualified_raw in {"1", "Y", "YES", "TRUE", "ДА"} else "НЕТ",
        "Будущих купонов": row.get("Будущих купонов", 0),
        "Неизвестных будущих купонов": row.get("Неизвестных будущих купонов", 0),
        "Купоны известны": row.get("Купоны известны", "НЕТ"),
        "Сканер": "V2",
    }


def split_accepted_rejected(all_rows: pd.DataFrame, config: ScannerConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if all_rows.empty:
        return all_rows.copy(), pd.DataFrame()
    rejected: list[dict[str, Any]] = []
    for _, row in all_rows.iterrows():
        reasons: list[str] = []
        if row["История достаточна"] != "ДА":
            reasons.append(f"меньше {MIN_HISTORY_SESSIONS} торговых дней")
        if safe_float(row["Минимальный дневной объем, шт."]) is None or float(row["Минимальный дневной объем, шт."]) < config.volume_more:
            reasons.append("минимальный дневной объём ниже порога")
        if safe_float(row["Объем за 15 дней, шт."]) is None or float(row["Объем за 15 дней, шт."]) < config.bond_volume_more:
            reasons.append("суммарный объём ниже порога")
        if config.require_known_coupons and row["Купоны известны"] != "ДА":
            reasons.append("есть неизвестные будущие купоны или нет будущих купонов")
        if reasons:
            rejected.append({**row.to_dict(), "Причина исключения": "; ".join(reasons)})
    rejected_frame = pd.DataFrame(rejected)
    rejected_ids = set(rejected_frame.get("Код ценной бумаги", pd.Series(dtype=str)))
    accepted = all_rows[~all_rows["Код ценной бумаги"].isin(rejected_ids)]
    accepted = accepted.drop_duplicates("Код ценной бумаги").sort_values(
        ["Доходность", "Объем за 15 дней, шт."], ascending=[False, False]
    )
    return accepted, rejected_frame
