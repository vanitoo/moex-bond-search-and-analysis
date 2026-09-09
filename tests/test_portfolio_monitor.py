import importlib.util
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "10_portfolio_monitor.py"
spec = importlib.util.spec_from_file_location("portfolio_monitor", MODULE_PATH)
monitor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(monitor)


def test_hard_stop_means_sell():
    action, reasons = monitor.classify_action(
        {
            "Финальное решение": "Не покупать",
            "Рейтинг": "BBB-",
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "—",
        },
        None,
    )
    assert action == "ПРОДАТЬ"
    assert reasons


def test_multiple_soft_deteriorations_mean_reduce():
    action, reasons = monitor.classify_action(
        {
            "Финальное решение": "Рассматривать",
            "Финальный балл": 65,
            "Рейтинг": "BBB-",
            "Спред к ОФЗ, б.п.": 750,
            "Цена, %": 88,
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "—",
        },
        {
            "Финальный балл": 85,
            "Рейтинг": "A-",
            "Спред к ОФЗ, б.п.": 300,
            "Цена, %": 100,
        },
    )
    assert action == "СОКРАТИТЬ НА 50%"
    assert any("Баллы снизились" in reason for reason in reasons)


def test_stable_position_means_hold():
    action, reasons = monitor.classify_action(
        {
            "Финальное решение": "Купить",
            "Финальный балл": 88,
            "Рейтинг": "A-",
            "Спред к ОФЗ, б.п.": 320,
            "Цена, %": 100,
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "—",
        },
        {
            "Финальный балл": 87,
            "Рейтинг": "A-",
            "Спред к ОФЗ, б.п.": 300,
            "Цена, %": 101,
        },
    )
    assert action == "ДЕРЖАТЬ"
    assert reasons == ["Критических ухудшений не обнаружено"]


def test_absent_fresh_decision_is_review_not_forced_sale():
    action, reasons = monitor.classify_action(
        {
            "Финальное решение": "",
            "Рейтинг": "BBB+",
            "Жёсткий стоп": "НЕТ",
            "Блокеры": "—",
        },
        None,
    )
    assert action == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"
    assert any("отсутствует" in reason for reason in reasons)


def test_signal_persistence_tracks_days_and_strengthening():
    history = [
        {
            "Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
            "_snapshot_day": "2026-09-05",
        },
        {
            "Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
            "_snapshot_day": "2026-09-08",
        },
    ]
    persistence = monitor.signal_persistence(
        "СОКРАТИТЬ НА 50%",
        history,
        now=datetime(2026, 9, 9, 12, 0, 0),
    )
    assert persistence["first_seen"] == "2026-09-05"
    assert persistence["days"] == 5
    assert persistence["trend"] == "УСИЛИЛСЯ"


def test_signal_disappearance_is_reported():
    persistence = monitor.signal_persistence(
        "ДЕРЖАТЬ",
        [{"Рекомендация мониторинга": "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ", "_snapshot_day": "2026-09-08"}],
        now=datetime(2026, 9, 9, 12, 0, 0),
    )
    assert persistence["days"] == 0
    assert persistence["trend"] == "ИСЧЕЗ"


def test_persistent_material_review_escalates_to_reduce():
    action, reasons = monitor.apply_signal_persistence(
        "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
        ["Высокий спред к ОФЗ: 650 б.п."],
        {"first_seen": "2026-09-05", "days": 5, "trend": "ДЕРЖИТСЯ 5 ДН."},
    )
    assert action == "СОКРАТИТЬ НА 50%"
    assert any("5+ дней" in reason for reason in reasons)


def test_persistent_generic_review_does_not_force_reduce():
    action, reasons = monitor.apply_signal_persistence(
        "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ",
        ["Решение ухудшилось до «Рассматривать»"],
        {"first_seen": "2026-09-01", "days": 9, "trend": "ДЕРЖИТСЯ 9 ДН."},
    )
    assert action == "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ"
    assert reasons
