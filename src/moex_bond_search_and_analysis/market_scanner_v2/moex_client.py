from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests

from .cache import JsonCache
from .models import HISTORY_CALENDAR_DAYS, MAX_MARKET_PAGES, MIN_HISTORY_SESSIONS

MOEX = "https://iss.moex.com/iss"
_thread_local = threading.local()


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    return [dict(zip(columns, item)) for item in section.get("data") or []]


class MoexClient:
    def __init__(self, cache: JsonCache, logger: logging.Logger) -> None:
        self.cache = cache
        self.logger = logger

    def _session(self) -> requests.Session:
        current = getattr(_thread_local, "session", None)
        if current is None:
            current = requests.Session()
            current.headers.update({"User-Agent": "MOEX-Bond-Lab-market-scanner-v2/2.2"})
            _thread_local.session = current
        return current

    def _request_json(self, url: str, params: dict[str, Any] | None = None, attempts: int = 3, purpose: str = "MOEX") -> dict[str, Any]:
        error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                self.logger.debug("Запрос %s: %s params=%s attempt=%s/%s", purpose, url, params, attempt, attempts)
                response = self._session().get(url, params=params, timeout=35)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("MOEX ISS вернул неожиданный формат")
                self.logger.debug("Ответ %s: HTTP %s, %.2f сек., %s байт", purpose, response.status_code, time.perf_counter() - started, len(response.content))
                return payload
            except (requests.RequestException, ValueError) as exc:
                error = exc
                self.logger.warning("Ошибка запроса %s, попытка %s/%s: %s", purpose, attempt, attempts, exc)
                if attempt < attempts:
                    time.sleep(0.7 * attempt)
        raise RuntimeError(f"Запрос MOEX не выполнен ({purpose}): {error}") from error

    @staticmethod
    def _cursor_info(payload: dict[str, Any], block: str) -> tuple[int | None, int | None, int | None]:
        cursor_rows = rows(payload, f"{block}.cursor")
        if not cursor_rows:
            return None, None, None
        cursor = cursor_rows[0]
        return (
            int(safe_float(cursor.get("INDEX")) or 0),
            int(safe_float(cursor.get("TOTAL")) or 0),
            int(safe_float(cursor.get("PAGESIZE")) or 0),
        )

    def fetch_market(self) -> list[dict[str, Any]]:
        cached = self.cache.get("market", "market_snapshot")
        if isinstance(cached, list) and cached:
            self.logger.info("Рынок взят из кэша: %s строк", len(cached))
            return cached

        url = f"{MOEX}/engines/stock/markets/bonds/securities.json"
        start = 0
        result_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        seen: set[tuple[tuple[str, str], ...]] = set()
        for page_number in range(1, MAX_MARKET_PAGES + 1):
            payload = self._request_json(url, {
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
                self.logger.warning("MOEX повторил страницу при start=%s; загрузка остановлена", start)
                break
            seen.add(fingerprint)
            market_by_key = {(str(r.get("SECID") or ""), str(r.get("BOARDID") or "")): r for r in marketdata}
            before = len(result_by_key)
            for security in securities:
                key = (str(security.get("SECID") or ""), str(security.get("BOARDID") or ""))
                result_by_key[key] = {**security, **market_by_key.get(key, {})}
            index, total, page_size = self._cursor_info(payload, "securities")
            if total and len(result_by_key) >= total:
                break
            if len(result_by_key) == before:
                break
            step = page_size or len(securities)
            next_start = (index + step) if index is not None else (start + step)
            if next_start <= start:
                break
            start = next_start

        result = list(result_by_key.values())
        if not result:
            raise RuntimeError("MOEX не вернул рынок облигаций")
        self.cache.put("market", "market_snapshot", result)
        self.logger.info("Загрузка рынка завершена: %s строк", len(result))
        return result

    def fetch_primary_board(self, secid: str) -> str | None:
        cached = self.cache.get("boards", secid)
        if isinstance(cached, dict):
            return cached.get("board")
        payload = self._request_json(f"{MOEX}/securities/{quote(secid)}.json", {
            "iss.meta": "off", "iss.only": "boards", "boards.columns": "secid,boardid,is_primary"
        }, purpose=f"режим торгов {secid}")
        board = next((str(r.get("boardid")) for r in rows(payload, "boards") if safe_float(r.get("is_primary")) == 1), None)
        self.cache.put("boards", secid, {"board": board})
        return board

    def fetch_history(self, secid: str, board: str) -> dict[str, Any]:
        key = f"{secid}_{board}_{date.today().isoformat()}"
        cached = self.cache.get("history", key)
        if isinstance(cached, dict):
            return cached
        from_date = (date.today() - timedelta(days=HISTORY_CALENDAR_DAYS)).isoformat()
        payload = self._request_json(
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
        self.cache.put("history", key, result)
        return result

    def fetch_cashflow(self, secid: str) -> dict[str, Any]:
        cached = self.cache.get("cashflow", secid)
        if isinstance(cached, dict):
            return cached
        payload = self._request_json(
            f"{MOEX}/statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json",
            {"iss.meta": "off", "iss.only": "coupons", "start": 0, "limit": 100},
            purpose=f"cashflow {secid}",
        )
        future: list[dict[str, Any]] = []
        for row in rows(payload, "coupons"):
            coupon_date = pd.to_datetime(row.get("coupondate"), errors="coerce")
            if pd.notna(coupon_date) and coupon_date.date() > date.today():
                future.append(row)
        unknown = sum(1 for row in future if safe_float(row.get("value_rub")) is None)
        result = {
            "Будущих купонов": len(future),
            "Неизвестных будущих купонов": unknown,
            "Купоны известны": "ДА" if future and unknown == 0 else "НЕТ",
        }
        self.cache.put("cashflow", secid, result)
        return result
