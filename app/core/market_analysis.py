from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.core.pipeline_common import safe_float


@dataclass(frozen=True)
class MarketAnalysisResult:
    score: int
    decision: str
    positives: tuple[str, ...]
    risks: tuple[str, ...]
    hard_stop: bool
    ofz_adjustment: int

    def legacy_tuple(self) -> tuple[int, str, list[str], list[str], bool, int]:
        """Preserve the historical stage-5 scoring contract."""
        return (
            self.score,
            self.decision,
            list(self.positives),
            list(self.risks),
            self.hard_stop,
            self.ofz_adjustment,
        )


def yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"да", "yes", "true", "1"}


def ofz_spread_adjustment(row: Mapping[str, Any]) -> tuple[int, str | None, str | None]:
    quality = str(row.get("Качество данных спреда") or "").strip().upper()
    spread_bp = safe_float(row.get("Спред к ОФЗ, б.п."))
    if quality == "ОШИБКА":
        return 0, None, "Ошибка расчёта спреда к ОФЗ"
    if spread_bp is None:
        return 0, None, "Спред к ОФЗ неизвестен"
    if spread_bp < 0:
        return -6, None, "Доходность ниже сопоставимой ОФЗ"
    if spread_bp < 100:
        return -3, None, "Премия к ОФЗ меньше 100 б.п."
    if spread_bp < 300:
        return 3, "Умеренная премия к ОФЗ", None
    if spread_bp < 600:
        return 6, "Хорошая премия к ОФЗ", None
    if spread_bp < 1000:
        return 1, None, "Высокая премия к ОФЗ требует проверки кредитного риска"
    return -6, None, "Экстремальный спред к ОФЗ — вероятный высокий риск"


def analyze_market_row(row: Mapping[str, Any]) -> MarketAnalysisResult:
    score, good, risks = 0, [], []
    y = safe_float(row.get("Доходность"), 0) or 0
    price = safe_float(row.get("Цена, %"), 0) or 0
    duration = safe_float(row.get("Дюрация, месяцев"), 99) or 99
    volume = safe_float(row.get("Объем сделок с 15 дней, шт."), 0) or 0
    max_buy = safe_float(row.get("Максимум к покупке, руб."), 0) or 0
    spread = safe_float(row.get("Спред, %"))
    unknown = int(safe_float(row.get("Неизвестных купонов"), 0) or 0)
    hard_stop = yes(row.get("Критический новостной стоп"))

    if 15 <= y <= 22:
        score += 24
        good.append("Рабочая доходность")
    elif y < 15:
        score += 14
    elif y <= 27:
        score += 18
        risks.append("Повышенная доходность")
    else:
        score += 6
        risks.append("Очень высокая доходность — сигнал риска")

    if 90 <= price <= 105:
        score += 12
        good.append("Цена около номинала")
    elif 80 <= price <= 110:
        score += 8
    else:
        score += 3
        risks.append("Цена сильно отличается от номинала")

    if duration <= 12:
        score += 12
        good.append("Короткая/умеренная дюрация")
    elif duration <= 24:
        score += 8
    else:
        score += 3
        risks.append("Высокая чувствительность к ставке")

    if volume >= 200_000:
        score += 15
    elif volume >= 60_000:
        score += 10
    else:
        score += 3
        risks.append("Низкий объём торгов")

    if max_buy >= 100_000:
        score += 15
        good.append("Достаточный доступный объём")
    elif max_buy >= 30_000:
        score += 10
    elif max_buy > 0:
        score += 4
        risks.append("Ограниченный объём покупки")
    else:
        risks.append("Нет подтверждённого доступного объёма")

    if spread is not None:
        if spread <= 0.5:
            score += 8
            good.append("Узкий bid/ask-спред")
        elif spread <= 1.5:
            score += 5
        else:
            risks.append("Широкий bid/ask-спред")

    if unknown == 0:
        score += 7
        good.append("Будущие купоны известны")
    else:
        risks.append(f"Неизвестных будущих купонов: {unknown}")

    if not yes(row.get("Нужна квалификация?")):
        score += 7
    else:
        risks.append("Требуется статус квалифицированного инвестора")

    ofz_points, ofz_good, ofz_risk = ofz_spread_adjustment(row)
    score += ofz_points
    if ofz_good:
        good.append(ofz_good)
    if ofz_risk:
        risks.append(ofz_risk)

    if str(row.get("Полнота новостей") or "") == "Нет данных":
        risks.append("Нет новостных данных")
    if hard_stop:
        score = min(score, 15)
        risks.append("Критический новостной стоп")

    score = max(0, min(100, round(score)))
    if hard_stop or score < 45:
        decision = "Не покупать без ручного анализа"
    elif score >= 82:
        decision = "Рассматривать в первую очередь"
    elif score >= 68:
        decision = "Рассматривать"
    else:
        decision = "Требуется углублённая проверка"

    return MarketAnalysisResult(
        score=score,
        decision=decision,
        positives=tuple(good),
        risks=tuple(risks),
        hard_stop=hard_stop,
        ofz_adjustment=ofz_points,
    )


def score_row(row: Mapping[str, Any]) -> tuple[int, str, list[str], list[str], bool, int]:
    """Compatibility adapter for the historical stage-5 tuple API."""
    return analyze_market_row(row).legacy_tuple()
