from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from collections.abc import Callable
from typing import Any

import pandas as pd

from app.core.rating_utils import RATING_ORDER, normalize_rating, rating_direction
from moex_bond_search_and_analysis.cbr_banks import score_bank_metrics
from moex_bond_search_and_analysis.issuer_credit_model import IssuerCreditModel, classify_issuer


RATING_POINTS = {
    "AAA": 30, "AA+": 28, "AA": 27, "AA-": 25,
    "A+": 23, "A": 21, "A-": 19,
    "BBB+": 17, "BBB": 15, "BBB-": 13,
    "BB+": 10, "BB": 8, "BB-": 6,
    "B+": 4, "B": 2, "B-": 1,
    "CCC": 0, "CC": 0, "C": 0, "D": 0,
}



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
    if isinstance(value, float) and value.is_integer():
        value = int(value)
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
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
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


def evaluate(
    source: pd.Series,
    rating: pd.Series | None,
    fin: pd.Series | None,
    model: IssuerCreditModel,
    bank_metrics: pd.Series | None = None,
) -> CreditResult:
    """Pure credit-scoring engine.

    External fetching, file IO and report generation intentionally live outside
    this module so the scoring rules can be tested independently.
    """

    positives: list[str] = []
    risks: list[str] = []
    missing: list[str] = []
    penalty = 0
    hard_stop = normalize(source.get("Жёсткий стоп")) in {"да", "true", "1"}
    second_score = int(round(safe_float(source.get("Итоговый балл")) or 0))

    rating_score = 0
    rating_value = ""
    rating_date: date | None = None
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

    metrics = calculate_metrics(fin if model.key == "corporate" else None)
    financial_score = 0

    if model.key == "corporate":
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
                financial_score += 10
                positives.append("Низкая долговая нагрузка")
            elif nd_ebitda <= 3.5:
                financial_score += 7
                positives.append("Умеренная долговая нагрузка")
            elif nd_ebitda <= 5:
                financial_score += 3
                risks.append("Повышенная долговая нагрузка")
            else:
                risks.append("Очень высокая долговая нагрузка")
                penalty += 12

            if coverage is None:
                missing.append("Покрытие процентов")
            elif coverage >= 4:
                financial_score += 8
                positives.append("Хорошее покрытие процентных расходов")
            elif coverage >= 2:
                financial_score += 5
            elif coverage >= 1:
                financial_score += 1
                risks.append("Слабое покрытие процентов")
            else:
                risks.append("EBITDA не покрывает процентные расходы")
                penalty += 12

            if current is None:
                missing.append("Текущая ликвидность")
            elif current >= 1.5:
                financial_score += 5
                positives.append("Хорошая текущая ликвидность")
            elif current >= 1:
                financial_score += 3
            else:
                risks.append("Оборотных активов меньше краткосрочных обязательств")
                penalty += 6

            if debt_equity is not None:
                if debt_equity <= 1.5:
                    financial_score += 3
                elif debt_equity > 3:
                    risks.append("Высокое отношение долга к капиталу")
                    penalty += 5

            if net_margin is not None:
                if net_margin > 0.05:
                    financial_score += 2
                    positives.append("Положительная чистая маржа")
                elif net_margin < 0:
                    risks.append("Компания убыточна")
                    penalty += 8

            if ocf_debt is not None:
                if ocf_debt >= 0.2:
                    financial_score += 2
                    positives.append("Долг поддержан операционным денежным потоком")
                elif ocf_debt < 0:
                    risks.append("Отрицательный операционный денежный поток")
                    penalty += 8

        financial_score = min(30, financial_score)
        expected_fields = 10
        available = max(0, expected_fields - min(expected_fields, len(missing)))
        completeness_score = round(10 * available / expected_fields)
        final_score = round(
            second_score * 0.30
            + rating_score
            + financial_score
            + completeness_score
            - penalty
        )
    elif model.key == "bank" and bank_metrics is not None:
        bank_score, bank_positives, bank_risks, bank_hard_stop, bank_completeness = score_bank_metrics(bank_metrics)
        positives.extend(bank_positives)
        risks.extend(bank_risks)
        hard_stop = hard_stop or bank_hard_stop
        financial_score = bank_score
        completeness_score = bank_completeness
        metrics.update({
            "Н1.0": safe_float(bank_metrics.get("Н1.0")),
            "Н1.1": safe_float(bank_metrics.get("Н1.1")),
            "Н1.2": safe_float(bank_metrics.get("Н1.2")),
            "Н2": safe_float(bank_metrics.get("Н2")),
            "Н3": safe_float(bank_metrics.get("Н3")),
            "Н4": safe_float(bank_metrics.get("Н4")),
        })
        if bank_completeness < 7:
            missing.append("Часть обязательных нормативов ЦБ РФ")
        positives.append("Применена банковская модель по форме 0409135 Банка России")
        final_score = round(
            second_score * 0.30
            + rating_score
            + bank_score
            + completeness_score
            - penalty
        )
    else:
        if model.specialist_data_label:
            missing.append(model.specialist_data_label)
        rating_normalized = rating_score / 30.0 * 100.0 if rating_score else 0.0
        completeness_score = 7 if rating_value and rating_date else 5 if rating_value else 2
        final_score = round(
            second_score * 0.55
            + rating_normalized * 0.35
            + completeness_score
            - penalty
        )
        positives.append(f"Применена специализированная модель: {model.label}")

    final_score = max(0, min(100, final_score))

    if hard_stop:
        recommendation, css = "Не покупать", "avoid"
        final_score = min(final_score, 20)
    elif model.key != "corporate" and not rating_value:
        recommendation, css = "Недостаточно данных", "missing"
        final_score = min(final_score, 49)
    elif model.key == "corporate" and len(missing) >= 6:
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

    if model.key == "bank" and bank_metrics is not None:
        confidence = "Высокая" if completeness_score >= 8 and rating_value else "Средняя" if rating_value else "Низкая"
    elif model.key != "corporate" and model.specialist_data_label:
        confidence = "Средняя" if rating_value else "Низкая"
    else:
        confidence = "Высокая" if completeness_score >= 9 else "Средняя" if completeness_score >= 6 else "Низкая"

    return CreditResult(
        rating_score,
        financial_score,
        completeness_score,
        penalty,
        final_score,
        recommendation,
        css,
        risk_level,
        confidence,
        max_share,
        hard_stop,
        positives,
        risks,
        missing,
        metrics,
    )


