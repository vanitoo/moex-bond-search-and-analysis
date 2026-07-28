from pathlib import Path

import pandas as pd

from pipeline_architecture import _status_for_row, is_enabled, load_config


def test_balanced_config_enables_modules():
    config = load_config(Path(__file__).resolve().parents[1] / "configs" / "balanced.json")
    assert is_enabled(config, "news") is True
    assert config["strategy"] == "balanced"


def test_news_without_files_is_no_data():
    row = pd.Series({"Новостных файлов": 0, "Критический новостной стоп": "НЕТ"})
    status, passed, hard_stop, _, code, _ = _status_for_row("news", row)
    assert status == "NO_DATA"
    assert passed is None
    assert hard_stop is False
    assert code == "NEWS_NOT_FOUND"


def test_critical_news_is_hard_stop():
    row = pd.Series({
        "Новостных файлов": 2,
        "Критический новостной стоп": "ДА",
        "Негативные события": "Дефолт/просрочка",
    })
    status, passed, hard_stop, _, code, _ = _status_for_row("news", row)
    assert status == "FAIL"
    assert passed is False
    assert hard_stop is True
    assert code == "CRITICAL_NEWS"


def test_missing_orderbook_is_warning_not_high_liquidity():
    row = pd.Series({
        "Максимум к покупке, руб.": 100_000,
        "Объём предложения в стакане, руб.": 0,
    })
    status, passed, _, score_delta, code, _ = _status_for_row("liquidity", row)
    assert status == "WARNING"
    assert passed is True
    assert score_delta < 0
    assert code == "ORDERBOOK_UNKNOWN"
