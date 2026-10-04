from __future__ import annotations

import pandas as pd


SEARCH_REQUIRED_COLUMNS = frozenset({
    "Полное наименование",
    "Код ценной бумаги",
    "Нужна квалификация?",
    "Цена, %",
    "Объем сделок с 15 дней, шт.",
    "Доходность",
    "Дюрация, месяцев",
})

SEARCH_COLUMN_ALIASES = {
    "Нужна квалификация?": ("Для квалифицированных инвесторов",),
    "Объем сделок с 15 дней, шт.": (
        "Объем за 15 дней, шт.",
        "Объем торгов за 15 дней",
    ),
}


def normalize_search_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize V1/V2 market-search aliases to the analysis contract."""
    result = frame.copy()
    for canonical, alternatives in SEARCH_COLUMN_ALIASES.items():
        if canonical in result.columns:
            continue
        for alternative in alternatives:
            if alternative in result.columns:
                result[canonical] = result[alternative]
                break
    return result


def missing_search_columns(frame: pd.DataFrame) -> set[str]:
    return set(SEARCH_REQUIRED_COLUMNS.difference(frame.columns))
