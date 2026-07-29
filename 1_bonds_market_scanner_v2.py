# 🔴 ЧТО ДЕЛАЕТ МОДУЛЬ: пакетно загружает рынок облигаций MOEX, фильтрует данные локально,
# использует дисковый кэш и ограниченный параллелизм для проверки оборотов и cashflow.
# Это экспериментальная версия первого этапа. V1 оставлен для сравнения результатов.

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
HISTORY_DAYS = 15
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

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    LOGGER.addHandler(console)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


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


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    attempts: int = 3,
    purpose: str = "MOEX",
) -> dict[str, Any]:
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
            LOGGER.debug(
                "Ответ %s: HTTP %s, %.2f сек., %s байт",
                purpose,
                response.status_code,
                time.perf_counter() - started,
                len(response.content),
            )
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
    if not path.exists():
        LOGGER.debug("Кэш отсутствует: %s", path)
        return None
    if max_age_hours <= 0:
        LOGGER.debug("Кэш отключён параметром cache-hours=0: %s", path)
        return None
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if age > timedelta(hours=max_age_hours):
        LOGGER.debug("Кэш устарел: %s, возраст %.2f ч.", path, age.total_seconds() / 3600)
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        LOGGER.debug("Кэш прочитан: %s, возраст %.2f ч.", path, age.total_seconds() / 3600)
        return payload
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Не удалось прочитать кэш %s: %s", path, exc)
        return None


def write_cache(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    LOGGER.debug("Кэш записан: %s", path)


def cursor_info(payload: dict[str, Any], block: str) -> tuple[int | None, int | None, int | None]:
    cursor_rows = rows(payload, f"{block}.cursor")
    if not cursor_rows:
        return None, None, None
    cursor = cursor_rows[0]
    index = int(safe_float(cursor.get("INDEX")) or 0)
    total = int(safe_float(cursor.get("TOTAL")) or 0)
    page_size = int(safe_float(cursor.get("PAGESIZE")) or 0)
    return index, total, page_size


def fetch_market_batch(cache_dir: Path, cache_hours: float) -> list[dict[str, Any]]:
    path = cache_file(cache_dir, "market_snapshot")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, list) and cached:
        LOGGER.info("Рынок взят из кэша: %s строк, файл %s", len(cached), path)
        return cached

    url = f"{MOEX}/engines/stock/markets/bonds/securities.json"
    requested_page_size = 100
    start = 0
    result_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    seen_page_fingerprints: set[tuple[tuple[str, str], ...]] = set()

    LOGGER.info("Начинаем загрузку рынка MOEX: %s", url)
    LOGGER.info("Кэш рынка не используется; cache-hours=%s", cache_hours)

    for page_number in range(1, MAX_MARKET_PAGES + 1):
        LOGGER.info("Страница рынка %s: start=%s, запрошено=%s", page_number, start, requested_page_size)
        payload = request_json(
            url,
            {
                "iss.meta": "off",
                "iss.only": "securities,marketdata,securities.cursor",
                "start": start,
                "securities.start": start,
                "limit": requested_page_size,
                "securities.limit": requested_page_size,
                "securities.columns": "SECID,SHORTNAME,SECNAME,BOARDID,FACEVALUE,MATDATE,ISQUALIFIEDINVESTORS,COUPONVALUE,COUPONPERIOD",
                "marketdata.columns": "SECID,BOARDID,LAST,MARKETPRICE,LCURRENTPRICE,OFFER,YIELD,YIELDATWAP,YIELDCLOSE,DURATION,VALTODAY,VOLTODAY,NUMTRADES",
            },
            purpose=f"рынок, страница {page_number}",
        )
        securities = rows(payload, "securities")
        marketdata = rows(payload, "marketdata")
        cursor_index, cursor_total, cursor_page_size = cursor_info(payload, "securities")

        LOGGER.info(
            "Получено: securities=%s, marketdata=%s, cursor(index=%s total=%s pagesize=%s)",
            len(securities),
            len(marketdata),
            cursor_index,
            cursor_total,
            cursor_page_size,
        )

        if not securities:
            LOGGER.info("MOEX вернул пустую страницу. Загрузка рынка завершена.")
            break

        fingerprint = tuple(
            (str(row.get("SECID") or ""), str(row.get("BOARDID") or ""))
            for row in securities
        )
        if fingerprint in seen_page_fingerprints:
            LOGGER.warning(
                "MOEX повторно вернул уже загруженную страницу при start=%s. "
                "Останавливаем цикл, чтобы не создавать миллионы дублей.",
                start,
            )
            break
        seen_page_fingerprints.add(fingerprint)

        market_by_key = {
            (str(row.get("SECID") or ""), str(row.get("BOARDID") or "")): row
            for row in marketdata
        }
        before = len(result_by_key)
        for security in securities:
            key = (str(security.get("SECID") or ""), str(security.get("BOARDID") or ""))
            result_by_key[key] = {**security, **market_by_key.get(key, {})}
        added = len(result_by_key) - before

        LOGGER.info(
            "Страница обработана: новых=%s, уникальных строк рынка=%s",
            added,
            len(result_by_key),
        )
        if added == 0:
            LOGGER.warning("Страница не добавила новых SECID/BOARDID. Загрузка остановлена.")
            break

        if cursor_total is not None and cursor_total > 0 and len(result_by_key) >= cursor_total:
            LOGGER.info("Достигнут TOTAL из курсора MOEX: %s. Загрузка завершена.", cursor_total)
            break

        actual_step = cursor_page_size or len(securities)
        if actual_step <= 0:
            LOGGER.warning("Невозможно определить шаг пагинации. Загрузка остановлена.")
            break
        next_start = (cursor_index + actual_step) if cursor_index is not None else (start + actual_step)
        if next_start <= start:
            LOGGER.warning("Пагинация не продвинулась: start=%s, next_start=%s. Остановка.", start, next_start)
            break
        start = next_start

        if cursor_total is None and len(securities) < requested_page_size:
            LOGGER.info("Получена последняя неполная страница: %s строк.", len(securities))
            break
    else:
        raise RuntimeError(f"Превышен защитный лимит в {MAX_MARKET_PAGES} страниц рынка MOEX")

    result = list(result_by_key.values())
    if not result:
        raise RuntimeError("MOEX не вернул ни одной строки рынка облигаций")

    write_cache(path, result)
    LOGGER.info("Загрузка рынка завершена: %s уникальных строк. Кэш: %s", len(result), path)
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
    LOGGER.info("Локальная фильтрация: входных строк=%s", len(frame))
    frame = choose_best_board(frame)
    LOGGER.info("После выбора лучшего режима торгов: уникальных выпусков=%s", len(frame))
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
    LOGGER.info(
        "После фильтра доходность %.2f–%.2f%%, цена %.2f–%.2f%%, дюрация %.2f–%.2f мес.: %s выпусков",
        args.yield_more,
        args.yield_less,
        args.price_more,
        args.price_less,
        args.duration_more,
        args.duration_less,
        len(filtered),
    )
    return filtered


