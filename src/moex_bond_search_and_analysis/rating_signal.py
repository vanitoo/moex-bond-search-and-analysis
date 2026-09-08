from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CRITICAL_RATINGS = {"D", "C", "CC", "CCC"}
SEVERE_ACTIONS = {"ПОНИЖЕН", "ОТОЗВАН"}
SOFT_NEGATIVE_ACTIONS = {"ПРОГНОЗ ИЗМЕНЕН"}
POSITIVE_ACTIONS = {"ПОВЫШЕН"}
NEGATIVE_FORECASTS = {"негативный", "развивающийся"}
POSITIVE_FORECASTS = {"позитивный"}


@dataclass(frozen=True)
class RatingSignal:
    penalty: int = 0
    bonus: int = 0
    hard_stop: bool = False
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    positives: tuple[str, ...] = ()
    latest_rating: str = ""
    latest_forecast: str = ""
    latest_action: str = ""
    latest_agency: str = ""
    latest_event_date: str = ""


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_upper(value: Any) -> str:
    return _norm(value).upper()


def _parse_dt(value: Any) -> datetime:
    text = _norm(value)
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def load_rating_events(root: Path) -> list[dict[str, Any]]:
    candidates = list(root.glob("news*/**/_rating_events.json")) + list(root.glob("новости*/**/_rating_events.json"))
    if not candidates:
        return []
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in payload.get("events", []) if isinstance(item, dict)]


def events_for_secid(events: Iterable[dict[str, Any]], secid: str) -> list[dict[str, Any]]:
    needle = _norm_upper(secid)
    result: list[dict[str, Any]] = []
    for event in events:
        secids = {_norm_upper(value) for value in event.get("secids", [])}
        object_type = _norm(event.get("object_type"))
        if object_type == "Выпуск":
            title = _norm_upper(event.get("title"))
            if needle and needle in title:
                result.append(event)
        elif needle in secids:
            result.append(event)
    return sorted(result, key=lambda item: _parse_dt(item.get("event_date")), reverse=True)


def build_rating_signal(events: Iterable[dict[str, Any]], secid: str) -> RatingSignal:
    matched = events_for_secid(events, secid)
    if not matched:
        return RatingSignal()

    penalty = 0
    bonus = 0
    hard_stop = False
    reasons: list[str] = []
    warnings: list[str] = []
    positives: list[str] = []

    for event in matched:
        agency = _norm(event.get("agency")) or "Рейтинговое агентство"
        action = _norm_upper(event.get("action"))
        current = _norm_upper(event.get("current_rating"))
        previous = _norm_upper(event.get("previous_rating"))
        forecast = _norm(event.get("forecast"))
        forecast_norm = forecast.lower().replace("ё", "е")

        if current in CRITICAL_RATINGS:
            hard_stop = True
            reasons.append(f"{agency}: критический рейтинг {current}")

        if action == "ПОНИЖЕН":
            penalty += 12
            detail = f"{previous} → {current}" if previous and current else current or "без распознанного уровня"
            warnings.append(f"{agency}: рейтинг понижен ({detail})")
        elif action == "ОТОЗВАН":
            penalty += 8
            warnings.append(f"{agency}: рейтинг отозван")
        elif action in SOFT_NEGATIVE_ACTIONS:
            penalty += 3
            warnings.append(f"{agency}: изменён прогноз рейтинга")
        elif action in POSITIVE_ACTIONS:
            bonus += 4
            positives.append(f"{agency}: рейтинг повышен")

        if any(marker in forecast_norm for marker in NEGATIVE_FORECASTS):
            penalty += 6
            warnings.append(f"{agency}: прогноз {forecast}")
        elif any(marker in forecast_norm for marker in POSITIVE_FORECASTS):
            bonus += 2
            positives.append(f"{agency}: позитивный прогноз")

    latest = matched[0]
    return RatingSignal(
        penalty=penalty,
        bonus=bonus,
        hard_stop=hard_stop,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        positives=tuple(dict.fromkeys(positives)),
        latest_rating=_norm_upper(latest.get("current_rating")),
        latest_forecast=_norm(latest.get("forecast")),
        latest_action=_norm_upper(latest.get("action")),
        latest_agency=_norm(latest.get("agency")),
        latest_event_date=_norm(latest.get("event_date")),
    )
