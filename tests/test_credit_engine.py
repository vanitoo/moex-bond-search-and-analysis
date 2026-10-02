from datetime import date

import pandas as pd

from credit_engine import best_match, evaluate
from moex_bond_search_and_analysis.issuer_credit_model import CORPORATE


def _source(**overrides):
    row = {
        "Код ценной бумаги": "RU000A10TEST",
        "Полное наименование": "ООО Тест",
        "ИНН": "1234567890",
        "Жёсткий стоп": "НЕТ",
        "Итоговый балл": 90,
    }
    row.update(overrides)
    return pd.Series(row)


def _rating(value="AA", **overrides):
    row = {
        "Код ценной бумаги": "",
        "Эмитент": "ООО Тест",
        "ИНН": "1234567890",
        "Рейтинг": value,
        "Дата рейтинга": date.today().isoformat(),
        "Прогноз": "Стабильный",
        "Предыдущий рейтинг": value,
    }
    row.update(overrides)
    return pd.Series(row)


def _financials(**overrides):
    row = {
        "Код ценной бумаги": "",
        "Эмитент": "ООО Тест",
        "ИНН": "1234567890",
        "Выручка": 10000,
        "EBITDA": 2500,
        "Чистая прибыль": 1000,
        "Операционный денежный поток": 1600,
        "Денежные средства": 1000,
        "Общий долг": 4000,
        "Процентные расходы": 500,
        "Собственный капитал": 5000,
        "Оборотные активы": 6000,
        "Краткосрочные обязательства": 3000,
    }
    row.update(overrides)
    return pd.Series(row)


def test_best_match_prefers_inn_over_issuer_text():
    table = pd.DataFrame([
        {"Эмитент": "ООО Тест Похожий", "ИНН": "0000000000"},
        {"Эмитент": "Другое название", "ИНН": "1234567890"},
    ])
    matched = best_match(_source(), table)
    assert matched is not None
    assert matched["ИНН"] == "1234567890"


def test_corporate_engine_scores_complete_financials():
    result = evaluate(_source(), _rating(), _financials(), CORPORATE)
    assert result.hard_stop is False
    assert result.financial_score > 0
    assert result.final_score >= 70
    assert "Финансовая отчётность" not in result.missing


def test_critical_rating_is_hard_stop():
    result = evaluate(_source(), _rating("CCC"), _financials(), CORPORATE)
    assert result.hard_stop is True
    assert result.recommendation == "Не покупать"
    assert result.final_score <= 20


def test_missing_financials_are_explicit_not_zero_filled():
    result = evaluate(_source(), _rating(), None, CORPORATE)
    assert "Финансовая отчётность" in result.missing
    assert result.financial_score == 0
