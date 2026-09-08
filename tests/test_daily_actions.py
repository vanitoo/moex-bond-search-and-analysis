from daily_actions import _monitor_actions


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
    assert changes == [{
        "secid": "RU1",
        "name": "Bond 1",
        "from": "ДЕРЖАТЬ",
        "to": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
        "reason": "Рейтинг понижен",
    }]


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
