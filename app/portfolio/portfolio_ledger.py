from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.portfolio.portfolio_store import safe_name

TRANSACTION_TYPES = {"DEPOSIT", "BUY", "SELL", "COUPON", "REDEMPTION"}


def ledger_path(ledger_dir: Path, portfolio_name: str) -> Path:
    return ledger_dir / f"{safe_name(portfolio_name)}.jsonl"


def read_ledger(ledger_dir: Path, portfolio_name: str) -> list[dict[str, Any]]:
    path = ledger_path(ledger_dir, portfolio_name)
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            result.append(payload)
    return result


def append_transaction(
    ledger_dir: Path,
    portfolio_name: str,
    transaction_type: str,
    *,
    amount: float,
    secid: str | None = None,
    quantity: int | None = None,
    unit_cost: float | None = None,
    note: str | None = None,
    occurred_at: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    kind = transaction_type.strip().upper()
    if kind not in TRANSACTION_TYPES:
        raise ValueError(f"Неизвестный тип операции: {transaction_type}")
    if amount <= 0:
        raise ValueError("Сумма операции должна быть больше нуля")
    if kind in {"BUY", "SELL", "REDEMPTION"} and not secid:
        raise ValueError(f"Для {kind} требуется SECID")
    if kind in {"BUY", "SELL"} and (quantity is None or quantity <= 0):
        raise ValueError(f"Для {kind} требуется положительное количество")

    payload = {
        "id": uuid4().hex,
        "batch_id": batch_id,
        "portfolio": portfolio_name,
        "type": kind,
        "occurred_at": occurred_at or datetime.now().isoformat(timespec="seconds"),
        "amount": round(float(amount), 2),
        "secid": secid,
        "quantity": int(quantity) if quantity is not None else None,
        "unit_cost": round(float(unit_cost), 2) if unit_cost is not None else None,
        "note": note,
    }
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_path(ledger_dir, portfolio_name)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def cash_balance(transactions: list[dict[str, Any]]) -> float:
    balance = 0.0
    for tx in transactions:
        amount = float(tx.get("amount") or 0)
        kind = str(tx.get("type") or "").upper()
        if kind in {"DEPOSIT", "SELL", "COUPON", "REDEMPTION"}:
            balance += amount
        elif kind == "BUY":
            balance -= amount
    return round(balance, 2)
