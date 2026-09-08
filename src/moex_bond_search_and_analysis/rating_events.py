from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from moex_bond_search_and_analysis.schemas import NewsItem


RATING_TOKEN = re.compile(
    r"(?<![A-ZА-Я0-9])(?:ru)?(?:AAA|AA|A|BBB|BB|B|CCC|CC|C|D)[+\-]?(?:\(RU\))?(?![A-ZА-Я0-9])",
    re.IGNORECASE,
)


@dataclass
class RatingEvent:
    company: str
    secids: list[str]
    agency: str
    action: str
    current_rating: str
    previous_rating: str
    forecast: str
    event_date: str
    object_type: str
    source_url: str
    title: str

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_rating(value: str) -> str:
    text = str(value or "").upper().replace(" ", "")
    text = text.replace("(RU)", "").removeprefix("RU")
    return text


def detect_action(text: str) -> str:
    value = text.lower().replace("ё", "е")
    checks = (
        ("ОТОЗВАН", ("отозвал", "отозван", "отзывает")),
        ("ПОНИЖЕН", ("понизил", "понижен", "снизил рейтинг", "рейтинг снижен")),
        ("ПОВЫШЕН", ("повысил", "повышен", "рейтинг повышен")),
        ("ПОДТВЕРЖДЕН", ("подтвердил", "подтвержден", "подтверждает")),
        ("ПРИСВОЕН", ("присвоил", "присвоен", "присваивает")),
        ("ПРОГНОЗ ИЗМЕНЕН", ("изменил прогноз", "прогноз изменен", "пересмотрел прогноз")),
    )
    for action, markers in checks:
        if any(marker in value for marker in markers):
            return action
    return "ИНФОРМАЦИЯ"


def detect_forecast(text: str) -> str:
    value = text.lower().replace("ё", "е")
    for word, label in (
        ("позитив", "Позитивный"),
        ("негатив", "Негативный"),
        ("развива", "Развивающийся"),
        ("стабиль", "Стабильный"),
    ):
        if word in value:
            return label
    return ""


def _ratings(text: str) -> list[str]:
    values: list[str] = []
    for match in RATING_TOKEN.finditer(text):
        rating = normalize_rating(match.group(0))
        if rating and rating not in values:
            values.append(rating)
    return values


def parse_rating_event(company: str, secids: Iterable[str], item: NewsItem) -> RatingEvent | None:
    source = str(item.source or "")
    source_norm = source.lower()
    if "акра" not in source_norm and "эксперт" not in source_norm:
        return None

    title = str(item.title or "").strip()
    action = detect_action(title)
    ratings = _ratings(title)
    if action == "ИНФОРМАЦИЯ" and not ratings and not detect_forecast(title):
        return None

    current = ratings[-1] if ratings else ""
    previous = ""
    if len(ratings) >= 2:
        lower = title.lower().replace("ё", "е")
        if " с " in lower and " до " in lower:
            previous, current = ratings[0], ratings[-1]
        elif action in {"ПОВЫШЕН", "ПОНИЖЕН"}:
            previous, current = ratings[0], ratings[-1]

    secid_values = [str(value).strip().upper() for value in secids if str(value).strip()]
    title_upper = title.upper()
    object_type = "Выпуск" if any(secid in title_upper for secid in secid_values) else "Эмитент"
    event_date = item.date.isoformat(timespec="seconds") if item.date else ""

    return RatingEvent(
        company=company,
        secids=secid_values,
        agency="АКРА" if "акра" in source_norm else "Эксперт РА",
        action=action,
        current_rating=current,
        previous_rating=previous,
        forecast=detect_forecast(title),
        event_date=event_date,
        object_type=object_type,
        source_url=str(item.url or ""),
        title=title,
    )


def extract_rating_events(company: str, secids: Iterable[str], items: Iterable[NewsItem]) -> list[RatingEvent]:
    result: list[RatingEvent] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        event = parse_rating_event(company, secids, item)
        if event is None:
            continue
        key = (event.agency, event.action, event.current_rating, event.source_url or event.title)
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result
