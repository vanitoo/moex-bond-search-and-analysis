from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(str(value).replace(" ", "").replace(",", "."))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize_rating(value: Any) -> str:
    raw = str(value or "").upper().replace("(RU)", "").replace("RU", "")
    text = re.sub(r"[^A-Z+\-]", "", raw)
    for item in sorted(RATING_ORDER, key=len, reverse=True):
        if item in text:
            return item
    return ""


def deep_get(item: dict[str, Any], dotted_path: str) -> Any:
    value: Any = item
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def infer_issuer(bond: dict[str, Any], position: dict[str, Any] | None = None) -> str:
    position = position or {}
    for key in ("issuer", "Эмитент", "issuer_name", "Название эмитента"):
        value = position.get(key)
        if value:
            return str(value).strip()
    for key in ("issuer", "issuer_name"):
        value = bond.get(key)
        if value:
            return str(value).strip()
    for raw in (bond.get("raw") or {}).values():
        if not isinstance(raw, dict):
            continue
        for key in ("Эмитент", "Название эмитента", "Наименование эмитента", "issuer", "issuer_name"):
            value = raw.get(key)
            if value:
                return str(value).strip()
    return ""


def position_amount(position: dict[str, Any]) -> float:
    for key in ("market_value", "current_value", "value", "invested", "Вложено, руб.", "Рыночная стоимость, руб."):
        value = safe_float(position.get(key))
        if value is not None and value > 0:
            return value
    return 0.0


def bond_yield(bond: dict[str, Any], position: dict[str, Any] | None = None) -> float | None:
    position = position or {}
    for key in ("yield", "ytm", "Доходность", "Доходность, %"):
        value = safe_float(position.get(key))
        if value is not None:
            return value
    return safe_float(deep_get(bond, "market.yield"))


def risk_level(bond: dict[str, Any], position: dict[str, Any] | None = None) -> str | None:
    position = position or {}
    rating = normalize_rating(position.get("rating") or position.get("Рейтинг") or deep_get(bond, "credit.rating"))
    score = safe_float(deep_get(bond, "decision.score"))
    spread = safe_float(deep_get(bond, "ofz_spread.spread_bp"))
    decision = str(deep_get(bond, "decision.status") or "").lower()

    if "не покупать" in decision:
        return "high"
    if rating:
        idx = RATING_ORDER.index(rating)
        if idx < RATING_ORDER.index("BBB-"):
            return "high"
        if idx <= RATING_ORDER.index("BBB+"):
            return "medium"
        return "low"
    if score is not None:
        if score < 60:
            return "high"
        if score < 75:
            return "medium"
        return "low"
    if spread is not None:
        if spread >= 1000:
            return "high"
        if spread >= 600:
            return "medium"
        return "low"
    return None


