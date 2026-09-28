from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from moex_bond_search_and_analysis.http_client import browser_headers, browser_session

FNS_BASES = ("https://bo.nalog.gov.ru",)
FNS_TIMEOUT = 30
DEFAULT_CACHE_DAYS = 35
DEFAULT_WORKERS = 1
DEFAULT_DELAY_SECONDS = 1.2
DEFAULT_RETRIES = 4
_RETRYABLE_STATUS = {403, 408, 425, 429, 500, 502, 503, 504}
_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0

FINANCIAL_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Период", "Валюта",
    "Выручка", "EBITDA", "Чистая прибыль", "Операционный денежный поток",
    "Денежные средства", "Общий долг", "Краткосрочный долг",
    "Процентные расходы", "Собственный капитал", "Оборотные активы",
    "Краткосрочные обязательства", "Источник", "Комментарий",
]

AUTO_COMMENT = (
    "Автоматически из публичного JSON ГИР БО ФНС; значения форм БФО в тыс. руб.; "
    "общий долг = заёмные средства строк 1410+1510; EBITDA в стандартной бухгалтерской "
    "отчётности не публикуется и не рассчитывается искусственно"
)


@dataclass(frozen=True)
class FetchStats:
    requested: int
    fetched: int
    cached: int
    not_found: int
    errors: tuple[str, ...]


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"<[^>]+>", "", str(value)).strip()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(str(value).replace(" ", "").replace(",", "."))
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


def _line(block: dict[str, Any] | None, code: str) -> float | None:
    if not isinstance(block, dict):
        return None
    for key in (f"current{code}", code, f"current_{code}"):
        value = _number(block.get(key))
        if value is not None:
            return value
    return None


