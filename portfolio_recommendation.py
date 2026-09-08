from __future__ import annotations

from typing import Any

from portfolio_impact import deep_get, infer_issuer, risk_level, safe_float, simulate_purchase


KEY_DATA_PATHS = (
    "market.yield",
    "liquidity.max_purchase_rub",
    "ofz_spread.spread_bp",
    "credit.rating",
    "decision.score",
    "decision.status",
)


def _score(bond: dict[str, Any]) -> float | None:
    for path in ("decision.score", "deep_analysis.score", "analysis.score"):
        value = safe_float(deep_get(bond, path))
        if value is not None:
            return value
    return None


def _position_secid(position: dict[str, Any]) -> str:
    return str(position.get("secid") or position.get("SECID") or position.get("Код ценной бумаги") or "").strip()


def _has_hard_stop(bond: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    decision = str(deep_get(bond, "decision.status") or "").strip().lower()
    if "не покупать" in decision:
        reasons.append("финальный модуль пометил выпуск как «Не покупать»")

    if deep_get(bond, "news.critical_stop") is True:
        reasons.append("есть критический новостной стоп")

    for event in (bond.get("modules") or {}).values():
        if not isinstance(event, dict):
            continue
        if event.get("hard_stop") is True:
            reason = str(event.get("reason") or "жёсткий стоп одного из модулей")
            if reason not in reasons:
                reasons.append(reason)

    return bool(reasons), reasons


def _data_coverage(bond: dict[str, Any]) -> tuple[int, int, list[str]]:
    present = 0
    missing: list[str] = []
    labels = {
        "market.yield": "доходность",
        "liquidity.max_purchase_rub": "ликвидность",
        "ofz_spread.spread_bp": "спред к ОФЗ",
        "credit.rating": "кредитный рейтинг",
        "decision.score": "финальный балл",
        "decision.status": "финальное решение",
    }
    for path in KEY_DATA_PATHS:
        value = deep_get(bond, path)
        if value not in (None, ""):
            present += 1
        else:
            missing.append(labels[path])
    return present, len(KEY_DATA_PATHS), missing


def _risk_rank(value: str | None) -> int:
    return {None: 3, "low": 0, "medium": 1, "high": 2}.get(value, 3)


def _weakest_position(
    portfolio: dict[str, Any],
    candidate: dict[str, Any],
    bonds_by_secid: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidate_score = _score(candidate)
    candidate_risk = risk_level(candidate)
    if candidate_score is None:
        return None

    options: list[dict[str, Any]] = []
    for position in portfolio.get("positions", []):
        secid = _position_secid(position)
        bond = bonds_by_secid.get(secid)
        if not bond:
            continue
        score = _score(bond)
        risk = risk_level(bond, position)
        if score is None:
            continue
        improvement = candidate_score - score
        risk_improves = _risk_rank(candidate_risk) < _risk_rank(risk)
        if improvement >= 12 or (improvement >= 5 and risk_improves):
            options.append({
                "secid": secid,
                "name": position.get("name") or bond.get("name") or secid,
                "score": score,
                "risk": risk,
                "improvement": improvement,
            })
    if not options:
        return None
    return max(options, key=lambda item: (item["improvement"], _risk_rank(item.get("risk"))))


def recommend_candidate(
    portfolio: dict[str, Any],
    candidate: dict[str, Any],
    amount: float,
    bonds_by_secid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return an explainable portfolio action. No trade is executed."""
    scenario = simulate_purchase(portfolio, candidate, amount, bonds_by_secid)
    secid = str(candidate.get("secid") or "")
    held = any(_position_secid(item) == secid for item in portfolio.get("positions", []))
    score = _score(candidate)
    risk = risk_level(candidate)
    issuer = infer_issuer(candidate)
    present, total, missing = _data_coverage(candidate)
    hard_stop, hard_reasons = _has_hard_stop(candidate)

    positives: list[str] = []
    negatives: list[str] = []
    warnings: list[str] = []

    if score is not None:
        if score >= 80:
            positives.append(f"высокий текущий скоринг: {score:.0f}")
        elif score < 60:
            negatives.append(f"низкий текущий скоринг: {score:.0f}")

    ytm_before = scenario.get("weighted_yield_before")
    ytm_after = scenario.get("weighted_yield_after")
    if ytm_before is not None and ytm_after is not None:
        delta = float(ytm_after) - float(ytm_before)
        if delta >= 0.25:
            positives.append(f"средняя YTM портфеля растёт примерно на {delta:.2f} п.п.")
        elif delta <= -0.25:
            negatives.append(f"средняя YTM портфеля снижается примерно на {abs(delta):.2f} п.п.")

    eff_before = safe_float(scenario.get("effective_positions_before")) or 0.0
    eff_after = safe_float(scenario.get("effective_positions_after")) or 0.0
    if eff_after > eff_before + 0.05:
        positives.append("диверсификация по выпускам улучшается")
    elif eff_after < eff_before - 0.05:
        negatives.append("диверсификация по выпускам ухудшается")

    share = safe_float(scenario.get("candidate_share_percent")) or 0.0
    issuer_share = safe_float(scenario.get("issuer_share_after_percent"))
    if share >= 20:
        negatives.append(f"доля выпуска после покупки будет {share:.1f}% (выше порога 20%)")
    if issuer_share is not None and issuer_share >= 25:
        negatives.append(f"доля эмитента после покупки будет {issuer_share:.1f}% (выше порога 25%)")
    if scenario.get("liquidity_ok") is False:
        negatives.append("заданная сумма выше расчётного лимита ликвидности")
    if risk == "high":
        negatives.append("кандидат относится к высокой группе риска")
    elif risk == "low":
        positives.append("по доступным данным риск кандидата низкий")

    if missing:
        warnings.append("не хватает данных: " + ", ".join(missing))

    decision_known = deep_get(candidate, "decision.status") not in (None, "")
    credit_known = deep_get(candidate, "credit.rating") not in (None, "") or deep_get(candidate, "credit.score") not in (None, "")
    liquidity_known = deep_get(candidate, "liquidity.max_purchase_rub") not in (None, "")
    enough_for_positive_action = decision_known and credit_known and liquidity_known

    replacement = _weakest_position(portfolio, candidate, bonds_by_secid) if not held else None

    if hard_stop:
        action = "НЕ ПОКУПАТЬ"
        negatives = hard_reasons + negatives
    elif not enough_for_positive_action:
        action = "ОЖИДАЕТ ДАННЫХ"
        warnings.insert(0, "положительное или отрицательное инвестиционное решение ещё не сформировано")
    elif risk == "high" or score is not None and score < 60:
        action = "НЕ ПОКУПАТЬ"
    elif scenario.get("liquidity_ok") is False or share >= 20 or (issuer_share is not None and issuer_share >= 25):
        action = "НЕ ПОКУПАТЬ"
    elif held:
        action = "ДОКУПИТЬ"
    elif replacement is not None:
        action = "ЗАМЕНИТЬ"
        positives.append(
            f"кандидат сильнее позиции {replacement['name']}: преимущество по скорингу около {replacement['improvement']:.0f} баллов"
        )
    else:
        action = "КУПИТЬ"

    confidence = "низкая"
    ratio = present / total if total else 0.0
    if ratio >= 0.83 and decision_known and credit_known and liquidity_known:
        confidence = "высокая"
    elif ratio >= 0.50:
        confidence = "средняя"

    return {
        "action": action,
        "secid": secid,
        "name": candidate.get("name") or secid,
        "issuer": issuer or None,
        "amount": amount,
        "score": score,
        "risk": risk,
        "confidence": confidence,
        "data_present": present,
        "data_total": total,
        "positives": positives,
        "negatives": negatives,
        "warnings": warnings,
        "replacement": replacement,
        "scenario": scenario,
    }