def load_portfolios(portfolio_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not portfolio_dir.exists():
        return result
    for path in sorted(portfolio_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
            result[path.stem] = payload
    return result


def _weighted_yield(rows: list[dict[str, Any]]) -> tuple[float | None, float]:
    total = sum(row["amount"] for row in rows)
    known = [row for row in rows if row.get("yield") is not None]
    known_amount = sum(row["amount"] for row in known)
    if known_amount <= 0:
        return None, 0.0
    value = sum(row["amount"] * float(row["yield"]) for row in known) / known_amount
    coverage = known_amount / total * 100 if total > 0 else 0.0
    return value, coverage


def _effective_positions(rows: list[dict[str, Any]]) -> float:
    total = sum(row["amount"] for row in rows)
    if total <= 0:
        return 0.0
    weights = [row["amount"] / total for row in rows if row["amount"] > 0]
    denom = sum(weight * weight for weight in weights)
    return 1.0 / denom if denom > 0 else 0.0


def _risk_stats(rows: list[dict[str, Any]]) -> tuple[float, float]:
    total = sum(row["amount"] for row in rows)
    if total <= 0:
        return 0.0, 0.0
    known = [row for row in rows if row.get("risk") in {"low", "medium", "high"}]
    known_amount = sum(row["amount"] for row in known)
    high_amount = sum(row["amount"] for row in known if row.get("risk") == "high")
    return high_amount / total * 100, known_amount / total * 100


def portfolio_rows(portfolio: dict[str, Any], bonds_by_secid: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or position.get("SECID") or position.get("Код ценной бумаги") or "").strip()
        amount = position_amount(position)
        if not secid or amount <= 0:
            continue
        bond = bonds_by_secid.get(secid, {})
        rows.append({
            "secid": secid,
            "amount": amount,
            "issuer": infer_issuer(bond, position),
            "yield": bond_yield(bond, position),
            "risk": risk_level(bond, position),
        })
    return rows


def simulate_purchase(
    portfolio: dict[str, Any],
    candidate: dict[str, Any],
    amount: float,
    bonds_by_secid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    base = portfolio_rows(portfolio, bonds_by_secid)
    total_before = sum(row["amount"] for row in base)
    candidate_issuer = infer_issuer(candidate)
    candidate_risk = risk_level(candidate)
    candidate_yield = bond_yield(candidate)
    candidate_secid = str(candidate.get("secid") or "")

    candidate_row = {
        "secid": candidate_secid,
        "amount": float(amount),
        "issuer": candidate_issuer,
        "yield": candidate_yield,
        "risk": candidate_risk,
    }
    after = base + [candidate_row]
    total_after = total_before + amount

    ytm_before, yield_coverage_before = _weighted_yield(base)
    ytm_after, yield_coverage_after = _weighted_yield(after)
    risk_before, risk_coverage_before = _risk_stats(base)
    risk_after, risk_coverage_after = _risk_stats(after)

    max_position_before = max((row["amount"] / total_before * 100 for row in base), default=0.0) if total_before else 0.0
    max_position_after = max((row["amount"] / total_after * 100 for row in after), default=0.0) if total_after else 0.0
    candidate_share = amount / total_after * 100 if total_after else 0.0

    issuer_share_after: float | None = None
    if candidate_issuer and total_after > 0:
        issuer_amount = amount + sum(row["amount"] for row in base if row.get("issuer") == candidate_issuer)
        issuer_share_after = issuer_amount / total_after * 100

    max_purchase = safe_float(deep_get(candidate, "liquidity.max_purchase_rub"))
    liquidity_ok = None if max_purchase is None else amount <= max_purchase

    notes: list[str] = []
    if liquidity_ok is False:
        notes.append("сумма выше рассчитанного лимита ликвидности")
    if candidate_share >= 20:
        notes.append("доля одного выпуска после покупки ≥ 20%")
    if issuer_share_after is not None and issuer_share_after >= 25:
        notes.append("доля эмитента после покупки ≥ 25%")
    if candidate_risk == "high":
        notes.append("кандидат относится к высокой группе риска")
    if _effective_positions(after) > _effective_positions(base) + 0.05:
        notes.append("диверсификация по выпускам улучшается")
    elif _effective_positions(after) < _effective_positions(base) - 0.05:
        notes.append("диверсификация по выпускам ухудшается")

    return {
        "secid": candidate_secid,
        "amount": amount,
        "total_before": total_before,
        "total_after": total_after,
        "candidate_share_percent": candidate_share,
        "issuer": candidate_issuer or None,
        "issuer_share_after_percent": issuer_share_after,
        "weighted_yield_before": ytm_before,
        "weighted_yield_after": ytm_after,
        "yield_coverage_before_percent": yield_coverage_before,
        "yield_coverage_after_percent": yield_coverage_after,
        "high_risk_share_before_percent": risk_before,
        "high_risk_share_after_percent": risk_after,
        "risk_coverage_before_percent": risk_coverage_before,
        "risk_coverage_after_percent": risk_coverage_after,
        "max_position_share_before_percent": max_position_before,
        "max_position_share_after_percent": max_position_after,
        "effective_positions_before": _effective_positions(base),
        "effective_positions_after": _effective_positions(after),
        "candidate_risk": candidate_risk,
        "max_purchase_rub": max_purchase,
        "liquidity_ok": liquidity_ok,
        "notes": notes,
    }
