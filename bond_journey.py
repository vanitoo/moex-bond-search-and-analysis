from __future__ import annotations

from typing import Any

from portfolio_impact import deep_get, safe_float


STAGES = [
    ("Поиск", "market_search"),
    ("Cashflow", "cashflow"),
    ("Новости", "news"),
    ("Ликвидность", "liquidity"),
    ("Спред к ОФЗ", "ofz_spread"),
    ("Анализ", "analysis"),
    ("Deep analysis", "deep_analysis"),
    ("Credit", "credit"),
    ("Decision", "decision"),
]


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _raw(bond: dict[str, Any], module: str) -> dict[str, Any]:
    raw = bond.get("raw", {}).get(module, {})
    return raw if isinstance(raw, dict) else {}


def _first(raw: dict[str, Any], *names: str) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
        value = lowered.get(name.strip().lower())
        if value not in (None, ""):
            return value
    return None


def _trace(bond: dict[str, Any], module: str) -> dict[str, Any]:
    value = bond.get("modules", {}).get(module, {})
    return value if isinstance(value, dict) else {}


def _trace_reason(event: dict[str, Any]) -> str:
    for key in ("reason", "message", "details", "result", "summary"):
        value = event.get(key)
        if value not in (None, ""):
            return _text(value)
    return ""


def _trace_status(event: dict[str, Any]) -> str:
    value = _text(event.get("status") or event.get("state")).upper()
    return value


def journey_rows(bond: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for title, module in STAGES:
        event = _trace(bond, module)
        status = _trace_status(event)
        reason = _trace_reason(event)
        result = ""
        score: float | None = None

        if module == "market_search":
            result = f"YTM {deep_get(bond, 'market.yield')}% · цена {deep_get(bond, 'market.price')}%" if deep_get(bond, "market.yield") is not None else "Найдена"
        elif module == "cashflow":
            result = _text(deep_get(bond, "cashflow.completeness")) or "Данные получены"
            reason = reason or _text(_first(_raw(bond, module), "Причина", "Комментарий"))
        elif module == "news":
            result = _text(deep_get(bond, "news.completeness")) or "Нет итоговой оценки"
            negatives = _text(deep_get(bond, "news.negative"))
            if negatives:
                reason = reason or negatives
        elif module == "liquidity":
            quality = _text(deep_get(bond, "liquidity.quality"))
            spread = deep_get(bond, "liquidity.spread_percent")
            result = quality or (f"Bid/Ask {spread}%" if spread is not None else "Данные получены")
        elif module == "ofz_spread":
            spread = deep_get(bond, "ofz_spread.spread_bp")
            risk_class = _text(deep_get(bond, "ofz_spread.risk_class"))
            result = f"{spread:.0f} б.п." if isinstance(spread, (int, float)) else risk_class or "Данные получены"
            reason = reason or risk_class
        elif module == "analysis":
            score = safe_float(deep_get(bond, "analysis.score"))
            result = _text(deep_get(bond, "analysis.recommendation")) or "Рассчитано"
        elif module == "deep_analysis":
            score = safe_float(deep_get(bond, "deep_analysis.score"))
            result = _text(deep_get(bond, "deep_analysis.recommendation")) or "Рассчитано"
        elif module == "credit":
            score = safe_float(deep_get(bond, "credit.score"))
            rating = _text(deep_get(bond, "credit.rating"))
            agency = _text(deep_get(bond, "credit.agency"))
            result = " · ".join(x for x in (rating, agency) if x) or "Данные получены"
            reason = reason or _text(deep_get(bond, "credit.missing_data"))
        elif module == "decision":
            score = safe_float(deep_get(bond, "decision.score"))
            result = _text(deep_get(bond, "decision.status")) or "Нет решения"
            raw = _raw(bond, module)
            rating_action = _text(_first(raw, "Рейтинговое событие", "Действие рейтинга", "rating_action"))
            rating_forecast = _text(_first(raw, "Прогноз рейтинга", "Рейтинговый прогноз", "rating_forecast"))
            decision_reason = _text(deep_get(bond, "decision.reasons")) or _text(deep_get(bond, "decision.blockers"))
            reason = reason or " · ".join(x for x in (rating_action, rating_forecast, decision_reason) if x)

        if not status:
            has_data = bool(_raw(bond, module)) or bool(event)
            status = "OK" if has_data else "NO_DATA"

        rows.append({"Этап": title, "Статус": status, "Результат": result or "—", "Баллы": score, "Причина": reason or "—"})
    return rows


def route_text(bond: dict[str, Any]) -> str:
    chunks: list[str] = []
    for row in journey_rows(bond):
        result = row["Результат"]
        if result and result != "—":
            chunks.append(f"{row['Этап']}: {result}")
    return " → ".join(chunks)
