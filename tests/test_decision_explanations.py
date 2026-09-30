import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "8_bonds_decision.py"
spec = importlib.util.spec_from_file_location("decision_module", MODULE_PATH)
decision = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = decision
assert spec.loader is not None
spec.loader.exec_module(decision)


def test_shortlist_explanations_cover_duplicate_threshold_and_blocker():
    frame = pd.DataFrame([
        {
            "Код ценной бумаги": "A1", "ИНН": "111", "Эмитент": "A",
            "Финальный балл": 89, "Допущена в портфель": "ДА",
            "Блокеры": "—", "Предупреждения": "—",
            "Недостающие кредитные данные": "—", "Модули без данных": "—",
            "Корректировка за рейтинг": 0,
        },
        {
            "Код ценной бумаги": "A2", "ИНН": "111", "Эмитент": "A",
            "Финальный балл": 87, "Допущена в портфель": "ДА",
            "Блокеры": "—", "Предупреждения": "—",
            "Недостающие кредитные данные": "Чистый долг/EBITDA", "Модули без данных": "—",
            "Корректировка за рейтинг": 0,
        },
        {
            "Код ценной бумаги": "B1", "ИНН": "222", "Эмитент": "B",
            "Финальный балл": 84, "Допущена в портфель": "ДА",
            "Блокеры": "—", "Предупреждения": "Высокий спред к ОФЗ",
            "Недостающие кредитные данные": "—", "Модули без данных": "—",
            "Корректировка за рейтинг": 0,
        },
        {
            "Код ценной бумаги": "C1", "ИНН": "333", "Эмитент": "C",
            "Финальный балл": 25, "Допущена в портфель": "НЕТ",
            "Блокеры": "Критический новостной стоп", "Предупреждения": "—",
            "Недостающие кредитные данные": "—", "Модули без данных": "news",
            "Корректировка за рейтинг": -5,
        },
    ])
    shortlist = {
        "shortlist": [{"secid": "A1", "inn": "111", "issuer": "A"}],
        "thresholds": {"strong_score": 86, "max_shortlist": 12},
    }

    result = decision._annotate_shortlist_reasons(frame, shortlist).set_index("Код ценной бумаги")

    assert result.loc["A1", "В финальном shortlist"] == "ДА"
    assert result.loc["A1", "Почему не shortlist"] == "Выбран в финальный shortlist"
    assert "Дубликат эмитента" in result.loc["A2", "Почему не shortlist"]
    assert "ниже порога сильного кандидата" in result.loc["B1", "Почему не shortlist"]
    assert "Критический новостной стоп" in result.loc["C1", "Почему не shortlist"]
    assert "Рейтинговые события" in result.loc["C1", "Почему потерял баллы"]
