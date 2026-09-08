import pandas as pd

from pipeline_common import merge_by_secid


def test_merge_by_secid_keeps_existing_overlapping_columns_and_adds_new_fields():
    base = pd.DataFrame([
        {"Код ценной бумаги": "RU000A123456", "Спред к ОФЗ, б.п.": 500, "База": "ok"}
    ])
    extra = pd.DataFrame([
        {"Код ценной бумаги": "RU000A123456", "Спред к ОФЗ, б.п.": 700, "Рейтинг": "BBB+"}
    ])

    result = merge_by_secid(base, extra)

    assert list(result.columns) == ["Код ценной бумаги", "Спред к ОФЗ, б.п.", "База", "Рейтинг"]
    assert result.loc[0, "Спред к ОФЗ, б.п."] == 500
    assert result.loc[0, "Рейтинг"] == "BBB+"
    assert not any(column.endswith(("_x", "_y")) for column in result.columns)


def test_repeated_merge_does_not_create_suffix_columns_or_raise():
    base = pd.DataFrame([
        {"Код ценной бумаги": "RU000A123456", "Максимум к покупке, руб.": 10000}
    ])
    extra = pd.DataFrame([
        {"Код ценной бумаги": "RU000A123456", "Максимум к покупке, руб.": 10000, "Рейтинг": "A-"}
    ])

    once = merge_by_secid(base, extra)
    twice = merge_by_secid(once, extra)

    assert twice.loc[0, "Максимум к покупке, руб."] == 10000
    assert twice.loc[0, "Рейтинг"] == "A-"
    assert not any(column.endswith(("_x", "_y")) for column in twice.columns)
