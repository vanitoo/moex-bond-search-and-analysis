import pandas as pd

from decision_engine import annotate_shortlist_reasons, decide


def _row(**overrides):
    row = {
        "Полное наименование": "Тестовая облигация",
        "Код ценной бумаги": "RU000A10TEST",
        "Эмитент": "ООО Тест",
        "ИНН": "1234567890",
        "Оценка, 0-100": 84,
        "Итоговый балл": 86,
        "Итоговый кредитный балл": 88,
        "Доходность": 18.0,
        "Рейтинг": "AA",
        "Максимум к покупке, руб.": 100000,
        "Максимум к покупке, шт.": 100,
        "Спред, %": 0.5,
        "Спред к ОФЗ, б.п.": 350,
        "Новостных файлов": 2,
        "Критический новостной стоп": "НЕТ",
        "Риски": "—",
        "Недостающие данные": "—",
    }
    row.update(overrides)
    return pd.Series(row)


def test_decide_admits_strong_security_without_blockers():
    enabled = {"analysis", "deep_analysis", "credit", "news", "liquidity", "ofz_spread"}
    result = decide(_row(), enabled, "test.xlsx", [])
    assert result["Финальное решение"] == "Купить"
    assert result["Допущена в портфель"] == "ДА"
    assert result["Финальный балл"] >= 82
    assert result["Блокеры"] == "—"


def test_decide_rejects_critical_credit_rating():
    enabled = {"analysis", "deep_analysis", "credit"}
    result = decide(_row(Рейтинг="CCC"), enabled, "test.xlsx", [])
    assert result["Финальное решение"] == "Не покупать"
    assert result["Допущена в портфель"] == "НЕТ"
    assert "Недопустимый рейтинг CCC" in result["Блокеры"]


def test_shortlist_annotation_explains_duplicate_issuer():
    frame = pd.DataFrame([
        {
            "Код ценной бумаги": "SEC-1",
            "Эмитент": "Issuer A",
            "ИНН": "123",
            "Финальный балл": 90,
            "Допущена в портфель": "ДА",
            "Блокеры": "—",
            "Предупреждения": "—",
            "Недостающие кредитные данные": "—",
            "Модули без данных": "—",
            "Корректировка за рейтинг": 0,
        },
        {
            "Код ценной бумаги": "SEC-2",
            "Эмитент": "Issuer A",
            "ИНН": "123",
            "Финальный балл": 88,
            "Допущена в портфель": "ДА",
            "Блокеры": "—",
            "Предупреждения": "—",
            "Недостающие кредитные данные": "—",
            "Модули без данных": "—",
            "Корректировка за рейтинг": 0,
        },
    ])
    shortlist = {
        "shortlist": [{"secid": "SEC-1", "issuer": "Issuer A", "inn": "123"}],
        "thresholds": {"strong_score": 86, "max_shortlist": 12},
    }
    annotated = annotate_shortlist_reasons(frame, shortlist)
    assert annotated.loc[0, "В финальном shortlist"] == "ДА"
    assert "Дубликат эмитента" in annotated.loc[1, "Почему не shortlist"]
