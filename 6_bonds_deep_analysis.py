# 🔎 Второй слой анализа облигаций
#
# Вход: последний bond_analysis_YYYY-MM-DD.xlsx, созданный скриптом №5.
# Выход:
#   - bond_deep_analysis_YYYY-MM-DD.xlsx
#   - bond_deep_analysis_YYYY-MM-DD.html
#
# Скрипт повторно не перебирает весь рынок. Он обогащает уже отобранные выпуски
# данными MOEX ISS, проверяет структуру выпуска и локальные файлы новостей.
# Это риск-фильтр перед ручным решением, а не гарантия платёжеспособности эмитента.

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import pandas as pd
import requests


MOEX_BASE = "https://iss.moex.com/iss"
REQUEST_DELAY = 1.25
REQUEST_TIMEOUT = 30

REQUIRED_COLUMNS = {
    "Полное наименование",
    "Код ценной бумаги",
    "Цена, %",
    "Доходность",
    "Дюрация, месяцев",
    "Объем сделок с 15 дней, шт.",
    "Оценка, 0-100",
}

DANGER_PATTERNS: dict[str, tuple[str, ...]] = {
    "Дефолт или просрочка": (
        "дефолт", "технический дефолт", "не выплат", "невыплат", "просроч",
        "не исполнил обязатель", "неисполнение обязатель", "задержка купона",
    ),
    "Банкротство": (
        "банкрот", "несостоятельн", "заявление о признании", "наблюдение введено",
        "конкурсное производство",
    ),
    "Снижение рейтинга": (
        "снизил рейтинг", "понизил рейтинг", "негативный прогноз", "рейтинг отозван",
        "отозвало рейтинг",
    ),
    "Судебные или регуляторные риски": (
        "арест актив", "блокировк счет", "уголовное дело", "обыск", "отзыв лицензии",
        "налоговые претенз", "иск на сумму",
    ),
    "Финансовое ухудшение": (
        "чистый убыток", "убыток вырос", "выручка снизилась", "падение выручки",
        "долговая нагрузка выросла", "реструктуризация долга", "нарушение ковенант",
    ),
}

POSITIVE_PATTERNS: dict[str, tuple[str, ...]] = {
    "Повышение рейтинга": ("повысил рейтинг", "рейтинг повышен", "позитивный прогноз"),
    "Подтверждение рейтинга": ("подтвердил рейтинг", "рейтинг подтвержден"),
    "Исполнение обязательств": ("выплатил купон", "погасил облигац", "исполнил обязательства"),
}


@dataclass
class IssueData:
    secid: str
    shortname: str = ""
    isin: str = ""
    regnumber: str = ""
    face_value: float | None = None
    face_unit: str = ""
    maturity_date: str = ""
    offer_date: str = ""
    coupon_percent: float | None = None
    coupon_value: float | None = None
    coupon_period: int | None = None
    issue_size: float | None = None
    qualified: str = ""
    next_coupon_date: str = ""
    future_coupons: int = 0
    unknown_future_coupons: int = 0
    future_amortizations: int = 0
    amortization_before_maturity: bool = False
    source_errors: list[str] = field(default_factory=list)


@dataclass
class DeepResult:
    market_score: int
    structure_score: int
    news_score: int
    completeness_score: int
    penalty: int
    final_score: int
    recommendation: str
    recommendation_class: str
    risk_level: str
    max_share: str
    confidence: str
    hard_stop: bool
    positives: list[str]
    risks: list[str]
    missing: list[str]
    news_flags: list[str]


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    return int(number) if number is not None else None


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return pd.to_datetime(value, errors="raise").date()
    except (ValueError, TypeError, OverflowError):
        return None


def fmt_number(value: Any, digits: int = 2) -> str:
    number = safe_float(value)
    if number is None:
        return "—"
    return f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip()


