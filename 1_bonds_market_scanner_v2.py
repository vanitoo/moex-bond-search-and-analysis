# 🔴 ЧТО ДЕЛАЕТ МОДУЛЬ: пакетно загружает рынок облигаций MOEX, фильтрует данные локально,
# использует дисковый кэш и ограниченный параллелизм для проверки оборотов и cashflow.
# Это экспериментальная версия первого этапа. V1 оставлен для сравнения результатов.

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

MOEX = "https://iss.moex.com/iss"
DEFAULT_WORKERS = 5
DEFAULT_CACHE_HOURS = 12
HISTORY_DAYS = 15
_thread_local = threading.local()


def session() -> requests.Session:
    current = getattr(_thread_local, "session", None)
    if current is None:
        current = requests.Session()
        current.headers.update({"User-Agent": "MOEX-Bond-Lab-market-scanner-v2/1.0"})
        _thread_local.session = current
    return current


def rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, item)) for item in section.get("data") or []]


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def request_json(url: str, params: dict[str, Any] | None = None, attempts: int = 3) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session().get(url, params=params, timeout=35)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX ISS вернул неожиданный формат")
            return payload
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < attempts:
                time.sleep(0.7 * attempt)
    raise RuntimeError(f"Запрос MOEX не выполнен: {error}") from error


def cache_file(cache_dir: Path, name: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{name}.json"


def read_cache(path: Path, max_age_hours: float) -> Any | None:
    if not path.exists() or max_age_hours <= 0:
        return None
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if age > timedelta(hours=max_age_hours):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def fetch_market_batch(cache_dir: Path, cache_hours: float) -> list[dict[str, Any]]:
    path = cache_file(cache_dir, "market_snapshot")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, list) and cached:
        print(f"Кэш рынка: {len(cached)} строк")
        return cached

    url = f"{MOEX}/engines/stock/markets/bonds/securities.json"
    start = 0
    page_size = 100
    result: list[dict[str, Any]] = []
    while True:
        payload = request_json(
            url,
            {
                "iss.meta": "off",
                "iss.only": "securities,marketdata",
                "start": start,
                "limit": page_size,
                "securities.columns": "SECID,SHORTNAME,SECNAME,BOARDID,FACEVALUE,MATDATE,ISQUALIFIEDINVESTORS,COUPONVALUE,COUPONPERIOD",
                "marketdata.columns": "SECID,BOARDID,LAST,MARKETPRICE,LCURRENTPRICE,OFFER,YIELD,YIELDATWAP,YIELDCLOSE,DURATION,VALTODAY,VOLTODAY,NUMTRADES",
            },
        )
        securities = rows(payload, "securities")
        marketdata = rows(payload, "marketdata")
        if not securities:
            break
        market_by_key = {(str(row.get("SECID")), str(row.get("BOARDID"))): row for row in marketdata}
        for security in securities:
            key = (str(security.get("SECID")), str(security.get("BOARDID")))
            result.append({**security, **market_by_key.get(key, {})})
        start += len(securities)
        print(f"Пакетная загрузка рынка: {start} строк")
        if len(securities) < page_size:
            break

    write_cache(path, result)
    return result


