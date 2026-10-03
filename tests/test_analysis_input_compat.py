import pandas as pd

from app.core.search_contract import SEARCH_REQUIRED_COLUMNS, normalize_search_columns


def test_analysis_normalizes_v2_search_aliases():
    frame = pd.DataFrame([{
        "Полное наименование": "Test Bond",
        "Код ценной бумаги": "RU000A10TEST",
        "Для квалифицированных инвесторов": "НЕТ",
        "Цена, %": 99.0,
        "Объем за 15 дней, шт.": 70000,
        "Доходность": 18.0,
        "Дюрация, месяцев": 12.0,
    }])
    normalized = normalize_search_columns(frame)
    assert normalized.loc[0, "Нужна квалификация?"] == "НЕТ"
    assert normalized.loc[0, "Объем сделок с 15 дней, шт."] == 70000
    assert not SEARCH_REQUIRED_COLUMNS.difference(normalized.columns)
