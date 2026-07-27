import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "4c_bonds_ofz_spread.py"
SPEC = importlib.util.spec_from_file_location("bonds_ofz_spread", MODULE_PATH)
assert SPEC and SPEC.loader
ofz = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ofz)


def sample_curve() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "SECID ОФЗ": "SU0001",
                "Дюрация ОФЗ, месяцев": 6.0,
                "Доходность ОФЗ, %": 14.0,
            },
            {
                "SECID ОФЗ": "SU0002",
                "Дюрация ОФЗ, месяцев": 18.0,
                "Доходность ОФЗ, %": 16.0,
            },
        ]
    )


def test_interpolates_ofz_yield_by_duration():
    result = ofz.interpolate_ofz_yield(sample_curve(), 12.0)

    assert result["Доходность сопоставимой ОФЗ, %"] == 15.0
    assert result["ОФЗ сравнения"] == "SU0001 / SU0002"
    assert result["Метод сравнения с ОФЗ"] == "Линейная интерполяция по дюрации"


def test_calculates_spread_in_basis_points():
    bonds = pd.DataFrame(
        [
            {
                "Код ценной бумаги": "RU000A100000",
                "Доходность": 19.0,
                "Дюрация, месяцев": 12.0,
            }
        ]
    )

    result = ofz.calculate_spreads(bonds, sample_curve())

    assert result.iloc[0]["Доходность сопоставимой ОФЗ, %"] == 15.0
    assert result.iloc[0]["Спред к ОФЗ, п.п."] == 4.0
    assert result.iloc[0]["Спред к ОФЗ, б.п."] == 400.0
    assert result.iloc[0]["Качество данных спреда"] == "ИЗВЕСТНО"


def test_marks_missing_bond_inputs_as_unknown():
    bonds = pd.DataFrame(
        [
            {
                "Код ценной бумаги": "RU000A100000",
                "Доходность": None,
                "Дюрация, месяцев": 12.0,
            }
        ]
    )

    result = ofz.calculate_spreads(bonds, sample_curve())

    assert result.iloc[0]["Качество данных спреда"] == "НЕИЗВЕСТНО"
    assert "Нет доходности" in result.iloc[0]["Причина качества спреда"]


def test_extreme_spread_is_not_treated_as_automatically_good():
    assert ofz.classify_spread(450) == "Повышенная премия"
    assert ofz.classify_spread(1200) == "Экстремальная премия / вероятный высокий риск"
