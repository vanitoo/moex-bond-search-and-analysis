from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from moex_bond_search_and_analysis.http_client import browser_headers, browser_session

FNS_BASES = (
    "https://bo.nalog.gov.ru",
    "https://bo.nalog.ru",
)
FNS_TIMEOUT = 30
DEFAULT_CACHE_DAYS = 35
DEFAULT_WORKERS = 3

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


def fetch_fns_financials(
    inn: str,
    *,
    session: requests.Session | None = None,
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
            search_response = client.get(
                f"{base}/advanced-search/organizations/search",
                params={"query": inn, "page": 0, "size": 20},
                timeout=FNS_TIMEOUT,
            )
            search_response.raise_for_status()
            org_id, search_item = _find_org_id(search_response.json(), inn)
            if not org_id:
                continue
            bfo_response = client.get(
                f"{base}/nbo/organizations/{org_id}/bfo/",
                timeout=FNS_TIMEOUT,
            )
            bfo_response.raise_for_status()
            source_url = f"{base}/organizations-card/{org_id}"
            return parse_fns_bfo(
                bfo_response.json(),
                inn=inn,
                source_url=source_url,
                search_item=search_item,
            )
        except (requests.RequestException, ValueError) as exc:
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
            row = fetch_fns_financials(inn)
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
