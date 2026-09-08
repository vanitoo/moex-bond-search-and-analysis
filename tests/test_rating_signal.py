from __future__ import annotations

from moex_bond_search_and_analysis.rating_signal import build_rating_signal, events_for_secid


def event(**overrides):
    base = {
        "company": "Issuer",
        "secids": ["RU000A000001", "RU000A000002"],
        "agency": "АКРА",
        "action": "ПОНИЖЕН",
        "current_rating": "BB+",
        "previous_rating": "BBB-",
        "forecast": "Негативный",
        "event_date": "2026-09-09T10:00:00",
        "object_type": "Эмитент",
        "source_url": "https://example.test/rating",
        "title": "АКРА понизило рейтинг",
    }
    base.update(overrides)
    return base


def test_issuer_event_applies_to_all_issuer_secids():
    events = [event()]
    assert len(events_for_secid(events, "RU000A000001")) == 1
    assert len(events_for_secid(events, "RU000A000002")) == 1


def test_issue_event_applies_only_when_secid_is_in_title():
    events = [event(object_type="Выпуск", title="Рейтинг выпуска RU000A000001 понижен")]
    assert len(events_for_secid(events, "RU000A000001")) == 1
    assert len(events_for_secid(events, "RU000A000002")) == 0


def test_downgrade_and_negative_outlook_reduce_score_without_hard_stop():
    signal = build_rating_signal([event()], "RU000A000001")
    assert signal.penalty == 18
    assert signal.bonus == 0
    assert signal.hard_stop is False


def test_withdrawal_is_warning_not_automatic_hard_stop():
    signal = build_rating_signal([
        event(action="ОТОЗВАН", current_rating="BB+", previous_rating="", forecast="")
    ], "RU000A000001")
    assert signal.penalty == 8
    assert signal.hard_stop is False


def test_critical_rating_is_hard_stop():
    signal = build_rating_signal([
        event(action="ПОНИЖЕН", current_rating="CCC", previous_rating="B-", forecast="Негативный")
    ], "RU000A000001")
    assert signal.hard_stop is True
    assert any("критический рейтинг CCC" in reason for reason in signal.reasons)


def test_upgrade_and_positive_outlook_add_bonus():
    signal = build_rating_signal([
        event(action="ПОВЫШЕН", current_rating="A", previous_rating="A-", forecast="Позитивный")
    ], "RU000A000001")
    assert signal.bonus == 6
    assert signal.penalty == 0
