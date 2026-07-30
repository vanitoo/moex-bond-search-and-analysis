from __future__ import annotations

import argparse
import json
import logging
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
HISTORY_CALENDAR_DAYS = 15
MIN_HISTORY_SESSIONS = 6
MAX_MARKET_PAGES = 1000
_thread_local = threading.local()
LOGGER = logging.getLogger("market_scanner_v2")


def setup_logging(level: str, log_file: Path) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    LOGGER.setLevel(numeric_level)
    LOGGER.handlers.clear()
    LOGGER.propagate = False
    for handler in (logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")):
        handler.setLevel(numeric_level if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler) else logging.DEBUG)
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def session() -> requests.Session:
    current = getattr(_thread_local, "session", None)
    if current is None:
        current = requests.Session()
        current.headers.update({"User-Agent": "MOEX-Bond-Lab-market-scanner-v2/1.1"})
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


def request_json(url: str, params: dict[str, Any] | None = None, attempts: int = 3, purpose: str = "MOEX") -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        try:
            LOGGER.debug("Запрос %s: %s params=%s attempt=%s/%s", purpose, url, params, attempt, attempts)
            response = session().get(url, params=params, timeout=35)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX ISS вернул неожиданный формат")
            LOGGER.debug("Ответ %s: HTTP %s, %.2f сек., %s байт", purpose, response.status_code, time.perf_counter() - started, len(response.content))
            return payload
        except (requests.RequestException, ValueError) as exc:
            error = exc
            LOGGER.warning("Ошибка запроса %s, попытка %s/%s: %s", purpose, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(0.7 * attempt)
    raise RuntimeError(f"Запрос MOEX не выполнен ({purpose}): {error}") from error


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


def cursor_info(payload: dict[str, Any], block: str) -> tuple[int | None, int | None, int | None]:
    cursor_rows = rows(payload, f"{block}.cursor")
    if not cursor_rows:
        return None, None, None
    cursor = cursor_rows[0]
    return (
        int(safe_float(cursor.get("INDEX")) or 0),
        int(safe_float(cursor.get("TOTAL")) or 0),
        int(safe_float(cursor.get("PAGESIZE")) or 0),
    )


def fetch_market_batch(cache_dir: Path, cache_hours: float) -> list[dict[str, Any]]:
    path = cache_file(cache_dir, "market_snapshot")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, list) and cached:
        LOGGER.info("Рынок взят из кэша: %s строк", len(cached))
        return cached

    url = f"{MOEX}/engines/stock/markets/bonds/securities.json"
    start = 0
    result_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    seen: set[tuple[tuple[str, str], ...]] = set()
    for page_number in range(1, MAX_MARKET_PAGES + 1):
        payload = request_json(url, {
            "iss.meta": "off",
            "iss.only": "securities,marketdata,securities.cursor",
            "start": start,
            "securities.start": start,
            "limit": 100,
            "securities.limit": 100,
            "securities.columns": "SECID,SHORTNAME,SECNAME,BOARDID,FACEVALUE,MATDATE,ISQUALIFIEDINVESTORS,COUPONVALUE,COUPONPERIOD",
            "marketdata.columns": "SECID,BOARDID,LAST,MARKETPRICE,LCURRENTPRICE,OFFER,YIELD,YIELDATWAP,YIELDCLOSE,DURATION,VALTODAY,VOLTODAY,NUMTRADES",
        }, purpose=f"рынок, страница {page_number}")
        securities = rows(payload, "securities")
        marketdata = rows(payload, "marketdata")
        if not securities:
            break
        fingerprint = tuple((str(r.get("SECID") or ""), str(r.get("BOARDID") or "")) for r in securities)
        if fingerprint in seen:
            LOGGER.warning("MOEX повторил страницу при start=%s; загрузка остановлена", start)
            break
        seen.add(fingerprint)
        market_by_key = {(str(r.get("SECID") or ""), str(r.get("BOARDID") or "")): r for r in marketdata}
        before = len(result_by_key)
        for security in securities:
            key = (str(security.get("SECID") or ""), str(security.get("BOARDID") or ""))
            result_by_key[key] = {**security, **market_by_key.get(key, {})}
        index, total, page_size = cursor_info(payload, "securities")
        if total and len(result_by_key) >= total:
            break
        added = len(result_by_key) - before
        if added == 0:
            break
        step = page_size or len(securities)
        next_start = (index + step) if index is not None else (start + step)
        if next_start <= start:
            break
        start = next_start
    result = list(result_by_key.values())
    if not result:
        raise RuntimeError("MOEX не вернул рынок облигаций")
    write_cache(path, result)
    LOGGER.info("Загрузка рынка завершена: %s строк", len(result))
    return result


