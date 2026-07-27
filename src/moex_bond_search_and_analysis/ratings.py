from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from typing import Any

import pandas as pd
import requests


EXPERT_RA_EXPORT_URL = "https://raexpert.ru/ratings/ratings-xlsx-export"
EXPERT_RA_SOURCE = "АО «Эксперт РА»"
EXPERT_RA_TIMEOUT = 120
EXPERT_RA_PATHS = [
    "credits",
    "credits_fin",
    "credits_holding",
    "leasing_rel",
    "regioncredit",
]
MOEX_SECURITIES_URL = "https://iss.moex.com/iss/securities.json"
MOEX_TIMEOUT = 30

RATING_COLUMNS = [
    "Код ценной бумаги",
    "Эмитент",
    "ИНН",
    "Рейтинг",
    "Агентство",
    "Прогноз",
    "Дата рейтинга",
    "Предыдущий рейтинг",
    "Дата предыдущего рейтинга",
    "Источник",
    "Комментарий",
]


def _clean_identifier(value: Any, prefix: str = "") -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if prefix:
        text = re.sub(rf"^\s*{re.escape(prefix)}\s*:\s*", "", text, flags=re.I)
    return text


def _find_header_row(raw: pd.DataFrame) -> int:
    for index, row in raw.iterrows():
        values = {str(value).strip() for value in row if not pd.isna(value)}
        if {"Эмитент/Объект", "Рейтинг", "ИНН"}.issubset(values):
            return int(index)
    raise ValueError("В экспорте «Эксперт РА» не найдена строка заголовков")


def parse_expert_ra_export(content: bytes) -> pd.DataFrame:
    raw = pd.read_excel(BytesIO(content), sheet_name=0, header=None)
    header_row = _find_header_row(raw)
    source = pd.read_excel(BytesIO(content), sheet_name=0, header=header_row)

    required = {
        "Эмитент/Объект",
        "ИНН",
        "ISIN",
        "Рейтинг",
        "Дата присвоения/актуализации/изменения рейтинга",
        "Прогноз",
        "Пресс-релиз",
    }
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(
            "В экспорте «Эксперт РА» отсутствуют колонки: "
            + ", ".join(sorted(missing))
        )

    rows: list[dict[str, Any]] = []
    for _, item in source.iterrows():
        rating = _clean_identifier(item.get("Рейтинг"))
        if not rating:
            continue
        url = _clean_identifier(item.get("Пресс-релиз"))
        rows.append(
            {
                "Код ценной бумаги": _clean_identifier(item.get("ISIN")),
                "Эмитент": _clean_identifier(item.get("Эмитент/Объект")),
                "ИНН": _clean_identifier(item.get("ИНН"), "ИНН"),
                "Рейтинг": rating,
                "Агентство": EXPERT_RA_SOURCE,
                "Прогноз": _clean_identifier(item.get("Прогноз")),
                "Дата рейтинга": item.get(
                    "Дата присвоения/актуализации/изменения рейтинга"
                ),
                "Предыдущий рейтинг": "",
                "Дата предыдущего рейтинга": "",
                "Источник": url or "https://raexpert.ru/ratings/",
                "Комментарий": "Автоматическая выгрузка с официального сайта агентства",
            }
        )

    result = pd.DataFrame(rows, columns=RATING_COLUMNS)
    if result.empty:
        raise ValueError("Экспорт «Эксперт РА» не содержит актуальных рейтингов")
    return result


def fetch_expert_ra_ratings(
    session: requests.Session | None = None,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    client = session or requests.Session()
    date_value = (as_of or datetime.now()).strftime("%d.%m.%Y")
    payload = {
        "Кредитные рейтинги": {
            "labels": [f"rating-{index}" for index in range(len(EXPERT_RA_PATHS))],
            "paths": EXPERT_RA_PATHS,
        }
    }
    response = client.post(
        EXPERT_RA_EXPORT_URL,
        params={"isSinglePage": 1, "virtual_date": date_value},
        json=payload,
        timeout=EXPERT_RA_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 bond-rating-pipeline/1.0"},
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    if "spreadsheet" not in content_type and not response.content.startswith(b"PK"):
        raise ValueError(
            "«Эксперт РА» вернул неожиданный формат вместо XLSX "
            f"({content_type or 'Content-Type отсутствует'})"
        )
    return parse_expert_ra_export(response.content)


def merge_rating_rows(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    existing = existing.reindex(columns=RATING_COLUMNS)
    fetched = fetched.reindex(columns=RATING_COLUMNS)
    if existing.empty:
        return fetched.reset_index(drop=True)

    def key(row: pd.Series) -> tuple[str, str, str]:
        return (
            _clean_identifier(row.get("Код ценной бумаги")).upper(),
            _clean_identifier(row.get("ИНН")),
            _clean_identifier(row.get("Агентство")).lower(),
        )

    manual_keys = {key(row) for _, row in existing.iterrows()}
    additions = [
        row for _, row in fetched.iterrows() if key(row) not in manual_keys
    ]
    if not additions:
        return existing.reset_index(drop=True)
    return pd.concat(
        [existing, pd.DataFrame(additions, columns=RATING_COLUMNS)],
        ignore_index=True,
    )


def enrich_issuer_identifiers(
    securities: pd.DataFrame,
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    result = securities.copy()
    if "ИНН" not in result.columns:
        result["ИНН"] = ""
    client = session or requests.Session()
    failures: list[str] = []

    for index, row in result.iterrows():
        if _clean_identifier(row.get("ИНН")):
            continue
        secid = _clean_identifier(row.get("Код ценной бумаги")).upper()
        if not secid:
            continue
        try:
            response = client.get(
                MOEX_SECURITIES_URL,
                params={
                    "q": secid,
                    "iss.meta": "off",
                    "securities.columns": "secid,emitent_title,emitent_inn",
                },
                timeout=MOEX_TIMEOUT,
                headers={"User-Agent": "bond-rating-pipeline/1.0"},
            )
            response.raise_for_status()
            block = response.json().get("securities", {})
            columns = block.get("columns", [])
            rows = block.get("data", [])
            if not rows or "secid" not in columns or "emitent_inn" not in columns:
                failures.append(secid)
                continue
            secid_index = columns.index("secid")
            inn_index = columns.index("emitent_inn")
            match = next(
                (
                    item
                    for item in rows
                    if str(item[secid_index]).strip().upper() == secid
                ),
                None,
            )
            inn = "" if match is None else _clean_identifier(match[inn_index])
            if inn:
                result.at[index, "ИНН"] = inn
            else:
                failures.append(secid)
        except (requests.RequestException, ValueError, KeyError, IndexError):
            failures.append(secid)

    return result, failures