def build_analysis(
    deep: pd.DataFrame,
    ratings: pd.DataFrame,
    financials: pd.DataFrame,
    bank_metrics_table: pd.DataFrame | None = None,
    *,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> pd.DataFrame:
    """Evaluate every security using the correct issuer-specific credit model."""

    rows: list[dict[str, Any]] = []
    total = len(deep)
    for index, (_, source) in enumerate(deep.iterrows(), start=1):
        name = str(source.get("Полное наименование") or "")
        secid = str(source.get("Код ценной бумаги") or "")
        if progress is not None:
            progress(index, total, name, secid)

        matched_rating = best_match(source, ratings)
        fin = best_match(source, financials)
        model = classify_issuer(
            name,
            "" if matched_rating is None else matched_rating.get("Эмитент"),
            "" if fin is None else fin.get("Эмитент"),
        )
        bank_metrics = None
        if (
            model.key == "bank"
            and bank_metrics_table is not None
            and not bank_metrics_table.empty
        ):
            bank_metrics = best_match(source, bank_metrics_table)

        result = evaluate(source, matched_rating, fin, model, bank_metrics)
        metrics = result.metrics
        used_fin = fin if model.key == "corporate" else None
        rows.append({
            "Полное наименование": name,
            "Код ценной бумаги": secid,
            "Эмитент": (
                "" if matched_rating is None else matched_rating.get("Эмитент")
            ) or ("" if fin is None else fin.get("Эмитент")) or "",
            "ИНН": (
                "" if matched_rating is None else matched_rating.get("ИНН")
            ) or ("" if fin is None else fin.get("ИНН")) or "",
            "Доходность": source.get("Доходность"),
            "Тип эмитента": model.label,
            "Ключ модели": model.key,
            "Методика кредитного анализа": model.methodology,
            "Баллы второго слоя": source.get("Итоговый балл"),
            "Решение второго слоя": source.get("Решение"),
            "Рейтинг": "" if matched_rating is None else matched_rating.get("Рейтинг"),
            "Агентство": "" if matched_rating is None else matched_rating.get("Агентство"),
            "Прогноз": "" if matched_rating is None else matched_rating.get("Прогноз"),
            "Дата рейтинга": "" if matched_rating is None else matched_rating.get("Дата рейтинга"),
            "Баллы рейтинга": result.rating_score,
            "Период отчётности": "" if used_fin is None else used_fin.get("Период"),
            "Чистый долг/EBITDA": metrics["Чистый долг/EBITDA"],
            "Долг/EBITDA": metrics["Долг/EBITDA"],
            "Покрытие процентов": metrics["Покрытие процентов"],
            "Текущая ликвидность": metrics["Текущая ликвидность"],
            "Долг/Капитал": metrics["Долг/Капитал"],
            "Маржа EBITDA": metrics["Маржа EBITDA"],
            "Маржа чистой прибыли": metrics["Маржа чистой прибыли"],
            "OCF/Долг": metrics["OCF/Долг"],
            "Н1.0": metrics.get("Н1.0"),
            "Н1.1": metrics.get("Н1.1"),
            "Н1.2": metrics.get("Н1.2"),
            "Н2": metrics.get("Н2"),
            "Н3": metrics.get("Н3"),
            "Н4": metrics.get("Н4"),
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
            "Источник рейтинга": "" if matched_rating is None else matched_rating.get("Источник"),
            "Источник финансов": "" if used_fin is None else used_fin.get("Источник"),
            "Источник банковских данных": "" if bank_metrics is None else bank_metrics.get("Источник"),
            "Дата банковских данных": "" if bank_metrics is None else bank_metrics.get("Дата отчётности"),
            "_class": result.recommendation_class,
        })

    return pd.DataFrame(rows).sort_values(
        ["Итоговый кредитный балл", "Баллы второго слоя", "Доходность"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