def moex_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{MOEX_BASE}/{path.lstrip('/')}"
    merged = {"iss.meta": "off"}
    if params:
        merged.update(params)
    time.sleep(REQUEST_DELAY)
    response = requests.get(url, params=merged, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def block_rows(payload: dict[str, Any], block: str) -> list[dict[str, Any]]:
    section = payload.get(block) or {}
    columns = section.get("columns") or []
    rows = section.get("data") or []
    return [dict(zip(columns, row)) for row in rows]


def first_value(rows: Iterable[dict[str, Any]], *keys: str) -> Any:
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
    return None


def fetch_issue_data(secid: str) -> IssueData:
    result = IssueData(secid=secid)

    try:
        payload = moex_get(
            f"securities/{quote(secid)}.json",
            {"iss.only": "description,boards", "description.columns": "name,title,value,type,sort_order"},
        )
        description_rows = block_rows(payload, "description")
        description = {str(row.get("name")): row.get("value") for row in description_rows}

        result.shortname = str(description.get("SHORTNAME") or description.get("NAME") or "")
        result.isin = str(description.get("ISIN") or "")
        result.regnumber = str(description.get("REGNUMBER") or "")
        result.face_value = safe_float(description.get("FACEVALUE"))
        result.face_unit = str(description.get("FACEUNIT") or "")
        result.maturity_date = str(description.get("MATDATE") or description.get("MATURITYDATE") or "")
        result.offer_date = str(description.get("OFFERDATE") or "")
        result.coupon_percent = safe_float(description.get("COUPONPERCENT"))
        result.coupon_value = safe_float(description.get("COUPONVALUE"))
        result.coupon_period = safe_int(description.get("COUPONPERIOD"))
        result.issue_size = safe_float(description.get("ISSUESIZE"))
        result.qualified = str(description.get("ISQUALIFIEDINVESTORS") or "")
        result.next_coupon_date = str(description.get("NEXTCOUPON") or "")
    except Exception as exc:  # network/source errors are recorded per issue
        result.source_errors.append(f"Описание выпуска: {exc}")

    try:
        payload = moex_get(
            f"statistics/engines/stock/markets/bonds/bondization/{quote(secid)}.json",
            {"iss.only": "coupons,amortizations,offers"},
        )
        coupons = block_rows(payload, "coupons")
        amortizations = block_rows(payload, "amortizations")
        offers = block_rows(payload, "offers")
        today = date.today()

        future_coupons = []
        for row in coupons:
            coupon_date = parse_date(row.get("coupondate") or row.get("COUPONDATE"))
            if coupon_date and coupon_date >= today:
                future_coupons.append(row)
        result.future_coupons = len(future_coupons)
        result.unknown_future_coupons = sum(
            1
            for row in future_coupons
            if safe_float(row.get("value") or row.get("VALUE")) is None
            and safe_float(row.get("valueprc") or row.get("VALUEPRC")) is None
        )

        maturity = parse_date(result.maturity_date)
        future_amortizations = []
        for row in amortizations:
            amort_date = parse_date(row.get("amortdate") or row.get("AMORTDATE"))
            if amort_date and amort_date >= today:
                future_amortizations.append((amort_date, row))
        result.future_amortizations = len(future_amortizations)
        result.amortization_before_maturity = bool(
            maturity and any(amort_date < maturity for amort_date, _ in future_amortizations)
        )

        future_offers: list[date] = []
        for row in offers:
            offer_date = parse_date(
                row.get("offerdate") or row.get("OFFERDATE") or row.get("enddate") or row.get("ENDDATE")
            )
            if offer_date and offer_date >= today:
                future_offers.append(offer_date)
        if future_offers:
            result.offer_date = min(future_offers).isoformat()
    except Exception as exc:
        result.source_errors.append(f"График платежей: {exc}")

    return result


def find_latest_analysis_file(directory: Path) -> Path:
    candidates = [
        path for path in directory.glob("bond_analysis_*.xlsx")
        if not path.name.startswith("~$") and "deep" not in path.name
    ]
    if not candidates:
        raise FileNotFoundError(
            "Не найден bond_analysis_YYYY-MM-DD.xlsx. Сначала запустите скрипт №5."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_analysis(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Анализ")
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError("Во входном файле отсутствуют колонки: " + ", ".join(sorted(missing)))
    return df.dropna(subset=["Код ценной бумаги"]).copy()


def news_files(directory: Path) -> list[Path]:
    patterns = ("**/*.txt", "**/*.md", "**/*.json")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(directory.glob(pattern))
    return [
        path for path in files
        if any(marker in normalize(str(path.parent)) for marker in ("news", "новост"))
        and path.stat().st_size <= 5_000_000
    ]


def load_news_text(secid: str, issue_name: str, root: Path) -> tuple[str, list[str]]:
    tokens = {normalize(secid)}
    name_words = [word for word in re.findall(r"[a-zа-я0-9]+", normalize(issue_name)) if len(word) >= 5]
    tokens.update(name_words[:4])
    matched: list[str] = []
    chunks: list[str] = []

    for path in news_files(root):
        path_text = normalize(path.name)
        if not any(token and token in path_text for token in tokens):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matched.append(str(path))
        chunks.append(text)
    return "\n".join(chunks), matched


def scan_news(text: str) -> tuple[list[str], list[str]]:
    normalized = normalize(text)
    dangers = [label for label, markers in DANGER_PATTERNS.items() if any(m in normalized for m in markers)]
    positives = [label for label, markers in POSITIVE_PATTERNS.items() if any(m in normalized for m in markers)]
    return dangers, positives


def qualification_required(value: Any) -> bool:
    text = normalize(value)
    if not text:
        return False
    return text not in {"0", "нет", "false", "n", "no"} and "не требуется" not in text


def analyze(row: pd.Series, issue: IssueData, news_text: str, news_sources: list[str]) -> DeepResult:
    market_score = int(round(safe_float(row.get("Оценка, 0-100")) or 0))
    positives: list[str] = []
    risks: list[str] = []
    missing: list[str] = []
    penalty = 0
    structure_score = 0
    news_score = 10
    hard_stop = False

    maturity = parse_date(issue.maturity_date)
    offer = parse_date(issue.offer_date)
    today = date.today()

    if maturity:
        days_to_maturity = (maturity - today).days
        if days_to_maturity <= 0:
            risks.append("Дата погашения уже наступила или некорректна")
            hard_stop = True
        elif days_to_maturity <= 730:
            structure_score += 12
            positives.append("Погашение в пределах двух лет")
        else:
            structure_score += 8
            risks.append("До погашения более двух лет")
    else:
        missing.append("Дата погашения")

    if offer:
        if offer <= today:
            risks.append("Дата оферты уже наступила — условия нужно проверить вручную")
            penalty += 8
        else:
            structure_score += 4
            risks.append(f"Есть оферта {offer.strftime('%d.%m.%Y')}; доходность нужно считать до неё")
    else:
        structure_score += 6
        positives.append("Ближайшая оферта в данных MOEX не обнаружена")

    if issue.future_coupons == 0:
        missing.append("Будущие купоны")
    elif issue.unknown_future_coupons == 0:
        structure_score += 12
        positives.append("Значения будущих купонов известны")
    else:
        risks.append(f"Неизвестны значения {issue.unknown_future_coupons} будущих купонов")
        penalty += min(18, 6 + issue.unknown_future_coupons * 2)

    if issue.amortization_before_maturity:
        structure_score += 4
        risks.append("Выпуск амортизационный: денежный поток и доходность нужно проверять по датам")
    else:
        structure_score += 6
        positives.append("Досрочная амортизация номинала не обнаружена")

    if issue.face_value is not None:
        structure_score += 3
    else:
        missing.append("Номинал")

    if issue.issue_size is not None:
        structure_score += 3
        if issue.issue_size < 500_000_000:
            risks.append("Небольшой объём выпуска может ухудшать ликвидность")
            penalty += 4
    else:
        missing.append("Объём выпуска")

    qualified = qualification_required(row.get("Нужна квалификация?")) or qualification_required(issue.qualified)
    if qualified:
        risks.append("Выпуск предназначен для квалифицированных инвесторов")
        penalty += 5
    else:
        positives.append("Ограничение для квалифицированных инвесторов не выявлено")

    dangers, news_positives = scan_news(news_text)
    news_flags = list(dangers)
    if not news_sources:
        missing.append("Локальные новости эмитента")
        news_score = 3
    elif dangers:
        news_score = max(0, 10 - 4 * len(dangers))
        risks.extend(f"Новостной сигнал: {flag}" for flag in dangers)
        penalty += min(35, 10 * len(dangers))
    else:
        positives.append("В локальных новостях жёсткие стоп-сигналы не найдены")

    positives.extend(f"Позитивный новостной сигнал: {flag}" for flag in news_positives)
    news_score = min(10, news_score + min(3, len(news_positives)))

    if any(flag in dangers for flag in ("Дефолт или просрочка", "Банкротство")):
        hard_stop = True

    if issue.source_errors:
        missing.extend(issue.source_errors)

    required_checks = 8
    available_checks = required_checks - min(required_checks, len(missing))
    completeness_score = round(20 * available_checks / required_checks)

    # Второй слой: первый балл имеет вес 40%, структура выпуска 30%, новости 10%, полнота 20%.
    structure_normalized = min(30, round(structure_score * 30 / 46))
    final_score = round(market_score * 0.40 + structure_normalized + news_score + completeness_score - penalty)
    final_score = max(0, min(100, final_score))

    if hard_stop:
        recommendation, recommendation_class = "Не покупать", "avoid"
        final_score = min(final_score, 25)
    elif len(missing) >= 5:
        recommendation, recommendation_class = "Недостаточно данных", "missing"
        final_score = min(final_score, 49)
    elif final_score >= 80:
        recommendation, recommendation_class = "Рассматривать к покупке", "buy"
    elif final_score >= 68:
        recommendation, recommendation_class = "Рассматривать", "consider"
    elif final_score >= 55:
        recommendation, recommendation_class = "Только небольшой долей", "small"
    elif final_score >= 42:
        recommendation, recommendation_class = "Ждать и проверить вручную", "wait"
    else:
        recommendation, recommendation_class = "Не покупать", "avoid"

    if hard_stop or final_score < 42:
        risk_level, max_share = "Высокий", "0%"
    elif final_score < 55:
        risk_level, max_share = "Повышенный", "до 1%"
    elif final_score < 68:
        risk_level, max_share = "Умеренно высокий", "до 2%"
    elif final_score < 80:
        risk_level, max_share = "Умеренный", "до 3%"
    else:
        risk_level, max_share = "Умеренный по доступным данным", "до 5%"

    if completeness_score >= 17 and news_sources and not issue.source_errors:
        confidence = "Высокая"
    elif completeness_score >= 12:
        confidence = "Средняя"
    else:
        confidence = "Низкая"

    return DeepResult(
        market_score=market_score,
        structure_score=structure_normalized,
        news_score=news_score,
        completeness_score=completeness_score,
        penalty=penalty,
        final_score=final_score,
        recommendation=recommendation,
        recommendation_class=recommendation_class,
        risk_level=risk_level,
        max_share=max_share,
        confidence=confidence,
        hard_stop=hard_stop,
        positives=positives,
        risks=risks,
        missing=missing,
        news_flags=news_flags,
    )


def build_deep_analysis(df: pd.DataFrame, root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = len(df)

    for index, (_, source) in enumerate(df.iterrows(), start=1):
        secid = str(source["Код ценной бумаги"]).strip()
        name = str(source["Полное наименование"]).strip()
        print(f"[{index}/{total}] Получение расширенных данных: {name} ({secid})")

        issue = fetch_issue_data(secid)
        news_text, sources = load_news_text(secid, name, root)
        result = analyze(source, issue, news_text, sources)

        rows.append({
            "Полное наименование": name,
            "Код ценной бумаги": secid,
            "ISIN": issue.isin,
            "Регистрационный номер": issue.regnumber,
            "Цена, %": source.get("Цена, %"),
            "Доходность": source.get("Доходность"),
            "Дюрация, месяцев": source.get("Дюрация, месяцев"),
            "Объем сделок с 15 дней, шт.": source.get("Объем сделок с 15 дней, шт."),
            "Первичный балл": result.market_score,
            "Баллы структуры выпуска": result.structure_score,
            "Баллы новостей": result.news_score,
            "Полнота данных": result.completeness_score,
            "Штрафы": result.penalty,
            "Итоговый балл": result.final_score,
            "Решение": result.recommendation,
            "Уровень риска": result.risk_level,
            "Максимальная доля": result.max_share,
            "Уверенность": result.confidence,
            "Жёсткий стоп": "ДА" if result.hard_stop else "НЕТ",
            "Дата погашения": issue.maturity_date,
            "Дата оферты": issue.offer_date,
            "Номинал": issue.face_value,
            "Валюта номинала": issue.face_unit,
            "Купон, %": issue.coupon_percent,
            "Купон, сумма": issue.coupon_value,
            "Период купона, дней": issue.coupon_period,
            "Будущих купонов": issue.future_coupons,
            "Купонов с неизвестной суммой": issue.unknown_future_coupons,
            "Будущих амортизаций": issue.future_amortizations,
            "Амортизация до погашения": "ДА" if issue.amortization_before_maturity else "НЕТ",
            "Объём выпуска": issue.issue_size,
            "Положительные факторы": "; ".join(result.positives) or "—",
            "Риски": "; ".join(result.risks) or "Явные риски не обнаружены",
            "Недостающие данные": "; ".join(result.missing) or "—",
            "Новостные стоп-сигналы": "; ".join(result.news_flags) or "Не обнаружены",
            "Источники локальных новостей": "; ".join(sources) or "Не найдены",
            "_class": result.recommendation_class,
        })

    return pd.DataFrame(rows).sort_values(
        by=["Итоговый балл", "Первичный балл", "Доходность"], ascending=[False, False, False]
    ).reset_index(drop=True)


def write_excel(df: pd.DataFrame, output_path: Path, input_path: Path) -> None:
    methodology = pd.DataFrame({
        "Блок": [
            "Назначение", "Рыночный слой", "Структура выпуска", "Новости",
            "Полнота данных", "Жёсткие стопы", "Ограничение", "Исходный файл",
        ],
        "Описание": [
            "Второй риск-фильтр после скрипта №5.",
            "40% итоговой оценки берётся из первичного рыночного балла.",
            "До 30 баллов: погашение, оферта, купоны, амортизация, номинал и объём выпуска.",
            "До 10 баллов. Анализируются только локально сохранённые файлы новостей.",
            "До 20 баллов. Неполные или недоступные сведения понижают уверенность.",
            "Дефолт, просрочка или банкротство автоматически дают решение «Не покупать».",
            "Скрипт не заменяет анализ отчётности, официальных сообщений и кредитных рейтингов.",
            input_path.name,
        ],
    })
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.drop(columns=["_class"]).to_excel(writer, sheet_name="Глубокий анализ", index=False)
        methodology.to_excel(writer, sheet_name="Методика", index=False)
        sheet = writer.book["Глубокий анализ"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cells in sheet.columns:
            width = min(70, max(len(str(cell.value or "")) for cell in cells) + 2)
            sheet.column_dimensions[cells[0].column_letter].width = width


def list_html(text: str, css_class: str = "") -> str:
    items = [item.strip() for item in str(text or "").split(";") if item.strip() and item.strip() != "—"]
    if not items:
        return "<div class='muted'>Нет данных</div>"
    return f"<ul class='{css_class}'>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def write_html(df: pd.DataFrame, output_path: Path, input_path: Path) -> None:
    cards: list[str] = []
    for _, row in df.iterrows():
        css = str(row["_class"])
        secid = html.escape(str(row["Код ценной бумаги"]))
        moex_url = f"https://www.moex.com/ru/issue.aspx?board=TQCB&code={quote(str(row['Код ценной бумаги']))}"
        cards.append(f"""
        <article class="bond-card {css}" data-class="{css}">
          <div class="head">
            <div><h2>{html.escape(str(row['Полное наименование']))}</h2>
              <a href="{moex_url}" target="_blank" rel="noopener">{secid} · открыть на MOEX</a></div>
            <div class="score">{int(row['Итоговый балл'])}<small>/100</small></div>
          </div>
          <div class="decision"><span class="badge {css}">{html.escape(str(row['Решение']))}</span>
            <span>Риск: <b>{html.escape(str(row['Уровень риска']))}</b></span>
            <span>Лимит: <b>{html.escape(str(row['Максимальная доля']))}</b></span>
            <span>Уверенность: <b>{html.escape(str(row['Уверенность']))}</b></span></div>
          <div class="metrics">
            <div><small>Первичный балл</small><b>{int(row['Первичный балл'])}</b></div>
            <div><small>Структура</small><b>{int(row['Баллы структуры выпуска'])}/30</b></div>
            <div><small>Новости</small><b>{int(row['Баллы новостей'])}/10</b></div>
            <div><small>Полнота</small><b>{int(row['Полнота данных'])}/20</b></div>
            <div><small>Доходность</small><b>{fmt_number(row['Доходность'])}%</b></div>
            <div><small>Погашение</small><b>{html.escape(str(row['Дата погашения'] or '—'))}</b></div>
            <div><small>Оферта</small><b>{html.escape(str(row['Дата оферты'] or '—'))}</b></div>
            <div><small>Неизвестных купонов</small><b>{int(row['Купонов с неизвестной суммой'])}</b></div>
          </div>
          <div class="columns">
            <section><h3>Плюсы</h3>{list_html(row['Положительные факторы'], 'positive')}</section>
            <section><h3>Риски</h3>{list_html(row['Риски'], 'negative')}</section>
            <section><h3>Не хватает данных</h3>{list_html(row['Недостающие данные'])}</section>
          </div>
        </article>""")

    counts = df["Решение"].value_counts().to_dict()
    generated = datetime.now().strftime("%d.%m.%Y в %H:%M:%S")
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Глубокий анализ облигаций</title>
<style>
:root{{--bg:#f3f5f8;--card:#fff;--text:#17202a;--muted:#667085;--line:#e4e7ec;--blue:#175cd3}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:Arial,sans-serif}}
main{{max-width:1450px;margin:auto;padding:28px}} h1{{margin:0 0 6px}} .subtitle,.muted{{color:var(--muted)}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}} .summary div,.bond-card{{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 1px 2px #1018280d}}
.summary div{{padding:16px}} .summary small{{display:block;color:var(--muted);margin-bottom:7px}} .summary b{{font-size:25px}}
.filters{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}} button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:9px 13px;cursor:pointer}}button.active{{background:#17202a;color:#fff}}
.bond-card{{padding:20px;margin-bottom:16px;border-left:6px solid #98a2b3}} .bond-card.buy{{border-left-color:#12b76a}}.bond-card.consider{{border-left-color:#2e90fa}}.bond-card.small{{border-left-color:#f79009}}.bond-card.wait{{border-left-color:#fdb022}}.bond-card.avoid{{border-left-color:#f04438}}.bond-card.missing{{border-left-color:#7f56d9}}
.head{{display:flex;justify-content:space-between;gap:15px}}h2{{margin:0 0 5px;font-size:21px}}a{{color:var(--blue);text-decoration:none}}.score{{font-size:34px;font-weight:800}}.score small{{font-size:14px;color:var(--muted)}}
.decision{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:15px 0}}.badge{{padding:7px 10px;border-radius:999px;font-weight:700;background:#eef2f6}}.badge.buy{{background:#ecfdf3;color:#027a48}}.badge.consider{{background:#eff8ff;color:#175cd3}}.badge.small,.badge.wait{{background:#fffaeb;color:#b54708}}.badge.avoid{{background:#fef3f2;color:#b42318}}.badge.missing{{background:#f4f3ff;color:#5925dc}}
.metrics{{display:grid;grid-template-columns:repeat(8,minmax(110px,1fr));gap:8px;background:#f9fafb;border-radius:10px;padding:12px}}.metrics div{{border-right:1px solid var(--line);padding:4px 8px}}.metrics div:last-child{{border:0}}.metrics small{{display:block;color:var(--muted);margin-bottom:5px}}.columns{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:14px}}h3{{font-size:15px;margin:0 0 8px}}ul{{margin:0;padding-left:20px;line-height:1.5}}.positive li::marker{{color:#12b76a}}.negative li::marker{{color:#f04438}}
.notice{{background:#fffaeb;border:1px solid #fedf89;padding:13px;border-radius:10px;margin:16px 0;line-height:1.45}}
@media(max-width:1000px){{.metrics{{grid-template-columns:repeat(4,1fr)}}.columns{{grid-template-columns:1fr}}}}@media(max-width:650px){{main{{padding:14px}}.summary{{grid-template-columns:repeat(2,1fr)}}.metrics{{grid-template-columns:repeat(2,1fr)}}.head{{display:block}}}}
</style></head><body><main>
<h1>Второй слой анализа облигаций</h1><div class="subtitle">Сформирован {generated} из {html.escape(input_path.name)}</div>
<div class="notice"><b>Важно:</b> это автоматический риск-фильтр. Он проверяет структуру выпуска по MOEX и локально сохранённые новости, но пока не анализирует бухгалтерскую отчётность и не подтверждает кредитные рейтинги по официальным источникам.</div>
<section class="summary"><div><small>Всего выпусков</small><b>{len(df)}</b></div><div><small>Рассматривать к покупке</small><b>{counts.get('Рассматривать к покупке',0)}</b></div><div><small>Не покупать</small><b>{counts.get('Не покупать',0)}</b></div><div><small>Недостаточно данных</small><b>{counts.get('Недостаточно данных',0)}</b></div></section>
<div class="filters"><button class="active" data-filter="all">Все</button><button data-filter="buy">К покупке</button><button data-filter="consider">Рассматривать</button><button data-filter="small">Небольшой долей</button><button data-filter="wait">Ждать</button><button data-filter="avoid">Не покупать</button><button data-filter="missing">Мало данных</button></div>
{''.join(cards)}
<script>document.querySelectorAll('button[data-filter]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');let f=b.dataset.filter;document.querySelectorAll('.bond-card').forEach(c=>c.style.display=(f==='all'||c.dataset.class===f)?'block':'none')}});</script>
</main></body></html>"""
    output_path.write_text(page, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Второй слой анализа облигаций")
    parser.add_argument("--input", type=Path, help="Путь к bond_analysis_YYYY-MM-DD.xlsx")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Корень проекта для поиска локальных новостей")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_path = args.input or find_latest_analysis_file(Path.cwd())
        print(f"Исходный файл: {input_path}")
        source = load_analysis(input_path)
        result = build_deep_analysis(source, args.root)
        report_date = datetime.now().strftime("%Y-%m-%d")
        excel_path = Path(f"bond_deep_analysis_{report_date}.xlsx")
        html_path = Path(f"bond_deep_analysis_{report_date}.html")
        write_excel(result, excel_path, input_path)
        write_html(result, html_path, input_path)
        print(f"\nГотово: {excel_path}")
        print(f"Готово: {html_path}")
        return 0
    except KeyboardInterrupt:
        print("\nОперация прервана пользователем.")
        return 130
    except Exception as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
