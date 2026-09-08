from datetime import datetime

from moex_bond_search_and_analysis.rating_events import extract_rating_events, parse_rating_event
from moex_bond_search_and_analysis.schemas import NewsItem


def test_parse_acra_upgrade_event():
    item = NewsItem(
        source="АКРА",
        title='АКРА повысило кредитный рейтинг компании до A+(RU), прогноз "Стабильный"',
        date=datetime(2026, 9, 9, 10, 30),
        url="https://example.test/acra",
    )
    event = parse_rating_event("Компания", ["RU000A123456"], item)
    assert event is not None
    assert event.agency == "АКРА"
    assert event.action == "ПОВЫШЕН"
    assert event.current_rating == "A+"
    assert event.forecast == "Стабильный"
    assert event.object_type == "Эмитент"


def test_parse_expert_ra_downgrade_with_previous_rating():
    item = NewsItem(
        source="Эксперт РА",
        title="Эксперт РА понизил рейтинг облигаций RU000A123456 с AA- до A+, прогноз негативный",
        date=datetime(2026, 9, 9),
        url="https://example.test/expert",
    )
    event = parse_rating_event("Компания", ["RU000A123456"], item)
    assert event is not None
    assert event.action == "ПОНИЖЕН"
    assert event.previous_rating == "AA-"
    assert event.current_rating == "A+"
    assert event.forecast == "Негативный"
    assert event.object_type == "Выпуск"


def test_non_rating_news_is_ignored():
    item = NewsItem(
        source="Эксперт РА",
        title="Компания опубликовала годовой отчет",
        date=datetime(2026, 9, 9),
        url="https://example.test/news",
    )
    assert extract_rating_events("Компания", [], [item]) == []
