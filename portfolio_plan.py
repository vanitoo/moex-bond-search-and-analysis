from __future__ import annotations

from datetime import date
from typing import Any

from portfolio_store import upsert_position


def recalculate_allocation_plan(
    lines: list[dict[str, Any]],
    quantities: dict[str, int],
    budget: float,
) -> dict[str, Any]:
    """Recalculate an allocation plan after manual quantity edits."""
    recalculated: list[dict[str, Any]] = []
    invested = 0.0

    for source in lines:
        secid = str(source.get("secid") or "").strip()
        if not secid:
            continue
        quantity = max(0, int(quantities.get(secid, source.get("quantity") or 0)))
        unit_cost = float(source.get("unit_cost") or 0)
        if quantity <= 0 or unit_cost <= 0:
            continue
        line = dict(source)
        amount = round(quantity * unit_cost, 2)
        line["quantity"] = quantity
        line["amount"] = amount
        invested += amount
        recalculated.append(line)

    invested = round(invested, 2)
    budget = float(budget)
    for line in recalculated:
        line["share_percent"] = round((float(line["amount"]) / budget * 100.0), 2) if budget > 0 else 0.0

    return {
        "budget": round(budget, 2),
        "invested": invested,
        "reserve": round(budget - invested, 2),
        "over_budget": invested > budget + 1e-9,
        "lines": recalculated,
    }


def apply_allocation_plan(
    portfolio: dict[str, Any],
    lines: list[dict[str, Any]],
    bonds_by_secid: dict[str, dict[str, Any]],
    purchase_date: str | None = None,
) -> dict[str, Any]:
    """Add planned purchases to a virtual portfolio, merging with existing lots by SECID."""
    result = dict(portfolio)
    current = {
        str(item.get("secid") or "").strip(): dict(item)
        for item in result.get("positions", [])
        if isinstance(item, dict) and str(item.get("secid") or "").strip()
    }
    when = purchase_date or date.today().isoformat()

    for line in lines:
        secid = str(line.get("secid") or "").strip()
        buy_qty = int(line.get("quantity") or 0)
        buy_amount = float(line.get("amount") or 0)
        if not secid or buy_qty <= 0 or buy_amount <= 0:
            continue

        old = current.get(secid, {})
        old_qty = int(old.get("quantity") or 0)
        old_invested = float(old.get("invested") or 0)
        bond = bonds_by_secid.get(secid, {})

        position = dict(old)
        position.update({
            "secid": secid,
            "name": line.get("name") or old.get("name") or bond.get("name") or secid,
            "issuer": line.get("issuer") or old.get("issuer") or bond.get("issuer") or "",
            "quantity": old_qty + buy_qty,
            "invested": round(old_invested + buy_amount, 2),
            "purchase_date": when,
        })
        result = upsert_position(result, position)
        current[secid] = position

    return result