def choose_best_board(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["_turnover"] = pd.to_numeric(frame.get("VALTODAY"), errors="coerce").fillna(0)
    frame["_price"] = pd.to_numeric(
        frame.get("OFFER", frame.get("LAST", frame.get("MARKETPRICE"))), errors="coerce"
    ).fillna(0)
    frame = frame.sort_values(["SECID", "_turnover", "_price"], ascending=[True, False, False])
    return frame.drop_duplicates("SECID", keep="first").drop(columns=["_turnover", "_price"])


def local_filter(frame: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    frame = choose_best_board(frame)
    for column in ("YIELD", "YIELDATWAP", "YIELDCLOSE", "OFFER", "LAST", "MARKETPRICE", "LCURRENTPRICE", "DURATION"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["_yield"] = frame.get("YIELD").fillna(frame.get("YIELDATWAP")).fillna(frame.get("YIELDCLOSE"))
    frame["_price"] = frame.get("OFFER").fillna(frame.get("LAST")).fillna(frame.get("MARKETPRICE")).fillna(frame.get("LCURRENTPRICE"))
    frame["_duration_months"] = frame.get("DURATION") / 30.4375
    mask = (
        frame["SECID"].astype(str).str.fullmatch(r"RU[A-Z0-9]{10}", na=False)
        & frame["_yield"].between(args.yield_more, args.yield_less, inclusive="both")
        & frame["_price"].between(args.price_more, args.price_less, inclusive="both")
        & frame["_duration_months"].between(args.duration_more, args.duration_less, inclusive="both")
    )
    return frame.loc[mask].copy()


def fetch_history(secid: str, board: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "history", f"{secid}_{board}")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        return cached
    from_date = (date.today() - timedelta(days=35)).isoformat()
    url = f"{MOEX}/history/engines/stock/markets/bonds/boards/{quote(board)}/securities/{quote(secid)}.json"
    payload = request_json(url, {"iss.meta": "off", "iss.only": "history", "history.columns": "TRADEDATE,VOLUME,NUMTRADES", "from": from_date, "limit": 100})
    history = rows(payload, "history")
    history = sorted(history, key=lambda row: str(row.get("TRADEDATE") or ""), reverse=True)[:HISTORY_DAYS]
    volumes = [safe_float(row.get("VOLUME")) or 0.0 for row in history]
    result = {
        "Торговых дней": len(history),
        "Объем за 15 дней, шт.": round(sum(volumes), 2),
        "Минимальный дневной объем, шт.": round(min(volumes), 2) if volumes else 0.0,
        "Сделок за 15 дней": int(sum(safe_float(row.get("NUMTRADES")) or 0 for row in history)),
    }
    write_cache(path, result)
    return result


def fetch_cashflow_flag(secid: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "cashflow", secid)
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        return cached
    url = f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json"
    payload = request_json(url, {"iss.meta": "off", "iss.only": "coupons", "coupons.columns": "coupondate,value"})
    future = []
    for row in rows(payload, "coupons"):
        coupon_date = pd.to_datetime(row.get("coupondate"), errors="coerce")
        if pd.notna(coupon_date) and coupon_date.date() >= date.today():
            future.append(row)
    unknown = sum(1 for row in future if safe_float(row.get("value")) is None)
    result = {"Будущих купонов": len(future), "Неизвестных будущих купонов": unknown, "Купоны известны": "ДА" if future and unknown == 0 else "НЕТ"}
    write_cache(path, result)
    return result


def enrich(row: dict[str, Any], args: argparse.Namespace, cache_dir: Path) -> dict[str, Any]:
    secid = str(row.get("SECID") or "")
    board = str(row.get("BOARDID") or "TQCB")
    history = fetch_history(secid, board, cache_dir, args.cache_hours)
    cashflow = fetch_cashflow_flag(secid, cache_dir, args.cache_hours)
    return {**row, **history, **cashflow}


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Экспериментальный пакетный сканер рынка облигаций MOEX V2")
    parser.add_argument("--yield-more", type=float, default=15)
    parser.add_argument("--yield-less", type=float, default=40)
    parser.add_argument("--price-more", type=float, default=70)
    parser.add_argument("--price-less", type=float, default=120)
    parser.add_argument("--duration-more", type=float, default=3)
    parser.add_argument("--duration-less", type=float, default=18)
    parser.add_argument("--volume-more", type=float, default=2000)
    parser.add_argument("--bond-volume-more", type=float, default=60000)
    parser.add_argument("--require-known-coupons", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--cache-hours", type=float, default=DEFAULT_CACHE_HOURS)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers должен быть от 1 до 8")

    project_root = Path(__file__).resolve().parent
    cache_dir = args.cache_dir or project_root / "data" / "cache" / "market_scanner_v2"
    started = time.perf_counter()
    market = fetch_market_batch(cache_dir, args.cache_hours)
    candidates = local_filter(pd.DataFrame(market), args)
    print(f"После локальной фильтрации: {len(candidates)} выпусков")

    enriched: list[dict[str, Any]] = []
    records = candidates.to_dict("records")
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="moex-v2") as pool:
        futures = {
            pool.submit(enrich, row, args, cache_dir): str(row.get("SECID"))
            for row in records
        }
        total = len(futures)
        for index, future in enumerate(as_completed(futures), 1):
            secid = futures[future]
            try:
                enriched.append(future.result())
                print(f"[{index}/{total}] готово: {secid}")
            except Exception as exc:
                print(f"[{index}/{total}] ошибка {secid}: {exc}")

    result = pd.DataFrame(output_row(row) for row in enriched)
    if not result.empty:
        result = result[
            (pd.to_numeric(result["Минимальный дневной объем, шт."], errors="coerce").fillna(0) >= args.volume_more)
            & (pd.to_numeric(result["Объем за 15 дней, шт."], errors="coerce").fillna(0) >= args.bond_volume_more)
        ]
        if args.require_known_coupons:
            result = result[result["Купоны известны"] == "ДА"]
        result = result.sort_values(["Доходность", "Объем за 15 дней, шт."], ascending=[False, False])

    output = args.output or Path.cwd() / f"bond_search_{date.today():%Y-%m-%d}.xlsx"
    parameters = pd.DataFrame({"Параметр": vars(args).keys(), "Значение": [str(value) for value in vars(args).values()]})
    stats = pd.DataFrame({
        "Показатель": ["Строк рынка", "После локальной фильтрации", "Итоговых выпусков", "Время, секунд", "Версия сканера"],
        "Значение": [len(market), len(candidates), len(result), round(time.perf_counter() - started, 2), "V2"],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Результаты поиска", index=False)
        parameters.to_excel(writer, sheet_name="Параметры", index=False)
        stats.to_excel(writer, sheet_name="Статистика V2", index=False)
    print(f"V2 завершён за {time.perf_counter() - started:.1f} сек. Найдено: {len(result)}")
    print(output)


if __name__ == "__main__":
    main()
