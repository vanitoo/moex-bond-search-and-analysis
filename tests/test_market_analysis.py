from __future__ import annotations

import pandas as pd

from app.core.market_analysis import MarketAnalysisResult, analyze_market_row, score_row


def _strong_row() -> dict[str, object]:
    return {
        "Доходность": 18.0,
        "Цена, %": 100.0,
        "Дюрация, месяцев": 10.0,
        "Объем сделок с 15 дней, шт.": 250000,
        "Максимум к покупке, руб.": 150000,
        "Спред, %": 0.4,
        "Неизвестных купонов": 0,
        "Нужна квалификация?": "НЕТ",
        "Спред к ОФЗ, б.п.": 350,
        "Качество данных спреда": "OK",
        "Полнота новостей": "Есть данные",
        "Критический новостной стоп": "НЕТ",
    }


def test_market_analysis_exposes_typed_result_and_legacy_tuple():
    row = _strong_row()
    result = analyze_market_row(row)

    assert isinstance(result, MarketAnalysisResult)
    assert result.score == 100
    assert result.decision == "Рассматривать в первую очередь"
    assert result.ofz_adjustment == 6
    assert score_row(row) == result.legacy_tuple()


def test_market_analysis_accepts_dataframe_series_without_excel_contract_change():
    result = analyze_market_row(pd.Series(_strong_row()))
    assert result.score == 100
    assert "Хорошая премия к ОФЗ" in result.positives


def test_market_analysis_hard_stop_preserves_historical_cap():
    row = _strong_row()
    row["Критический новостной стоп"] = "ДА"

    result = analyze_market_row(row)

    assert result.score == 15
    assert result.hard_stop is True
    assert result.decision == "Не покупать без ручного анализа"
    assert "Критический новостной стоп" in result.risks


def test_market_analysis_unknown_ofz_spread_is_not_fatal():
    row = _strong_row()
    row["Спред к ОФЗ, б.п."] = None

    result = analyze_market_row(row)

    assert result.ofz_adjustment == 0
    assert "Спред к ОФЗ неизвестен" in result.risks
