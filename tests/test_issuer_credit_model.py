import importlib.util
from pathlib import Path

import pandas as pd

from moex_bond_search_and_analysis.issuer_credit_model import classify_issuer


MODULE_PATH = Path(__file__).resolve().parents[1] / "7_bonds_credit_analysis.py"
spec = importlib.util.spec_from_file_location("credit_analysis_module", MODULE_PATH)
credit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(credit)


def _source(name: str) -> pd.Series:
    return pd.Series({
        "Полное наименование": name,
        "Итоговый балл": 85,
        "Жёсткий стоп": "НЕТ",
    })


def _rating(value: str = "AAA") -> pd.Series:
    return pd.Series({
        "Рейтинг": value,
        "Дата рейтинга": "01.09.2026",
        "Прогноз": "Стабильный",
        "Предыдущий рейтинг": value,
        "Эмитент": "Тест",
    })


def test_issuer_type_classifier_distinguishes_main_models():
    assert classify_issuer("Сбербанк ПАО 001Р").key == "bank"
    assert classify_issuer("Томская область 34075").key == "region"
    assert classify_issuer("СФО СБ Секьюритизация 5 класс А").key == "structured_finance"
    assert classify_issuer("АЛРОСА 001Р-01").key == "corporate"


def test_bank_classifier_does_not_misclassify_leasing_subsidiary():
    assert classify_issuer("Совкомбанк Лизинг БО-П17").key == "corporate"
    assert classify_issuer("ВТБ Лизинг 001Р").key == "corporate"


def test_noncorporate_model_does_not_require_corporate_financials():
    model = classify_issuer("Сбербанк ПАО 001Р")
    result = credit.evaluate(_source("Сбербанк ПАО 001Р"), _rating(), None, model)
    assert "Финансовая отчётность" not in result.missing
    assert "Специализированные банковские показатели ЦБ РФ" in result.missing
    assert result.confidence == "Средняя"
    assert result.final_score >= 70


def test_corporate_model_still_requires_financials():
    model = classify_issuer("АЛРОСА 001Р-01")
    result = credit.evaluate(_source("АЛРОСА 001Р-01"), _rating(), None, model)
    assert "Финансовая отчётность" in result.missing
