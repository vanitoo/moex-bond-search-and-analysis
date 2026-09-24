import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "5_bonds_analysis.py"
spec = importlib.util.spec_from_file_location("bonds_analysis", MODULE_PATH)
analysis = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(analysis)


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
    normalized = analysis.normalize_search_columns(frame)
    assert normalized.loc[0, "Нужна квалификация?"] == "НЕТ"
    assert normalized.loc[0, "Объем сделок с 15 дней, шт."] == 70000
    assert not analysis.REQUIRED.difference(normalized.columns)