def fetch_history(secid: str, board: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "history", f"{secid}_{board}")
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        LOGGER.debug("%s: история из кэша", secid)
        return cached
    from_date = (date.today() - timedelta(days=35)).isoformat()
    url = f"{MOEX}/history/engines/stock/markets/bonds/boards/{quote(board)}/securities/{quote(secid)}.json"
    payload = request_json(
        url,
        {"iss.meta": "off", "iss.only": "history", "history.columns": "TRADEDATE,VOLUME,NUMTRADES", "from": from_date, "limit": 100},
        purpose=f"история {secid}",
    )
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
    LOGGER.debug("%s: история загружена, торговых дней=%s", secid, len(history))
    return result


def fetch_cashflow_flag(secid: str, cache_dir: Path, cache_hours: float) -> dict[str, Any]:
    path = cache_file(cache_dir / "cashflow", secid)
    cached = read_cache(path, cache_hours)
    if isinstance(cached, dict):
        LOGGER.debug("%s: cashflow из кэша", secid)
        return cached
    url = f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json"
    payload = request_json(
        url,
        {"iss.meta": "off", "iss.only": "coupons", "coupons.columns": "coupondate,value"},
        purpose=f"cashflow {secid}",
    )
    future = []
    for row in rows(payload, "coupons"):
        coupon_date = pd.to_datetime(row.get("coupondate"), errors="coerce")
        if pd.notna(coupon_date) and coupon_date.date() >= date.today():
            future.append(row)
    unknown = sum(1 for row in future if safe_float(row.get("value")) is None)
    result = {
        "Будущих купонов": len(future),
        "Неизвестных будущих купонов": unknown,
        "Купоны известны": "ДА" if future and unknown == 0 else "НЕТ",
    }
    write_cache(path, result)
    LOGGER.debug("%s: cashflow загружен, будущих купонов=%s, неизвестных=%s", secid, len(future), unknown)
    return result