def _sum_known(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("content", "items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _find_org_id(payload: Any, inn: str) -> tuple[str | None, dict[str, Any]]:
    items = _extract_items(payload)
    exact: dict[str, Any] | None = None
    for item in items:
        candidate = re.sub(r"\D", "", _clean(item.get("inn")))
        if candidate == inn:
            exact = item
            break
    item = exact or (items[0] if items else None)
    if not item:
        return None, {}
    org_id = item.get("id") or item.get("organizationId") or item.get("organization_id")
    return (str(org_id).strip() if org_id not in (None, "") else None), item


def _latest_correction(payload: Any) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    periods = _extract_items(payload)
    candidates: list[tuple[int, int, int, str, dict[str, Any], dict[str, Any]]] = []
    for period_item in periods:
        period_text = _clean(period_item.get("period") or period_item.get("year"))
        try:
            period_num = int(re.sub(r"\D", "", period_text)[:4])
        except ValueError:
            period_num = 0
        corrections = period_item.get("typeCorrections") or period_item.get("corrections") or []
        if isinstance(corrections, dict):
            corrections = [corrections]
        for wrapper in corrections:
            if not isinstance(wrapper, dict):
                continue
            correction = wrapper.get("correction", wrapper)
            if isinstance(correction, list):
                correction_list = [item for item in correction if isinstance(item, dict)]
            elif isinstance(correction, dict):
                correction_list = [correction]
            else:
                continue
            wrapper_type = _number(wrapper.get("type"))
            for item in correction_list:
                period_type = _number(item.get("periodType"))
                annual = 1 if (period_type == 12 or wrapper_type == 12) else 0
                version = int(_number(item.get("correctionVersion")) or _number(item.get("id")) or 0)
                candidates.append((annual, period_num, version, period_text, item, period_item))
    if not candidates:
        return None
    annual_candidates = [item for item in candidates if item[0] == 1]
    pool = annual_candidates or candidates
    _, _, _, period_text, correction, period_item = max(pool, key=lambda item: (item[1], item[0], item[2]))
    return period_text, correction, period_item


def parse_fns_bfo(payload: Any, *, inn: str, source_url: str, search_item: dict[str, Any] | None = None) -> dict[str, Any] | None:
    selected = _latest_correction(payload)
    if selected is None:
        return None
    period, correction, period_item = selected
    balance = correction.get("balance") or {}
    result = correction.get("financialResult") or correction.get("financialResults") or {}
    cashflow = (
        correction.get("fundsMovement")
        or correction.get("cashFlow")
        or correction.get("cashflow")
        or {}
    )
    organization = (
        period_item.get("organizationInfo")
        or correction.get("organizationInfo")
        or search_item
        or {}
    )
    issuer = (
        _clean(organization.get("name"))
        or _clean(organization.get("shortName"))
        or _clean(organization.get("fullName"))
        or _clean(organization.get("organizationName"))
    )

    long_debt = _line(balance, "1410")
    short_debt = _line(balance, "1510")
    interest = _line(result, "2330")
    if interest is not None:
        interest = abs(interest)

    return {
        "Код ценной бумаги": "",
        "Эмитент": issuer,
        "ИНН": inn,
        "Период": period,
        "Валюта": "тыс. руб.",
        "Выручка": _line(result, "2110"),
        "EBITDA": None,
        "Чистая прибыль": _line(result, "2400"),
        "Операционный денежный поток": _line(cashflow, "4100"),
        "Денежные средства": _line(balance, "1250"),
        "Общий долг": _sum_known(long_debt, short_debt),
        "Краткосрочный долг": short_debt,
        "Процентные расходы": interest,
        "Собственный капитал": _line(balance, "1300"),
        "Оборотные активы": _line(balance, "1200"),
        "Краткосрочные обязательства": _line(balance, "1500"),
        "Источник": source_url,
        "Комментарий": AUTO_COMMENT,
    }


def _cache_file(cache_dir: Path, inn: str) -> Path:
    return cache_dir / f"{inn}.json"


def _load_cache(cache_dir: Path, inn: str, cache_days: int) -> dict[str, Any] | None:
    path = _cache_file(cache_dir, inn)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(str(payload.get("fetched_at")))
        if datetime.now() - fetched_at > timedelta(days=max(0, cache_days)):
            return None
        row = payload.get("row")
        return row if isinstance(row, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_cache(cache_dir: Path, inn: str, row: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_file(cache_dir, inn).write_text(
        json.dumps(
            {"fetched_at": datetime.now().isoformat(timespec="seconds"), "row": row},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def _paced_get(
    client: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> requests.Response:
    """GET с общим rate-limit, retry/backoff и понятной диагностикой JSON API ФНС."""
    global _NEXT_REQUEST_AT

    last_error: Exception | None = None
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        with _RATE_LOCK:
            now = time.monotonic()
            wait = max(0.0, _NEXT_REQUEST_AT - now)
            if wait:
                time.sleep(wait)
            _NEXT_REQUEST_AT = time.monotonic() + max(0.0, float(delay_seconds))

        try:
            response = client.get(url, params=params, timeout=FNS_TIMEOUT)
            if response.status_code in _RETRYABLE_STATUS:
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else 0.0
                except ValueError:
                    sleep_for = 0.0
                sleep_for = max(sleep_for, min(20.0, 1.5 * (2 ** attempt)))
                last_error = RuntimeError(
                    f"HTTP {response.status_code} от ГИР БО; повтор через {sleep_for:.1f} с"
                )
                if attempt + 1 < attempts:
                    time.sleep(sleep_for)
                    continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(20.0, 1.5 * (2 ** attempt)))
                continue
            raise

    if last_error:
        raise RuntimeError(str(last_error))
    raise RuntimeError("Не удалось выполнить запрос ГИР БО")


def _json_payload(response: requests.Response, *, label: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        content_type = response.headers.get("Content-Type", "")
        preview = (response.text or "").strip().replace("\n", " ")[:160]
        raise RuntimeError(
            f"{label}: ГИР БО вернул не JSON "
            f"(HTTP {response.status_code}, {content_type or 'без Content-Type'}"
            + (f", начало ответа: {preview!r}" if preview else ", пустой ответ")
            + ")"
        ) from exc


def _paced_json_get(
    client: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    retries: int = DEFAULT_RETRIES,
    label: str,
) -> Any:
    last_error: Exception | None = None
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            response = _paced_get(
                client,
                url,
                params=params,
                delay_seconds=delay_seconds,
                retries=1,
            )
            return _json_payload(response, label=label)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(30.0, 2.0 * (2 ** attempt)))
                continue
            break
    raise RuntimeError(str(last_error or f"{label}: неизвестная ошибка ГИР БО"))


def fetch_fns_financials(
    inn: str,
    *,
    session: requests.Session | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any] | None:
    inn = re.sub(r"\D", "", str(inn or ""))
    if len(inn) != 10:
        return None

    client = session or browser_session(trust_env=False)
    client.headers.update(browser_headers(
        referer="https://bo.nalog.gov.ru/search",
        extra={"Accept": "application/json, text/plain, */*"},
    ))

    last_error: Exception | None = None
    for base in FNS_BASES:
        try:
            search_payload = _paced_json_get(
                client,
                f"{base}/advanced-search/organizations/search",
                params={"query": inn, "page": 0, "size": 20},
                delay_seconds=delay_seconds,
                retries=retries,
                label=f"поиск ИНН {inn}",
            )
            org_id, search_item = _find_org_id(search_payload, inn)
            if not org_id:
                continue
            bfo_payload = _paced_json_get(
                client,
                f"{base}/nbo/organizations/{org_id}/bfo/",
                delay_seconds=delay_seconds,
                retries=retries,
                label=f"БФО ИНН {inn}",
            )
            source_url = f"{base}/organizations-card/{org_id}"
            return parse_fns_bfo(
                bfo_payload,
                inn=inn,
                source_url=source_url,
                search_item=search_item,
            )
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            continue
    if last_error:
        raise RuntimeError(f"ГИР БО ФНС недоступен для ИНН {inn}: {last_error}") from last_error
    return None


def fetch_financials_for_inns(
    inns: Iterable[str],
    *,
    cache_dir: Path,
    cache_days: int = DEFAULT_CACHE_DAYS,
    workers: int = DEFAULT_WORKERS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> tuple[pd.DataFrame, FetchStats]:
    normalized = sorted({
        re.sub(r"\D", "", str(value or ""))
        for value in inns
        if len(re.sub(r"\D", "", str(value or ""))) == 10
    })
    rows: list[dict[str, Any]] = []
    cached_count = 0
    pending: list[str] = []
    for inn in normalized:
        cached = _load_cache(cache_dir, inn, cache_days)
        if cached is not None:
            rows.append(cached)
            cached_count += 1
        else:
            pending.append(inn)

    errors: list[str] = []
    not_found = 0
    fetched = 0

    def one(inn: str) -> tuple[str, dict[str, Any] | None, str | None]:
        try:
            row = fetch_fns_financials(
                inn,
                delay_seconds=max(0.0, float(delay_seconds)),
                retries=max(1, int(retries)),
            )
            return inn, row, None
        except Exception as exc:
            return inn, None, str(exc)

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as pool:
        futures = {pool.submit(one, inn): inn for inn in pending}
        for future in as_completed(futures):
            inn, row, error = future.result()
            if error:
                errors.append(error)
            elif row is None:
                not_found += 1
            else:
                rows.append(row)
                fetched += 1
                _save_cache(cache_dir, inn, row)

    frame = pd.DataFrame(rows, columns=FINANCIAL_COLUMNS)
    stats = FetchStats(
        requested=len(normalized),
        fetched=fetched,
        cached=cached_count,
        not_found=not_found,
        errors=tuple(errors),
    )
    return frame, stats


def _manual_key(row: pd.Series) -> tuple[str, str]:
    inn = re.sub(r"\D", "", _clean(row.get("ИНН")))
    secid = _clean(row.get("Код ценной бумаги")).upper()
    return inn, secid


def _automatic(row: pd.Series) -> bool:
    return _clean(row.get("Комментарий")).startswith("Автоматически из публичного JSON ГИР БО ФНС")


def merge_financial_rows(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    existing = existing.reindex(columns=FINANCIAL_COLUMNS)
    fetched = fetched.reindex(columns=FINANCIAL_COLUMNS)
    if existing.empty:
        return fetched.reset_index(drop=True)

    manual = existing.loc[~existing.apply(_automatic, axis=1)].copy()
    auto_old = existing.loc[existing.apply(_automatic, axis=1)].copy()
    manual_keys = {_manual_key(row) for _, row in manual.iterrows()}

    fresh_rows = [
        row for _, row in fetched.iterrows()
        if _manual_key(row) not in manual_keys
    ]
    fresh = pd.DataFrame(fresh_rows, columns=FINANCIAL_COLUMNS)

    # Для ИНН, которые сегодня не обновились, сохраняем старый автоматический кэш.
    fresh_inns = {key[0] for key in (_manual_key(row) for _, row in fresh.iterrows()) if key[0]}
    old_keep = auto_old[
        ~auto_old["ИНН"].astype(str).str.replace(r"\D", "", regex=True).isin(fresh_inns)
    ]

    result = pd.concat([manual, fresh, old_keep], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=FINANCIAL_COLUMNS)
    result["_period_num"] = pd.to_numeric(
        result["Период"].astype(str).str.extract(r"(\d{4})", expand=False),
        errors="coerce",
    ).fillna(0)
    result["_key"] = result.apply(_manual_key, axis=1)
    result = result.sort_values("_period_num", ascending=False).drop_duplicates("_key", keep="first")
    return result.drop(columns=["_period_num", "_key"]).reset_index(drop=True)
