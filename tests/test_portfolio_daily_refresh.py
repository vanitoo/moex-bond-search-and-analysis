from pathlib import Path

import pandas as pd

from portfolio_daily_refresh import overlay_fresh_news


def _write_decisions(path: Path) -> None:
    pd.DataFrame([
        {
            "Код ценной бумаги": "RU0000000001",
            "Финальное решение": "Покупать",
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "",
        },
        {
            "Код ценной бумаги": "RU0000000002",
            "Финальное решение": "Покупать",
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "",
        },
    ]).to_excel(path, sheet_name="Решения", index=False)


def test_overlay_fresh_news_marks_critical_and_review(tmp_path: Path) -> None:
    decisions = tmp_path / "bond_decisions_2026-09-01.xlsx"
    news = tmp_path / "bond_news_daily.xlsx"
    _write_decisions(decisions)
    pd.DataFrame([
        {
            "Код ценной бумаги": "RU0000000001",
            "Негативные события": "Дефолт/просрочка",
            "Критический новостной стоп": "ДА",
        },
        {
            "Код ценной бумаги": "RU0000000002",
            "Негативные события": "Финансовое ухудшение",
            "Критический новостной стоп": "НЕТ",
        },
    ]).to_excel(news, sheet_name="Новости", index=False)

    output = overlay_fresh_news(tmp_path, news)
    assert output is not None
    result = pd.read_excel(output, sheet_name="Решения").set_index("Код ценной бумаги")
    assert result.loc["RU0000000001", "Финальное решение"] == "Не покупать"
    assert result.loc["RU0000000001", "Жёсткий стоп"] == "ДА"
    assert result.loc["RU0000000002", "Финальное решение"] == "Требуется ручная проверка"
