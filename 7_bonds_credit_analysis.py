# 🧾 Третий слой анализа облигаций: рейтинг и финансовое состояние эмитента
#
# Вход: последний bond_deep_analysis_YYYY-MM-DD.xlsx, созданный скриптом №6.
# Дополнительные источники (необязательные):
#   data/issuer_ratings.xlsx или .csv
#   data/issuer_financials.xlsx или .csv
#
# При первом запуске отсутствующие шаблоны создаются автоматически.
# Выход:
#   bond_credit_analysis_YYYY-MM-DD.xlsx
#   bond_credit_analysis_YYYY-MM-DD.html

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


RATING_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Рейтинг", "Агентство",
    "Прогноз", "Дата рейтинга", "Предыдущий рейтинг", "Дата предыдущего рейтинга",
    "Источник", "Комментарий",
]

FINANCIAL_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Период", "Валюта",
    "Выручка", "EBITDA", "Чистая прибыль", "Операционный денежный поток",
    "Денежные средства", "Общий долг", "Краткосрочный долг",
    "Процентные расходы", "Собственный капитал", "Оборотные активы",
    "Краткосрочные обязательства", "Источник", "Комментарий",
]

REQUIRED_DEEP_COLUMNS = {
    "Полное наименование", "Код ценной бумаги", "Итоговый балл", "Решение",
    "Жёсткий стоп", "Доходность", "Риски", "Недостающие данные",
}

RATING_POINTS = {
    "AAA": 30, "AA+": 28, "AA": 27, "AA-": 25,
    "A+": 23, "A": 21, "A-": 19,
    "BBB+": 17, "BBB": 15, "BBB-": 13,
    "BB+": 10, "BB": 8, "BB-": 6,
    "B+": 4, "B": 2, "B-": 1,
    "CCC": 0, "CC": 0, "C": 0, "D": 0,
}

RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]


@dataclass
class CreditResult:
    rating_score: int
    financial_score: int
    completeness_score: int
    penalty: int
    final_score: int
    recommendation: str
    recommendation_class: str
    risk_level: str
    confidence: str
    max_share: str
    hard_stop: bool
    positives: list[str]
    risks: list[str]
    missing: list[str]
    metrics: dict[str, float | None]


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value) or value == "":
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def fmt(value: Any, digits: int = 2) -> str:
    number = safe_float(value)
    if number is None:
        return "—"
    return f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")


