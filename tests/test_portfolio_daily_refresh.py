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


def _write_empty_news(path: Path) -> None:
    pd.DataFrame([
        {"Код ценной бумаги": "RU0000000001", "Негативные события": "—", "Критический новостной стоп": "НЕТ"},
        {"Код ценной бумаги": "RU0000000002", "Негативные события": "—", "Критический новостной стоп": "НЕТ"},
    ]).to_excel(path, sheet_name="Новости", index=False)


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

    output = overlay_fresh_news(tmp_path, news, rating_events=[])
    assert output is not None
    result = pd.read_excel(output, sheet_name="Решения").set_index("Код ценной бумаги")
    assert result.loc["RU0000000001", "Финальное решение"] == "Не покупать"
    assert result.loc["RU0000000001", "Жёсткий стоп"] == "ДА"
    assert result.loc["RU0000000002", "Финальное решение"] == "Требуется ручная проверка"


def test_overlay_fresh_rating_downgrade_reaches_monitor_fields(tmp_path: Path) -> None:
    decisions = tmp_path / "bond_decisions_2026-09-01.xlsx"
    news = tmp_path / "bond_news_daily.xlsx"
    _write_decisions(decisions)
    _write_empty_news(news)
    events = [{
        "company": "Issuer",
        "secids": ["RU0000000002"],
        "agency": "АКРА",
        "action": "ПОНИЖЕН",
        "current_rating": "BBB",
        "previous_rating": "A-",
        "forecast": "Негативный",
        "event_date": "2026-09-09T12:00:00+03:00",
        "object_type": "Эмитент",
        "source_url": "https://example.test/rating",
        "title": "Рейтинг понижен",
    }]

    output = overlay_fresh_news(tmp_path, news, rating_events=events)
    assert output is not None
    result = pd.read_excel(output, sheet_name="Решения").set_index("Код ценной бумаги")
    row = result.loc["RU0000000002"]
    assert row["Финальное решение"] == "Требуется ручная проверка"
    assert row["Последнее рейтинговое действие"] == "ПОНИЖЕН"
    assert row["Рейтинг"] == "BBB"
    assert row["Прогноз рейтинга"] == "Негативный"
    assert row["Рейтинговое агентство"] == "АКРА"
    assert row["Корректировка за рейтинг"] == -18
    assert "Свежий рейтинг" in row["Блокеры"]


def test_overlay_fresh_critical_rating_sets_hard_stop(tmp_path: Path) -> None:
    decisions = tmp_path / "bond_decisions_2026-09-01.xlsx"
    news = tmp_path / "bond_news_daily.xlsx"
    _write_decisions(decisions)
    _write_empty_news(news)
    events = [{
        "company": "Issuer",
        "secids": ["RU0000000001"],
        "agency": "Эксперт РА",
        "action": "ПОНИЖЕН",
        "current_rating": "CCC",
        "previous_rating": "B",
        "forecast": "Негативный",
        "event_date": "2026-09-09T12:00:00+03:00",
        "object_type": "Эмитент",
        "source_url": "https://example.test/rating",
        "title": "Критическое снижение рейтинга",
    }]

    output = overlay_fresh_news(tmp_path, news, rating_events=events)
    assert output is not None
    result = pd.read_excel(output, sheet_name="Решения").set_index("Код ценной бумаги")
    row = result.loc["RU0000000001"]
    assert row["Финальное решение"] == "Не покупать"
    assert row["Жёсткий стоп"] == "ДА"
    assert row["Рейтинг"] == "CCC"


def test_daily_overlay_does_not_use_previous_daily_decision_as_base(tmp_path: Path) -> None:
    base = tmp_path / "bond_decisions_2026-09-01.xlsx"
    stale_daily = tmp_path / "bond_decisions_daily_2026-09-08_120000.xlsx"
    news = tmp_path / "bond_news_daily.xlsx"
    _write_decisions(base)
    stale = pd.read_excel(base, sheet_name="Решения")
    stale.loc[stale["Код ценной бумаги"] == "RU0000000002", "Финальное решение"] = "Не покупать"
    stale.to_excel(stale_daily, sheet_name="Решения", index=False)
    _write_empty_news(news)

    output = overlay_fresh_news(tmp_path, news, rating_events=[])
    assert output is not None
    result = pd.read_excel(output, sheet_name="Решения").set_index("Код ценной бумаги")
    assert result.loc["RU0000000002", "Финальное решение"] == "Покупать"
