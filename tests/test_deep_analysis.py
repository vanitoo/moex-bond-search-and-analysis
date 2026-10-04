from __future__ import annotations

import pandas as pd

from app.core.deep_analysis import DeepAnalysisResult, analyze_deep_row, evaluate


def _complete_row() -> dict[str, object]:
    return {
        "Полное наименование": "ООО Тест 001Р-01",
        "Код ценной бумаги": "RU000TEST001",
        "Доходность": 18.0,
        "Оценка, 0-100": 90,
        "Риски и ограничения": "—",
        "Жёсткий стоп": "НЕТ",
        "Критический новостной стоп": "НЕТ",
        "Будущих купонов": 6,
        "Неизвестных купонов": 0,
        "Будущих амортизаций": 0,
        "Ближайшая оферта": "",
        "Максимум к покупке, руб.": 150000,
        "Максимум к покупке, шт.": 100,
        "Спред, %": 0.5,
        "Спред к ОФЗ, б.п.": 350,
        "Доходность сопоставимой ОФЗ, %": 14.5,
        "ОФЗ сравнения": "ОФЗ-ТЕСТ",
        "Оценка премии к ОФЗ": "Нормальная",
        "Качество данных спреда": "OK",
        "Новостных файлов": 2,
        "Негативные события": "—",
        "Позитивные события": "—",
    }


def test_deep_analysis_exposes_typed_result_and_legacy_dict():
    row = _complete_row()
    result = analyze_deep_row(row)

    assert isinstance(result, DeepAnalysisResult)
    assert result.score == 97
    assert result.decision == "Рассматривать к покупке"
    assert evaluate(row) == result.as_legacy_dict()


def test_deep_analysis_accepts_dataframe_series():
    result = analyze_deep_row(pd.Series(_complete_row()))
    assert result.values["Код ценной бумаги"] == "RU000TEST001"
    assert result.values["Жёсткий стоп"] == "НЕТ"


def test_deep_analysis_hard_stop_preserves_cap_and_decision():
    row = _complete_row()
    row["Жёсткий стоп"] = "ДА"

    result = analyze_deep_row(row)

    assert result.score == 20
    assert result.decision == "Не покупать"
    assert result.values["Жёсткий стоп"] == "ДА"


def test_deep_analysis_missing_inputs_preserve_no_data_decision():
    row = _complete_row()
    row["Будущих купонов"] = 0
    row["Спред к ОФЗ, б.п."] = None
    row["Новостных файлов"] = 0

    result = analyze_deep_row(row)

    assert result.score <= 55
    assert result.decision == "Недостаточно данных"
    assert "График будущих купонов" in result.values["Недостающие данные"]
    assert "Спред к ОФЗ" in result.values["Недостающие данные"]
    assert "Новости эмитента" in result.values["Недостающие данные"]
