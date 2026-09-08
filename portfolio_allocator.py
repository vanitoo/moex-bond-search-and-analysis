from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from portfolio_impact import deep_get, infer_issuer, portfolio_rows, risk_level, safe_float


@dataclass(frozen=True)
class AllocationLine:
    secid: str
    name: str
    issuer: str
    quantity: int
    unit_cost: float
    amount: float
    share_percent: float
    score: float | None
    risk: str | None
    action: str
    reason: str


def _unit_cost(bond: dict[str, Any]) -> float | None:
    face = safe_float(deep_get(bond, "market.face_value")) or 1000.0
    price = safe_float(deep_get(bond, "market.price"))
    if price is None or price <= 0:
        return None
    return face * price / 100.0


def _score(bond: dict[str, Any]) -> float | None:
    for path in ("decision.score", "deep_analysis.score", "analysis.score"):
        value = safe_float(deep_get(bond, path))
        if value is not None:
            return value
    return None


def _position_secids(portfolio: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in portfolio.get("positions", []):
        secid = str(item.get("secid") or item.get("SECID") or item.get("Код ценной бумаги") or "").strip()
        if secid:
            result.add(secid)
    return result


def _eligibility(bond: dict[str, Any], held: bool) -> tuple[bool, str, str]:
    """Check investment eligibility without simulating a 100% single-position portfolio.

    Concentration and liquidity sizing are handled later by the allocator itself. This
    avoids rejecting every candidate in an empty portfolio merely because buying one
    unit temporarily represents 100% of that portfolio.
    """
    decision = str(deep_get(bond, "decision.status") or "").strip()
    decision_norm = decision.lower().replace("ё", "е")
    score = _score(bond)
    rating_known = deep_get(bond, "credit.rating") not in (None, "") or deep_get(bond, "credit.score") not in (None, "")
    liquidity_known = deep_get(bond, "liquidity.max_purchase_rub") not in (None, "")

    if "не покупать" in decision_norm:
        return False, "НЕ ПОКУПАТЬ", "финальный модуль пометил выпуск как «Не покупать»"
    if decision in ("", "Недостаточно данных") or score is None or not rating_known or not liquidity_known:
        return False, "ОЖИДАЕТ ДАННЫХ", "не хватает финального решения, рейтинга/кредитного балла или ликвидности"

    risk = risk_level(bond)
    if risk == "high" or score < 60:
        return False, "НЕ ПОКУПАТЬ", "высокий риск или недостаточный финальный скоринг"

    return True, "ДОКУПИТЬ" if held else "КУПИТЬ", ""


def _weight(bond: dict[str, Any], issuer_share_before: float) -> float:
    score = _score(bond)
    if score is None:
        return 0.0
    risk = risk_level(bond)
    risk_factor = {"low": 1.0, "medium": 0.72, "high": 0.0, None: 0.55}.get(risk, 0.55)
    ytm = safe_float(deep_get(bond, "market.yield"))
    yield_factor = 1.0
    if ytm is not None:
        yield_factor = max(0.85, min(1.15, 1.0 + (ytm - 18.0) / 100.0))
    concentration_factor = max(0.15, 1.0 - issuer_share_before / 25.0)
    return max(0.0, score - 45.0) * risk_factor * yield_factor * concentration_factor


def allocate_budget(
    portfolio: dict[str, Any],
    bonds_by_secid: dict[str, dict[str, Any]],
    candidate_secids: list[str],
    budget: float,
    max_position_percent: float = 20.0,
    max_issuer_percent: float = 25.0,
) -> dict[str, Any]:
    """Allocate new cash across eligible bonds in whole units.

    This is a planning calculation only. It never changes the saved portfolio.
    """
    if budget <= 0:
        raise ValueError("Сумма инвестирования должна быть больше нуля")

    base_rows = portfolio_rows(portfolio, bonds_by_secid)
    base_total = sum(row["amount"] for row in base_rows)
    held_secids = _position_secids(portfolio)
    base_by_secid: dict[str, float] = {}
    base_by_issuer: dict[str, float] = {}
    for row in base_rows:
        base_by_secid[row["secid"]] = base_by_secid.get(row["secid"], 0.0) + row["amount"]
        issuer = str(row.get("issuer") or "")
        if issuer:
            base_by_issuer[issuer] = base_by_issuer.get(issuer, 0.0) + row["amount"]

    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_after = base_total + budget

    for secid in candidate_secids:
        secid = str(secid).strip()
        if not secid or secid in seen:
            continue
        seen.add(secid)
        bond = bonds_by_secid.get(secid)
        if not bond:
            excluded.append({"secid": secid, "reason": "нет бумаги в текущем master"})
            continue
        unit_cost = _unit_cost(bond)
        if unit_cost is None or unit_cost > budget:
            excluded.append({"secid": secid, "reason": "нет корректной цены или одна бумага дороже бюджета"})
            continue

        allowed, action, eligibility_reason = _eligibility(bond, secid in held_secids)
        if not allowed:
            excluded.append({"secid": secid, "name": bond.get("name") or secid, "reason": eligibility_reason or action})
            continue

        issuer = infer_issuer(bond)
        issuer_before = base_by_issuer.get(issuer, 0.0) if issuer else 0.0
        issuer_share_before = issuer_before / base_total * 100.0 if base_total > 0 else 0.0
        weight = _weight(bond, issuer_share_before)
        if weight <= 0:
            excluded.append({"secid": secid, "name": bond.get("name") or secid, "reason": "недостаточный риск/скоринг для распределения"})
            continue

        max_purchase = safe_float(deep_get(bond, "liquidity.max_purchase_rub"))
        eligible.append({
            "secid": secid,
            "bond": bond,
            "name": bond.get("name") or secid,
            "issuer": issuer,
            "unit_cost": unit_cost,
            "score": _score(bond),
            "risk": risk_level(bond),
            "action": action,
            "weight": weight,
            "max_purchase": max_purchase,
            "quantity": 0,
            "amount": 0.0,
        })

    if not eligible:
        return {"budget": budget, "invested": 0.0, "reserve": budget, "lines": [], "excluded": excluded}

    weight_sum = sum(item["weight"] for item in eligible)
    for item in eligible:
        item["target"] = budget * item["weight"] / weight_sum

    def can_add(item: dict[str, Any]) -> bool:
        next_amount = item["amount"] + item["unit_cost"]
        invested_now = sum(other["amount"] for other in eligible)
        if invested_now + item["unit_cost"] > budget + 1e-9:
            return False
        if item["max_purchase"] is not None and next_amount > item["max_purchase"] + 1e-9:
            return False
        position_after = base_by_secid.get(item["secid"], 0.0) + next_amount
        if total_after > 0 and position_after / total_after * 100.0 > max_position_percent + 1e-9:
            return False
        issuer = item["issuer"]
        if issuer:
            issuer_allocated = sum(other["amount"] for other in eligible if other["issuer"] == issuer)
            issuer_after = base_by_issuer.get(issuer, 0.0) + issuer_allocated + item["unit_cost"]
            if total_after > 0 and issuer_after / total_after * 100.0 > max_issuer_percent + 1e-9:
                return False
        return True

    for item in sorted(eligible, key=lambda x: x["weight"], reverse=True):
        target_qty = int(math.floor(item["target"] / item["unit_cost"]))
        while item["quantity"] < target_qty and can_add(item):
            item["quantity"] += 1
            item["amount"] += item["unit_cost"]

    while True:
        invested = sum(item["amount"] for item in eligible)
        reserve = budget - invested
        options = [item for item in eligible if item["unit_cost"] <= reserve + 1e-9 and can_add(item)]
        if not options:
            break
        item = max(
            options,
            key=lambda x: ((x["target"] - x["amount"]) / max(x["target"], 1.0), x["weight"]),
        )
        item["quantity"] += 1
        item["amount"] += item["unit_cost"]

    invested = sum(item["amount"] for item in eligible)
    lines: list[dict[str, Any]] = []
    for item in eligible:
        if item["quantity"] <= 0:
            excluded.append({"secid": item["secid"], "name": item["name"], "reason": "не вошла в бюджет после округления/лимитов"})
            continue
        share = item["amount"] / budget * 100.0
        reason_parts = [f"скоринг {item['score']:.0f}" if item["score"] is not None else "скоринг неизвестен"]
        if item["risk"]:
            reason_parts.append(f"риск {item['risk']}")
        if item["issuer"] and base_by_issuer.get(item["issuer"], 0.0) > 0:
            reason_parts.append("учтена существующая доля эмитента")
        lines.append({
            "secid": item["secid"],
            "name": item["name"],
            "issuer": item["issuer"],
            "quantity": item["quantity"],
            "unit_cost": round(item["unit_cost"], 2),
            "amount": round(item["amount"], 2),
            "share_percent": round(share, 2),
            "score": item["score"],
            "risk": item["risk"],
            "action": item["action"],
            "reason": "; ".join(reason_parts),
        })

    lines.sort(key=lambda x: x["amount"], reverse=True)
    return {
        "budget": round(budget, 2),
        "invested": round(invested, 2),
        "reserve": round(max(0.0, budget - invested), 2),
        "lines": lines,
        "excluded": excluded,
    }
