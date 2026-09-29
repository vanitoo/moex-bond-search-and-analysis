from __future__ import annotations

import html as html_lib
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Iterable
from xml.sax.saxutils import escape

import pandas as pd
import requests

from moex_bond_search_and_analysis.http_client import browser_headers, browser_session

CBR_SOAP_URL = "https://www.cbr.ru/CreditInfoWebServ/CreditOrgInfo.asmx"
CBR_TIMEOUT = 40
DEFAULT_BANK_CACHE_DAYS = 7
DEFAULT_BANK_DELAY_SECONDS = 0.4

BANK_COLUMNS = [
    "Эмитент", "ИНН", "Регномер ЦБ", "Внутренний код ЦБ", "Дата отчётности",
    "Н1.0", "Н1.1", "Н1.2", "Н2", "Н3", "Н4", "Источник", "Комментарий",
]


@dataclass(frozen=True)
class BankFetchStats:
    requested: int
    fetched: int
    cached: int
    not_found: int
    errors: tuple[str, ...]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[«»"'()]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace("\xa0", " ").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _soap_envelope(method: str, params_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
 <soap:Body>
  <{method} xmlns="http://web.cbr.ru/">{params_xml}</{method}>
 </soap:Body>
</soap:Envelope>"""


def _soap_call(
    client: requests.Session,
    method: str,
    params_xml: str,
) -> ET.Element:
    response = client.post(
        CBR_SOAP_URL,
        data=_soap_envelope(method, params_xml).encode("utf-8"),
        headers={
            **browser_headers(referer="https://www.cbr.ru/development/wsco/"),
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"http://web.cbr.ru/{method}"',
        },
        timeout=CBR_TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    result = next(
        (node for node in root.iter() if _local(node.tag) == f"{method}Result"),
        None,
    )
    if result is None:
        raise ValueError(f"ЦБ РФ: в SOAP-ответе {method} нет Result")
    if len(result):
        return result
    text = html_lib.unescape((result.text or "").strip())
    if not text:
        return result
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        wrapper = ET.Element("value")
        wrapper.text = text
        return wrapper


def _record(element: ET.Element) -> dict[str, str]:
    return {
        _local(child.tag): (child.text or "").strip()
        for child in list(element)
    }


def _pick(record: dict[str, str], *needles: str) -> str:
    for key, value in record.items():
        low = key.lower()
        if any(needle in low for needle in needles) and str(value).strip():
            return str(value).strip()
    return ""


def _search_query(name: str) -> str:
    text = re.sub(r"\b(пао|ао|ооо|нко)\b", " ", _norm(name))
    text = re.sub(r"\b(бо|пбо|р|p)\b[-\w]*", " ", text)
    text = re.sub(r"\b\d{3,}[a-zа-я0-9-]*\b", " ", text)
    text = re.sub(r"\b(001|002|003|004|005)[рp][-\w]*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Кредитный справочник лучше ищет короткую смысловую часть названия.
    return text[:80] or _norm(name)[:80]


def _name_score(query: str, candidate: str) -> float:
    q = set(re.findall(r"[a-zа-я0-9]+", _norm(query)))
    c = set(re.findall(r"[a-zа-я0-9]+", _norm(candidate)))
    if not q or not c:
        return 0.0
    common = q & c
    return len(common) / max(1, len(q))


def search_bank_identity(
    name: str,
    *,
    session: requests.Session | None = None,
) -> dict[str, str] | None:
    client = session or browser_session(trust_env=False)
    query = _search_query(name)
    root = _soap_call(
        client,
        "SearchByNameXML",
        f"<NamePart>{escape(query)}</NamePart>",
    )
    records = [_record(node) for node in root.iter() if _local(node.tag) == "CO"]
    if not records:
        # Некоторые версии сервиса возвращают записи под другим именем.
        records = [_record(node) for node in root.iter() if len(node) >= 2]

    candidates: list[tuple[float, dict[str, str], str, str, str]] = []
    for record in records:
        bank_name = _pick(record, "name", "cname", "org")
        regnum = _pick(record, "regnum", "regnumber", "reg_num")
        intcode = _pick(record, "intcode", "internalcode", "int_code")
        if not bank_name:
            continue
        candidates.append((_name_score(query, bank_name), record, bank_name, regnum, intcode))
    if not candidates:
        return None
    score, _, bank_name, regnum, intcode = max(candidates, key=lambda item: item[0])
    if score <= 0:
        return None
    return {
        "name": bank_name,
        "regnum": re.sub(r"\D", "", regnum),
        "intcode": re.sub(r"\D", "", intcode),
    }


def _dates_for_f135(
    credorg_number: str,
    client: requests.Session,
) -> list[str]:
    root = _soap_call(
        client,
        "GetDatesForF135",
        f"<CredprgNumber>{escape(str(credorg_number))}</CredprgNumber>",
    )
    dates: list[pd.Timestamp] = []
    for node in root.iter():
        if _local(node.tag).lower() != "datetime":
            continue
        value = pd.to_datetime(node.text, errors="coerce")
        if not pd.isna(value):
            dates.append(value)
    return [value.strftime("%Y-%m-%d") for value in sorted(set(dates), reverse=True)]


def _normalize_ratio_code(value: Any) -> str:
    text = str(value or "").upper().replace("H", "Н").replace(" ", "")
    match = re.search(r"Н(?:1\.[012]|[234])", text)
    return match.group(0) if match else ""


def _parse_f135_records(root: ET.Element) -> dict[str, float]:
    result: dict[str, float] = {}
    rows = [node for node in root.iter() if _local(node.tag) == "F135_2"]
    if not rows:
        rows = [node for node in root.iter() if len(node) >= 2]
    for node in rows:
        values = _record(node)
        code = ""
        code_key = ""
        for key, value in values.items():
            candidate = _normalize_ratio_code(value)
            if candidate:
                code, code_key = candidate, key
                break
        if not code:
            continue

        # В разных версиях формы имена XML-полей менялись. Сначала предпочитаем
        # фактическое значение, затем первый числовой столбец после кода.
        preferred = [
            value for key, value in values.items()
            if key != code_key and any(token in key.lower() for token in ("fact", "value", "znach", "c2"))
        ]
        numeric = next((_number(value) for value in preferred if _number(value) is not None), None)
        if numeric is None:
            numeric = next(
                (_number(value) for key, value in values.items() if key != code_key and _number(value) is not None),
                None,
            )
        if numeric is not None:
            result[code] = numeric
    return result


class _SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif low == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _parse_f135_html(content: str) -> dict[str, float]:
    ratios: dict[str, float] = {}
    parser = _SimpleTableParser()
    parser.feed(content)

    code_index: int | None = None
    fact_index: int | None = None
    for row in parser.rows:
        lowered = [cell.lower() for cell in row]
        if code_index is None:
            code_index = next(
                (i for i, cell in enumerate(lowered) if "наименование" in cell or "норматив" in cell),
                None,
            )
            fact_index = next(
                (i for i, cell in enumerate(lowered) if "фактичес" in cell),
                None,
            )
            if code_index is not None and fact_index is not None:
                continue
        if code_index is None or fact_index is None:
            continue
        if max(code_index, fact_index) >= len(row):
            continue
        code = _normalize_ratio_code(row[code_index])
        value = _number(row[fact_index])
        if code and value is not None:
            ratios[code] = value
    return ratios


def fetch_bank_metrics(
    issuer_name: str,
    *,
    inn: str = "",
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    client = session or browser_session(trust_env=False)
    identity = search_bank_identity(issuer_name, session=client)
    if not identity:
        return None

    numbers = [value for value in (identity.get("regnum"), identity.get("intcode")) if value]
    dates: list[str] = []
    used_number = ""
    for number in numbers:
        try:
            dates = _dates_for_f135(number, client)
        except (requests.RequestException, ValueError, ET.ParseError):
            dates = []
        if dates:
            used_number = number
            break
    if not dates:
        return None

    report_date = dates[0]
    ratios: dict[str, float] = {}
    source = ""

    # Публичная HTML-форма удобна тем, что содержит уже подписанные нормативы.
    regnum = identity.get("regnum") or used_number
    if regnum:
        url = (
            "https://www.cbr.ru/banking_sector/credit/coinfo/f135/2151"
            f"?dt={report_date}&regnum={regnum}"
        )
        try:
            response = client.get(url, timeout=CBR_TIMEOUT)
            response.raise_for_status()
            ratios = _parse_f135_html(response.text)
            if ratios:
                source = url
        except requests.RequestException:
            pass

    if not ratios:
        root = _soap_call(
            client,
            "Data135FormFullXML",
            f"<CredorgNumber>{escape(used_number)}</CredorgNumber>"
            f"<OnDate>{report_date}T00:00:00</OnDate>",
        )
        ratios = _parse_f135_records(root)
        source = CBR_SOAP_URL

    if not ratios:
        return None
    return {
        "Эмитент": identity.get("name") or issuer_name,
        "ИНН": re.sub(r"\D", "", str(inn or "")),
        "Регномер ЦБ": identity.get("regnum") or "",
        "Внутренний код ЦБ": identity.get("intcode") or "",
        "Дата отчётности": report_date,
        "Н1.0": ratios.get("Н1.0"),
        "Н1.1": ratios.get("Н1.1"),
        "Н1.2": ratios.get("Н1.2"),
        "Н2": ratios.get("Н2"),
        "Н3": ratios.get("Н3"),
        "Н4": ratios.get("Н4"),
        "Источник": source,
        "Комментарий": "Автоматически из формы 0409135 Банка России",
    }


def _cache_key(inn: str, name: str) -> str:
    digits = re.sub(r"\D", "", str(inn or ""))
    if digits:
        return digits
    return re.sub(r"[^a-zа-я0-9]+", "_", _norm(name)).strip("_")[:80] or "bank"


def _load_cache(cache_dir: Path, key: str, cache_days: int) -> dict[str, Any] | None:
    path = cache_dir / f"{key}.json"
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


def _save_cache(cache_dir: Path, key: str, row: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.json").write_text(
        json.dumps(
            {"fetched_at": datetime.now().isoformat(timespec="seconds"), "row": row},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def fetch_bank_metrics_for_issuers(
    issuers: Iterable[dict[str, str]],
    *,
    cache_dir: Path,
    cache_days: int = DEFAULT_BANK_CACHE_DAYS,
    delay_seconds: float = DEFAULT_BANK_DELAY_SECONDS,
) -> tuple[pd.DataFrame, BankFetchStats]:
    unique: dict[str, dict[str, str]] = {}
    for item in issuers:
        name = str(item.get("name") or "").strip()
        inn = re.sub(r"\D", "", str(item.get("inn") or ""))
        if not name:
            continue
        unique[_cache_key(inn, name)] = {"name": name, "inn": inn}

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    fetched = cached = not_found = 0

    for key, item in unique.items():
        row = _load_cache(cache_dir, key, cache_days)
        if row is not None:
            rows.append(row)
            cached += 1
            continue
        try:
            row = fetch_bank_metrics(item["name"], inn=item["inn"])
            if row is None:
                not_found += 1
            else:
                rows.append(row)
                fetched += 1
                _save_cache(cache_dir, key, row)
        except Exception as exc:
            errors.append(f"{item['name']}: {exc}")
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return (
        pd.DataFrame(rows, columns=BANK_COLUMNS),
        BankFetchStats(len(unique), fetched, cached, not_found, tuple(errors)),
    )


def score_bank_metrics(row: pd.Series | None) -> tuple[int, list[str], list[str], bool, int]:
    """Возвращает score 0..30, плюсы, риски, hard_stop, полноту 0..10."""
    if row is None:
        return 0, [], [], False, 0

    values = {code: _number(row.get(code)) for code in ("Н1.0", "Н1.1", "Н1.2", "Н2", "Н3", "Н4")}
    available = sum(value is not None for value in values.values())
    completeness = round(10 * available / 6)
    score = 0
    positives: list[str] = []
    risks: list[str] = []
    hard_stop = False

    def min_ratio(code: str, value: float | None, minimum: float, good: float, points: int) -> None:
        nonlocal score, hard_stop
        if value is None:
            return
        if value < minimum:
            risks.append(f"{code}={value:.2f}% ниже базового регуляторного порога {minimum:.1f}%")
            hard_stop = True
        elif value >= good:
            score += points
            positives.append(f"{code} с запасом: {value:.2f}%")
        else:
            score += max(1, points // 2)

    min_ratio("Н1.0", values["Н1.0"], 8.0, 12.0, 8)
    min_ratio("Н1.1", values["Н1.1"], 4.5, 7.0, 5)
    min_ratio("Н1.2", values["Н1.2"], 6.0, 9.0, 5)
    min_ratio("Н2", values["Н2"], 15.0, 30.0, 4)
    min_ratio("Н3", values["Н3"], 50.0, 80.0, 4)

    n4 = values["Н4"]
    if n4 is not None:
        if n4 > 120.0:
            risks.append(f"Н4={n4:.2f}% выше базового регуляторного порога 120%")
            hard_stop = True
        elif n4 <= 100.0:
            score += 4
            positives.append(f"Н4 с запасом: {n4:.2f}%")
        else:
            score += 2

    return min(30, score), positives, risks, hard_stop, completeness