def choose_best_board(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["_turnover"] = pd.to_numeric(frame.get("VALTODAY"), errors="coerce").fillna(0)
    frame["_price_sort"] = pd.to_numeric(frame.get("OFFER"), errors="coerce").fillna(pd.to_numeric(frame.get("LAST"), errors="coerce")).fillna(0)
    return frame.sort_values(["SECID", "_turnover", "_price_sort"], ascending=[True, False, False]).drop_duplicates("SECID").drop(columns=["_turnover", "_price_sort"])


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
    filtered = frame.loc[mask].copy()
    LOGGER.info("После фильтра цены, доходности и дюрации: %s из %s выпусков", len(filtered), len(frame))
    return filtered


def fetch_primary_board(secid: str, cache_dir: Path, cache_hours: float) -> str | None:
    path = cache_file(cache_dir / "boards", secid)
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        return cached.get("board")
    payload = request_json(f"{MOEX}/securities/{quote(secid)}.json", {
        "iss.meta": "off", "iss.only": "boards", "boards.columns": "secid,boardid,is_primary"
    }, purpose=f"режим торгов {secid}")
    board = next((str(r.get("boardid")) for r in rows(payload, "boards") if safe_float(r.get("is_primary")) == 1), None)
    write_cache(path, {"board": board})
    return board


def fetch_history(secid: str, board: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "history_v1_compatible", f"{secid}_{board}")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        return cached
    from_date = (date.today() - timedelta(days=HISTORY_CALENDAR_DAYS)).isoformat()
    payload = request_json(
        f"{MOEX}/history/engines/stock/markets/bonds/boards/{quote(board)}/securities/{quote(secid)}.json",
        {"iss.meta": "off", "iss.only": "history", "history.columns": "TRADEDATE,VOLUME,NUMTRADES", "from": from_date, "limit": 100},
        purpose=f"история {secid}",
    )
    history = rows(payload, "history")
    volumes = [safe_float(r.get("VOLUME")) or 0.0 for r in history]
    result = {
        "Торговых дней": len(history),
        "Объем за 15 дней, шт.": round(sum(volumes), 2),
        "Минимальный дневной объем, шт.": round(min(volumes), 2) if volumes else 0.0,
        "Сделок за 15 дней": int(sum(safe_float(r.get("NUMTRADES")) or 0 for r in history)),
        "История достаточна": "ДА" if len(history) >= MIN_HISTORY_SESSIONS else "НЕТ",
    }
    write_cache(path, result)
    return result


def fetch_cashflow_flag(secid: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "cashflow_v1_compatible", secid)
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        return cached
    payload = request_json(
        f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json",
        {"iss.meta": "off", "iss.only": "coupons", "start": 0, "limit": 100},
        purpose=f"cashflow {secid}",
    )
    coupon_rows = rows(payload, "coupons")
    future: list[dict[str, Any]] = []
    for row in coupon_rows:
        coupon_date = pd.to_datetime(row.get("coupondate"), errors="coerce")
        if pd.notna(coupon_date) and coupon_date.date() > date.today():
            future.append(row)
    unknown = sum(1 for row in future if safe_float(row.get("value_rub")) is None)
    result = {
        "Будущих купонов": len(future),
        "Неизвестных будущих купонов": unknown,
        "Купоны известны": "ДА" if future and unknown == 0 else "НЕТ",
    }
    write_cache(path, result)
    return result


def enrich(row: dict[str, Any], args: argparse.Namespace, cache_dir: Path) -> dict[str, Any]:
    secid = str(row.get("SECID") or "")
    primary_board = fetch_primary_board(secid, cache_dir, args.cache_hours)
    board = primary_board or str(row.get("BOARDID") or "TQCB")
    history = fetch_history(secid, board, cache_dir, args.cache_hours)
    cashflow = fetch_cashflow_flag(secid, cache_dir, args.cache_hours)
    return {**row, "BOARDID": board, **history, **cashflow}


def output_row(row: dict[str, Any]) -> dict[str, Any]:
    duration_days = safe_float(row.get("DURATION"))
    yield_value = safe_float(row.get("YIELD")) or safe_float(row.get("YIELDATWAP")) or safe_float(row.get("YIELDCLOSE"))
    price = safe_float(row.get("OFFER")) or safe_float(row.get("LAST")) or safe_float(row.get("MARKETPRICE")) or safe_float(row.get("LCURRENTPRICE"))
    qualified_raw = str(row.get("ISQUALIFIEDINVESTORS") or "0").upper()
    return {
        "Код ценной бумаги": row.get("SECID"), "Краткое наименование": row.get("SHORTNAME") or "",
        "Полное наименование": row.get("SECNAME") or row.get("SHORTNAME") or "", "Режим торгов": row.get("BOARDID") or "",
        "Доходность": yield_value, "Цена, %": price, "Цена": price,
        "Дюрация, месяцев": round(duration_days / 30.4375, 2) if duration_days else None, "Дюрация, дней": duration_days,
        "Дата погашения": row.get("MATDATE") or "", "Номинал": safe_float(row.get("FACEVALUE")),
        "Торговых дней": row.get("Торговых дней", 0), "История достаточна": row.get("История достаточна", "НЕТ"),
        "Объем торгов за 15 дней": row.get("Объем за 15 дней, шт.", 0), "Объем за 15 дней, шт.": row.get("Объем за 15 дней, шт.", 0),
        "Минимальный дневной объем, шт.": row.get("Минимальный дневной объем, шт.", 0), "Количество сделок за 15 дней": row.get("Сделок за 15 дней", 0),
        "Для квалифицированных инвесторов": "ДА" if qualified_raw in {"1", "Y", "YES", "TRUE", "ДА"} else "НЕТ",
        "Будущих купонов": row.get("Будущих купонов", 0), "Неизвестных будущих купонов": row.get("Неизвестных будущих купонов", 0),
        "Купоны известны": row.get("Купоны известны", "НЕТ"), "Сканер": "V2",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Пакетный сканер рынка облигаций MOEX V2")
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
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers должен быть от 1 до 8")
    if args.cache_hours < 0:
        parser.error("--cache-hours не может быть отрицательным")
    if args.yield_more > args.yield_less or args.price_more > args.price_less or args.duration_more > args.duration_less:
        parser.error("Нижняя граница не может быть больше верхней")
    if args.volume_more < 0 or args.bond_volume_more < 0:
        parser.error("Объёмы торгов не могут быть отрицательными")

    setup_logging(args.log_level, args.log_file or Path.cwd() / "market_scanner_v2.log")
    project_root = Path(__file__).resolve().parent
    cache_dir = args.cache_dir or project_root / "data" / "cache" / "market_scanner_v2"
    started = time.perf_counter()
    market = fetch_market_batch(cache_dir, args.cache_hours)
    candidates = local_filter(pd.DataFrame(market), args)

    enriched: list[dict[str, Any]] = []
    records = candidates.to_dict("records")
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="moex-v2") as pool:
        futures = {pool.submit(enrich, row, args, cache_dir): str(row.get("SECID")) for row in records}
        for index, future in enumerate(as_completed(futures), 1):
            secid = futures[future]
            try:
                enriched.append(future.result())
                LOGGER.info("Обогащение [%s/%s] готово: %s", index, len(futures), secid)
            except Exception as exc:
                LOGGER.exception("Обогащение [%s/%s] ошибка %s: %s", index, len(futures), secid, exc)

    all_rows = pd.DataFrame(output_row(row) for row in enriched)
    result = all_rows.copy()
    rejected: list[dict[str, Any]] = []
    if not result.empty:
        for _, row in result.iterrows():
            reasons: list[str] = []
            if row["История достаточна"] != "ДА":
                reasons.append(f"меньше {MIN_HISTORY_SESSIONS} торговых дней")
            if safe_float(row["Минимальный дневной объем, шт."]) is None or float(row["Минимальный дневной объем, шт."]) < args.volume_more:
                reasons.append("минимальный дневной объём ниже порога")
            if safe_float(row["Объем за 15 дней, шт."]) is None or float(row["Объем за 15 дней, шт."]) < args.bond_volume_more:
                reasons.append("суммарный объём ниже порога")
            if args.require_known_coupons and row["Купоны известны"] != "ДА":
                reasons.append("есть неизвестные будущие купоны или нет будущих купонов")
            if reasons:
                rejected.append({**row.to_dict(), "Причина исключения": "; ".join(reasons)})
        rejected_ids = {r["Код ценной бумаги"] for r in rejected}
        result = result[~result["Код ценной бумаги"].isin(rejected_ids)]
        result = result.drop_duplicates("Код ценной бумаги").sort_values(["Доходность", "Объем за 15 дней, шт."], ascending=[False, False])

    output = args.output or Path.cwd() / f"bond_search_{date.today():%Y-%m-%d}.xlsx"
    elapsed = time.perf_counter() - started
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Результаты поиска", index=False)
        pd.DataFrame(rejected).to_excel(writer, sheet_name="Исключённые V2", index=False)
        pd.DataFrame({"Параметр": vars(args).keys(), "Значение": [str(v) for v in vars(args).values()]}).to_excel(writer, sheet_name="Параметры", index=False)
        pd.DataFrame({"Показатель": ["Строк рынка", "После локальной фильтрации", "Итоговых выпусков", "Исключено после обогащения", "Время, секунд", "Версия сканера"], "Значение": [len(market), len(candidates), len(result), len(rejected), round(elapsed, 2), "V2.1"]}).to_excel(writer, sheet_name="Статистика V2", index=False)
    LOGGER.info("V2 завершён за %.1f сек. Найдено: %s; исключено: %s", elapsed, len(result), len(rejected))
    LOGGER.info("Результат: %s", output)


if __name__ == "__main__":
    main()