def enrich(row: dict[str, Any], args: argparse.Namespace, cache_dir: Path) -> dict[str, Any]:
    secid = str(row.get("SECID") or "")
    board = str(row.get("BOARDID") or "TQCB")
    LOGGER.debug("%s: начинаем обогащение, board=%s", secid, board)
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
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    parser.add_argument("--log-file", type=Path, help="Файл подробного лога; по умолчанию market_scanner_v2.log в текущей папке")
    args = parser.parse_args()

    if not 1 <= args.workers <= 8:
        parser.error("--workers должен быть от 1 до 8")
    if args.cache_hours < 0:
        parser.error("--cache-hours не может быть отрицательным")
    if args.yield_more > args.yield_less:
        parser.error("Доходность ОТ не может быть больше доходности ДО")
    if args.price_more > args.price_less:
        parser.error("Цена ОТ не может быть больше цены ДО")
    if args.duration_more > args.duration_less:
        parser.error("Дюрация ОТ не может быть больше дюрации ДО")
    if args.volume_more < 0 or args.bond_volume_more < 0:
        parser.error("Объёмы торгов не могут быть отрицательными")

    log_file = args.log_file or Path.cwd() / "market_scanner_v2.log"
    setup_logging(args.log_level, log_file)

    project_root = Path(__file__).resolve().parent
    cache_dir = args.cache_dir or project_root / "data" / "cache" / "market_scanner_v2"
    started = time.perf_counter()

    LOGGER.info("=== Запуск сканера V2 ===")
    LOGGER.info("Рабочая папка: %s", Path.cwd())
    LOGGER.info("Кэш: %s; срок жизни: %s ч.", cache_dir, args.cache_hours)
    LOGGER.info("Потоки: %s", args.workers)
    LOGGER.info(
        "Критерии: доходность %.2f–%.2f%%; цена %.2f–%.2f%%; дюрация %.2f–%.2f мес.; "
        "мин. день %.0f шт.; за 15 дней %.0f шт.; известные купоны=%s",
        args.yield_more,
        args.yield_less,
        args.price_more,
        args.price_less,
        args.duration_more,
        args.duration_less,
        args.volume_more,
        args.bond_volume_more,
        args.require_known_coupons,
    )

    market = fetch_market_batch(cache_dir, args.cache_hours)
    candidates = local_filter(pd.DataFrame(market), args)

    enriched: list[dict[str, Any]] = []
    records = candidates.to_dict("records")
    LOGGER.info("Начинаем историю и cashflow: %s выпусков, %s потоков", len(records), args.workers)
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
                LOGGER.info("Обогащение [%s/%s] готово: %s", index, total, secid)
            except Exception as exc:
                LOGGER.exception("Обогащение [%s/%s] ошибка %s: %s", index, total, secid, exc)

    result = pd.DataFrame(output_row(row) for row in enriched)
    before_liquidity = len(result)
    if not result.empty:
        result = result[
            (pd.to_numeric(result["Минимальный дневной объем, шт."], errors="coerce").fillna(0) >= args.volume_more)
            & (pd.to_numeric(result["Объем за 15 дней, шт."], errors="coerce").fillna(0) >= args.bond_volume_more)
        ]
        LOGGER.info("После фильтра объёмов: %s из %s выпусков", len(result), before_liquidity)
        if args.require_known_coupons:
            before_coupons = len(result)
            result = result[result["Купоны известны"] == "ДА"]
            LOGGER.info("После фильтра известных купонов: %s из %s выпусков", len(result), before_coupons)
        result = result.sort_values(["Доходность", "Объем за 15 дней, шт."], ascending=[False, False])

    output = args.output or Path.cwd() / f"bond_search_{date.today():%Y-%m-%d}.xlsx"
    parameters = pd.DataFrame({"Параметр": vars(args).keys(), "Значение": [str(value) for value in vars(args).values()]})
    elapsed = time.perf_counter() - started
    stats = pd.DataFrame({
        "Показатель": ["Строк рынка", "После локальной фильтрации", "Итоговых выпусков", "Время, секунд", "Версия сканера"],
        "Значение": [len(market), len(candidates), len(result), round(elapsed, 2), "V2"],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Результаты поиска", index=False)
        parameters.to_excel(writer, sheet_name="Параметры", index=False)
        stats.to_excel(writer, sheet_name="Статистика V2", index=False)

    LOGGER.info("V2 завершён за %.1f сек. Найдено: %s", elapsed, len(result))
    LOGGER.info("Результат: %s", output)
    LOGGER.info("Подробный лог: %s", log_file)


if __name__ == "__main__":
    main()