def normalize_rating(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = text.replace("RU", "").replace("(RU)", "")
    text = re.sub(r"[^A-Z+\-]", "", text)
    for rating in sorted(RATING_POINTS, key=len, reverse=True):
        if rating in text:
            return rating
    return ""


def rating_direction(current: str, previous: str) -> int:
    if current not in RATING_ORDER or previous not in RATING_ORDER:
        return 0
    return RATING_ORDER.index(current) - RATING_ORDER.index(previous)


def find_latest_deep_file(directory: Path) -> Path:
    files = [p for p in directory.glob("bond_deep_analysis_*.xlsx") if not p.name.startswith("~$")]
    if not files:
        raise FileNotFoundError("Не найден bond_deep_analysis_YYYY-MM-DD.xlsx. Сначала запустите скрипт №6.")
    return max(files, key=lambda p: p.stat().st_mtime)


def load_deep(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Глубокий анализ")
    missing = REQUIRED_DEEP_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError("Во входном файле отсутствуют колонки: " + ", ".join(sorted(missing)))
    return df.dropna(subset=["Код ценной бумаги"]).copy()


def create_templates(data_dir: Path) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    ratings = data_dir / "issuer_ratings.xlsx"
    financials = data_dir / "issuer_financials.xlsx"
    if not ratings.exists() and not ratings.with_suffix(".csv").exists():
        pd.DataFrame(columns=RATING_TEMPLATE_COLUMNS).to_excel(ratings, index=False)
        print(f"Создан шаблон рейтингов: {ratings}")
    if not financials.exists() and not financials.with_suffix(".csv").exists():
        pd.DataFrame(columns=FINANCIAL_TEMPLATE_COLUMNS).to_excel(financials, index=False)
        print(f"Создан шаблон финансов: {financials}")
    return ratings, financials


def load_optional_table(xlsx_path: Path, required_columns: list[str]) -> pd.DataFrame:
    csv_path = xlsx_path.with_suffix(".csv")
    path = csv_path if csv_path.exists() else xlsx_path
    if not path.exists():
        return pd.DataFrame(columns=required_columns)
    df = pd.read_csv(path, sep=None, engine="python") if path.suffix.lower() == ".csv" else pd.read_excel(path)
    for column in required_columns:
        if column not in df.columns:
            df[column] = None
    return df


def row_match_score(source: pd.Series, candidate: pd.Series) -> int:
    secid = normalize(source.get("Код ценной бумаги"))
    issuer = normalize(source.get("Полное наименование"))
    source_inn = normalize(source.get("ИНН"))
    candidate_secid = normalize(candidate.get("Код ценной бумаги"))
    candidate_issuer = normalize(candidate.get("Эмитент"))
    candidate_inn = normalize(candidate.get("ИНН"))
    if secid and secid == candidate_secid:
        return 100
    if source_inn and candidate_inn and source_inn == candidate_inn:
        return 90
    if issuer and candidate_issuer and (issuer in candidate_issuer or candidate_issuer in issuer):
        return 60
    return 0


def best_match(source: pd.Series, table: pd.DataFrame) -> pd.Series | None:
    if table.empty:
        return None
    scored = [(row_match_score(source, row), index) for index, row in table.iterrows()]
    score, index = max(scored, default=(0, None))
    return None if score == 0 or index is None else table.loc[index]


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def calculate_metrics(fin: pd.Series | None) -> dict[str, float | None]:
    if fin is None:
        return {key: None for key in (
            "Долг/EBITDA", "Чистый долг/EBITDA", "Покрытие процентов",
            "Текущая ликвидность", "Долг/Капитал", "Маржа EBITDA",
            "Маржа чистой прибыли", "OCF/Долг",
        )}
    revenue = safe_float(fin.get("Выручка"))
    ebitda = safe_float(fin.get("EBITDA"))
    profit = safe_float(fin.get("Чистая прибыль"))
    ocf = safe_float(fin.get("Операционный денежный поток"))
    cash = safe_float(fin.get("Денежные средства"))
    debt = safe_float(fin.get("Общий долг"))
    interest = safe_float(fin.get("Процентные расходы"))
    equity = safe_float(fin.get("Собственный капитал"))
    current_assets = safe_float(fin.get("Оборотные активы"))
    current_liabilities = safe_float(fin.get("Краткосрочные обязательства"))
    net_debt = None if debt is None else debt - (cash or 0)
    return {
        "Долг/EBITDA": ratio(debt, ebitda),
        "Чистый долг/EBITDA": ratio(net_debt, ebitda),
        "Покрытие процентов": ratio(ebitda, interest),
        "Текущая ликвидность": ratio(current_assets, current_liabilities),
        "Долг/Капитал": ratio(debt, equity),
        "Маржа EBITDA": ratio(ebitda, revenue),
        "Маржа чистой прибыли": ratio(profit, revenue),
        "OCF/Долг": ratio(ocf, debt),
    }


def evaluate(source: pd.Series, rating: pd.Series | None, fin: pd.Series | None) -> CreditResult:
    positives: list[str] = []
    risks: list[str] = []
    missing: list[str] = []
    penalty = 0
    hard_stop = normalize(source.get("Жёсткий стоп")) in {"да", "true", "1"}
    second_score = int(round(safe_float(source.get("Итоговый балл")) or 0))

    rating_score = 0
    rating_value = ""
    if rating is None:
        missing.append("Кредитный рейтинг")
    else:
        rating_value = normalize_rating(rating.get("Рейтинг"))
        rating_score = RATING_POINTS.get(rating_value, 0)
        if not rating_value:
            missing.append("Распознаваемый кредитный рейтинг")
        else:
            positives.append(f"Кредитный рейтинг {rating_value}")
            if rating_value in {"CCC", "CC", "C", "D"}:
                hard_stop = True
                risks.append("Рейтинг указывает на крайне высокий риск или дефолт")
            elif rating_score <= 10:
                risks.append("Спекулятивный кредитный рейтинг")
                penalty += 10

        rating_date = parse_date(rating.get("Дата рейтинга"))
        if rating_date:
            age = (date.today() - rating_date).days
            if age > 550:
                risks.append("Кредитный рейтинг старше 18 месяцев")
                penalty += 5
            elif age <= 370:
                positives.append("Кредитный рейтинг актуален")
        else:
            missing.append("Дата рейтинга")

        forecast = normalize(rating.get("Прогноз"))
        if "негатив" in forecast or "развива" in forecast:
            risks.append(f"Прогноз рейтинга: {rating.get('Прогноз')}")
            penalty += 6
        elif "позитив" in forecast:
            positives.append("Позитивный прогноз рейтинга")

        previous = normalize_rating(rating.get("Предыдущий рейтинг"))
        direction = rating_direction(rating_value, previous)
        if direction < 0:
            risks.append(f"Рейтинг снижен с {previous} до {rating_value}")
            penalty += 8
        elif direction > 0:
            positives.append(f"Рейтинг повышен с {previous} до {rating_value}")

    metrics = calculate_metrics(fin)
    financial_score = 0
    if fin is None:
        missing.append("Финансовая отчётность")
    else:
        nd_ebitda = metrics["Чистый долг/EBITDA"]
        coverage = metrics["Покрытие процентов"]
        current = metrics["Текущая ликвидность"]
        debt_equity = metrics["Долг/Капитал"]
        net_margin = metrics["Маржа чистой прибыли"]
        ocf_debt = metrics["OCF/Долг"]

        if nd_ebitda is None:
            missing.append("Чистый долг/EBITDA")
        elif nd_ebitda < 2:
            financial_score += 10; positives.append("Низкая долговая нагрузка")
        elif nd_ebitda <= 3.5:
            financial_score += 7; positives.append("Умеренная долговая нагрузка")
        elif nd_ebitda <= 5:
            financial_score += 3; risks.append("Повышенная долговая нагрузка")
        else:
            risks.append("Очень высокая долговая нагрузка"); penalty += 12

        if coverage is None:
            missing.append("Покрытие процентов")
        elif coverage >= 4:
            financial_score += 8; positives.append("Хорошее покрытие процентных расходов")
        elif coverage >= 2:
            financial_score += 5
        elif coverage >= 1:
            financial_score += 1; risks.append("Слабое покрытие процентов")
        else:
            risks.append("EBITDA не покрывает процентные расходы"); penalty += 12

        if current is None:
            missing.append("Текущая ликвидность")
        elif current >= 1.5:
            financial_score += 5; positives.append("Хорошая текущая ликвидность")
        elif current >= 1:
            financial_score += 3
        else:
            risks.append("Оборотных активов меньше краткосрочных обязательств"); penalty += 6

        if debt_equity is not None:
            if debt_equity <= 1.5:
                financial_score += 3
            elif debt_equity > 3:
                risks.append("Высокое отношение долга к капиталу"); penalty += 5

        if net_margin is not None:
            if net_margin > 0.05:
                financial_score += 2; positives.append("Положительная чистая маржа")
            elif net_margin < 0:
                risks.append("Компания убыточна"); penalty += 8

        if ocf_debt is not None:
            if ocf_debt >= 0.2:
                financial_score += 2; positives.append("Долг поддержан операционным денежным потоком")
            elif ocf_debt < 0:
                risks.append("Отрицательный операционный денежный поток"); penalty += 8

    financial_score = min(30, financial_score)
    expected_fields = 10
    available = max(0, expected_fields - min(expected_fields, len(missing)))
    completeness_score = round(10 * available / expected_fields)

    final_score = round(second_score * 0.30 + rating_score + financial_score + completeness_score - penalty)
    final_score = max(0, min(100, final_score))

    if hard_stop:
        recommendation, css = "Не покупать", "avoid"
        final_score = min(final_score, 20)
    elif len(missing) >= 6:
        recommendation, css = "Недостаточно данных", "missing"
        final_score = min(final_score, 49)
    elif final_score >= 82:
        recommendation, css = "Допустить к покупке", "buy"
    elif final_score >= 70:
        recommendation, css = "Рассматривать", "consider"
    elif final_score >= 58:
        recommendation, css = "Только небольшой долей", "small"
    elif final_score >= 45:
        recommendation, css = "Ждать и перепроверить", "wait"
    else:
        recommendation, css = "Не покупать", "avoid"

    if hard_stop or final_score < 45:
        risk_level, max_share = "Высокий", "0%"
    elif final_score < 58:
        risk_level, max_share = "Повышенный", "до 1%"
    elif final_score < 70:
        risk_level, max_share = "Умеренно высокий", "до 2%"
    elif final_score < 82:
        risk_level, max_share = "Умеренный", "до 3%"
    else:
        risk_level, max_share = "Приемлемый по доступным данным", "до 5%"

    confidence = "Высокая" if completeness_score >= 9 else "Средняя" if completeness_score >= 6 else "Низкая"
    return CreditResult(
        rating_score, financial_score, completeness_score, penalty, final_score,
        recommendation, css, risk_level, confidence, max_share, hard_stop,
        positives, risks, missing, metrics,
    )


def build_analysis(deep: pd.DataFrame, ratings: pd.DataFrame, financials: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, (_, source) in enumerate(deep.iterrows(), start=1):
        name = str(source.get("Полное наименование") or "")
        secid = str(source.get("Код ценной бумаги") or "")
        print(f"[{index}/{len(deep)}] Кредитный анализ: {name} ({secid})")
        rating = best_match(source, ratings)
        fin = best_match(source, financials)
        result = evaluate(source, rating, fin)
        metrics = result.metrics
        rows.append({
            "Полное наименование": name,
            "Код ценной бумаги": secid,
            "Доходность": source.get("Доходность"),
            "Баллы второго слоя": source.get("Итоговый балл"),
            "Решение второго слоя": source.get("Решение"),
            "Рейтинг": "" if rating is None else rating.get("Рейтинг"),
            "Агентство": "" if rating is None else rating.get("Агентство"),
            "Прогноз": "" if rating is None else rating.get("Прогноз"),
            "Дата рейтинга": "" if rating is None else rating.get("Дата рейтинга"),
            "Баллы рейтинга": result.rating_score,
            "Период отчётности": "" if fin is None else fin.get("Период"),
            "Чистый долг/EBITDA": metrics["Чистый долг/EBITDA"],
            "Долг/EBITDA": metrics["Долг/EBITDA"],
            "Покрытие процентов": metrics["Покрытие процентов"],
            "Текущая ликвидность": metrics["Текущая ликвидность"],
            "Долг/Капитал": metrics["Долг/Капитал"],
            "Маржа EBITDA": metrics["Маржа EBITDA"],
            "Маржа чистой прибыли": metrics["Маржа чистой прибыли"],
            "OCF/Долг": metrics["OCF/Долг"],
            "Баллы финансов": result.financial_score,
            "Полнота данных": result.completeness_score,
            "Штрафы": result.penalty,
            "Итоговый кредитный балл": result.final_score,
            "Финальное решение": result.recommendation,
            "Уровень риска": result.risk_level,
            "Максимальная доля": result.max_share,
            "Уверенность": result.confidence,
            "Жёсткий стоп": "ДА" if result.hard_stop else "НЕТ",
            "Положительные факторы": "; ".join(result.positives) or "—",
            "Риски": "; ".join(result.risks) or "Явные риски не обнаружены",
            "Недостающие данные": "; ".join(result.missing) or "—",
            "Источник рейтинга": "" if rating is None else rating.get("Источник"),
            "Источник финансов": "" if fin is None else fin.get("Источник"),
            "_class": result.recommendation_class,
        })
    return pd.DataFrame(rows).sort_values(
        ["Итоговый кредитный балл", "Баллы второго слоя", "Доходность"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def write_excel(df: pd.DataFrame, output: Path, source: Path) -> None:
    methodology = pd.DataFrame({
        "Блок": ["Назначение", "Второй слой", "Рейтинг", "Финансы", "Полнота", "Жёсткие стопы", "Исходный файл"],
        "Описание": [
            "Третий слой: кредитный рейтинг и финансовая устойчивость эмитента.",
            "30% итогового балла берётся из результата скрипта №6.",
            "До 30 баллов за рейтинг, актуальность, прогноз и направление изменения.",
            "До 30 баллов за долговую нагрузку, покрытие процентов, ликвидность, прибыль и денежный поток.",
            "До 10 баллов за полноту данных. Отсутствующие сведения уменьшают уверенность.",
            "Стоп второго слоя и рейтинги CCC/CC/C/D автоматически запрещают покупку.",
            source.name,
        ],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.drop(columns=["_class"]).to_excel(writer, sheet_name="Кредитный анализ", index=False)
        methodology.to_excel(writer, sheet_name="Методика", index=False)
        sheet = writer.book["Кредитный анализ"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cells in sheet.columns:
            sheet.column_dimensions[cells[0].column_letter].width = min(70, max(len(str(c.value or "")) for c in cells) + 2)


def list_html(value: Any, css: str = "") -> str:
    items = [x.strip() for x in str(value or "").split(";") if x.strip() and x.strip() != "—"]
    if not items:
        return "<div class='muted'>Нет данных</div>"
    return f"<ul class='{css}'>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>"


def write_html(df: pd.DataFrame, output: Path, source: Path) -> None:
    cards = []
    for _, row in df.iterrows():
        css = row.get("_class", "wait")
        secid = html.escape(str(row["Код ценной бумаги"]))
        cards.append(f"""
        <article class="bond {css}" data-class="{css}">
          <div class="head"><div><h2>{html.escape(str(row['Полное наименование']))}</h2><a href="https://www.moex.com/ru/issue.aspx?board=TQCB&code={secid}" target="_blank">{secid}</a></div><div class="score">{int(row['Итоговый кредитный балл'])}/100</div></div>
          <div class="decision">{html.escape(str(row['Финальное решение']))} · риск: {html.escape(str(row['Уровень риска']))} · доля: {html.escape(str(row['Максимальная доля']))}</div>
          <div class="grid">
            <div><b>Рейтинг</b><span>{html.escape(str(row['Рейтинг'] or '—'))} · {html.escape(str(row['Агентство'] or '—'))}</span></div>
            <div><b>Чистый долг/EBITDA</b><span>{fmt(row['Чистый долг/EBITDA'])}</span></div>
            <div><b>Покрытие процентов</b><span>{fmt(row['Покрытие процентов'])}</span></div>
            <div><b>Текущая ликвидность</b><span>{fmt(row['Текущая ликвидность'])}</span></div>
            <div><b>Финансовые баллы</b><span>{int(row['Баллы финансов'])}/30</span></div>
            <div><b>Уверенность</b><span>{html.escape(str(row['Уверенность']))}</span></div>
          </div>
          <div class="cols"><section><h3>Плюсы</h3>{list_html(row['Положительные факторы'], 'good')}</section><section><h3>Риски</h3>{list_html(row['Риски'], 'bad')}</section><section><h3>Не хватает</h3>{list_html(row['Недостающие данные'])}</section></div>
        </article>""")
    counts = df["_class"].value_counts().to_dict()
    output.write_text(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Кредитный анализ облигаций</title><style>
    body{{margin:0;background:#f4f6f8;color:#17202a;font-family:Arial,sans-serif}}main{{max-width:1400px;margin:auto;padding:24px}}h1{{margin-bottom:6px}}.sub,.muted{{color:#667085}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}button{{padding:9px 13px;border:1px solid #d0d5dd;border-radius:9px;background:white;cursor:pointer}}.bond{{background:white;border:1px solid #e4e7ec;border-left:6px solid #98a2b3;border-radius:14px;padding:18px;margin:14px 0}}.bond.buy{{border-left-color:#039855}}.bond.consider{{border-left-color:#1570ef}}.bond.small{{border-left-color:#f79009}}.bond.wait{{border-left-color:#dc6803}}.bond.avoid{{border-left-color:#d92d20}}.head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:0 0 5px}}.score{{font-size:25px;font-weight:700}}.decision{{margin:14px 0;font-weight:700}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.grid div{{background:#f9fafb;padding:10px;border-radius:8px}}.grid b,.grid span{{display:block}}.grid span{{margin-top:5px}}.cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}ul{{padding-left:20px}}.good{{color:#027a48}}.bad{{color:#b42318}}a{{color:#175cd3;text-decoration:none}}@media(max-width:800px){{.grid,.cols{{grid-template-columns:1fr}}}}
    </style></head><body><main><h1>Третий слой: кредитный анализ</h1><div class="sub">Сформировано {datetime.now().strftime('%d.%m.%Y %H:%M')} · источник: {html.escape(source.name)}</div><div class="filters"><button onclick="filterCards('all')">Все ({len(df)})</button><button onclick="filterCards('buy')">К покупке ({counts.get('buy',0)})</button><button onclick="filterCards('consider')">Рассматривать ({counts.get('consider',0)})</button><button onclick="filterCards('small')">Небольшой долей ({counts.get('small',0)})</button><button onclick="filterCards('wait')">Ждать ({counts.get('wait',0)})</button><button onclick="filterCards('avoid')">Не покупать ({counts.get('avoid',0)})</button><button onclick="filterCards('missing')">Мало данных ({counts.get('missing',0)})</button></div>{''.join(cards)}<p class="muted">Отчёт не является индивидуальной инвестиционной рекомендацией. Проверяйте первоисточники, дату отчётности и методику расчёта EBITDA.</p></main><script>function filterCards(c){{document.querySelectorAll('.bond').forEach(x=>x.style.display=(c==='all'||x.dataset.class===c)?'block':'none')}}</script></body></html>""", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Третий слой анализа облигаций")
    parser.add_argument("--input", type=Path, help="Файл bond_deep_analysis_YYYY-MM-DD.xlsx")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Каталог рейтингов и финансов")
    args = parser.parse_args()
    try:
        source = args.input or find_latest_deep_file(Path.cwd())
        ratings_path, financials_path = create_templates(args.data_dir)
        ratings = load_optional_table(ratings_path, RATING_TEMPLATE_COLUMNS)
        financials = load_optional_table(financials_path, FINANCIAL_TEMPLATE_COLUMNS)
        deep = load_deep(source)
        result = build_analysis(deep, ratings, financials)
        stamp = datetime.now().strftime("%Y-%m-%d")
        excel = Path(f"bond_credit_analysis_{stamp}.xlsx")
        report = Path(f"bond_credit_analysis_{stamp}.html")
        write_excel(result, excel, source)
        write_html(result, report, source)
        print(f"Готово: {excel}")
        print(f"Готово: {report}")
        if ratings.empty or financials.empty:
            print("Внимание: шаблоны данных пусты. Заполните data/issuer_ratings.xlsx и data/issuer_financials.xlsx и запустите повторно.")
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
