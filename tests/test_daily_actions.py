from daily_actions import _monitor_actions, _reconcile_actions


def test_monitor_actions_detect_change():
    previous = {
        "positions": [
            {
                "Код ценной бумаги": "RU1",
                "Название": "Bond 1",
                "Рекомендация мониторинга": "ДЕРЖАТЬ",
            }
        ]
    }
    current = {
        "positions": [
            {
                "Код ценной бумаги": "RU1",
                "Название": "Bond 1",
                "Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
                "Причины рекомендации": "Рейтинг понижен",
                "Финальный балл": 67,
            }
        ]
    }
    actions, changes = _monitor_actions(current, previous)
    assert actions[0]["action"] == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"
    assert actions[0]["signal_days"] == 0
    assert actions[0]["signal_trend"] == ""

    assert len(changes) == 1
    change = changes[0]
    assert change["secid"] == "RU1"
    assert change["name"] == "Bond 1"
    assert change["from"] == "ДЕРЖАТЬ"
    assert change["to"] == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"
    assert change["reason"] == "Рейтинг понижен"
    assert change["signal_days"] == 0
    assert change["signal_trend"] == ""


def test_monitor_actions_detect_signal_trend_change_without_action_change():
    previous = {
        "positions": [
            {
                "Код ценной бумаги": "RU1",
                "Название": "Bond 1",
                "Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
                "Динамика сигнала": "ДЕРЖИТСЯ 2 ДН.",
                "Сигнал дней": 2,
            }
        ]
    }
    current = {
        "positions": [
            {
                "Код ценной бумаги": "RU1",
                "Название": "Bond 1",
                "Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
                "Причины рекомендации": "Спред вырос",
                "Динамика сигнала": "УСИЛИЛСЯ",
                "Сигнал дней": 3,
            }
        ]
    }
    actions, changes = _monitor_actions(current, previous)
    assert actions[0]["signal_days"] == 3
    assert actions[0]["signal_trend"] == "УСИЛИЛСЯ"
    assert len(changes) == 1
    assert changes[0]["from"] == changes[0]["to"] == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"
    assert changes[0]["signal_trend"] == "УСИЛИЛСЯ"
    assert changes[0]["signal_days"] == 3


def test_monitor_actions_without_previous_change():
    current = {
        "positions": [
            {
                "Код ценной бумаги": "RU2",
                "Название": "Bond 2",
                "Рекомендация мониторинга": "ДЕРЖАТЬ",
                "Причины рекомендации": "Критических ухудшений не обнаружено",
            }
        ]
    }
    actions, changes = _monitor_actions(current, None)
    assert actions[0]["action"] == "ДЕРЖАТЬ"
    assert changes == []


def test_reconcile_blocks_add_when_monitor_warns():
    monitor = [{"action": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ", "secid": "RU1", "reason": "Негативный прогноз"}]
    candidates = [{"action": "ДОКУПИТЬ", "secid": "RU1", "reason": "Высокий скоринг", "amount": 50000}]
    result = _reconcile_actions(monitor, candidates)
    assert len(result) == 1
    assert result[0]["action"] == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"


def test_reconcile_upgrades_clean_hold_to_add():
    monitor = [{"action": "ДЕРЖАТЬ", "secid": "RU2", "reason": "Критических ухудшений не обнаружено"}]
    candidates = [{"action": "ДОКУПИТЬ", "secid": "RU2", "reason": "Высокий скоринг", "amount": 50000, "confidence": "высокая"}]
    result = _reconcile_actions(monitor, candidates)
    assert len(result) == 1
    assert result[0]["action"] == "ДОКУПИТЬ"
    assert result[0]["amount"] == 50000
