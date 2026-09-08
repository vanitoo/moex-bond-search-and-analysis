from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


def safe_name(value: str) -> str:
    text = re.sub(r"[^a-zA-Zа-яА-Я0-9_.-]+", "_", str(value or "").strip()).strip("_.")
    if not text:
        raise ValueError("Укажите название портфеля")
    return text


def portfolio_path(portfolio_dir: Path, name: str) -> Path:
    return portfolio_dir / f"{safe_name(name)}.json"


def list_portfolios(portfolio_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not portfolio_dir.exists():
        return result
    for path in sorted(portfolio_dir.glob("*.json"), key=lambda p: p.stem.lower()):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
            result[path.stem] = payload
    return result


def load_portfolio(portfolio_dir: Path, name: str) -> dict[str, Any]:
    path = portfolio_path(portfolio_dir, name)
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Некорректный формат портфеля")
    payload.setdefault("name", path.stem)
    payload.setdefault("positions", [])
    return payload


def save_portfolio(portfolio_dir: Path, portfolio: dict[str, Any]) -> Path:
    name = str(portfolio.get("name") or "").strip()
    if not name:
        raise ValueError("Укажите название портфеля")
    portfolio_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(portfolio)
    payload["name"] = name
    payload.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    payload.setdefault("positions", [])
    path = portfolio_path(portfolio_dir, name)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def create_portfolio(portfolio_dir: Path, name: str) -> Path:
    path = portfolio_path(portfolio_dir, name)
    if path.exists():
        raise FileExistsError(f"Портфель уже существует: {path.stem}")
    now = datetime.now().isoformat(timespec="seconds")
    return save_portfolio(portfolio_dir, {"name": name.strip(), "created_at": now, "positions": []})


def delete_portfolio(portfolio_dir: Path, name: str) -> None:
    path = portfolio_path(portfolio_dir, name)
    if path.exists():
        path.unlink()


def _position_secid(position: dict[str, Any]) -> str:
    return str(position.get("secid") or position.get("SECID") or position.get("Код ценной бумаги") or "").strip()


def upsert_position(portfolio: dict[str, Any], position: dict[str, Any]) -> dict[str, Any]:
    secid = _position_secid(position)
    if not secid:
        raise ValueError("Не указан SECID")
    quantity = int(position.get("quantity") or 0)
    if quantity <= 0:
        raise ValueError("Количество должно быть больше нуля")
    invested = float(position.get("invested") or 0)
    if invested <= 0:
        raise ValueError("Сумма вложений должна быть больше нуля")

    normalized = dict(position)
    normalized["secid"] = secid
    normalized["quantity"] = quantity
    normalized["invested"] = round(invested, 2)
    purchase_date = normalized.get("purchase_date")
    if isinstance(purchase_date, (date, datetime)):
        normalized["purchase_date"] = purchase_date.isoformat()
    normalized["updated_at"] = datetime.now().isoformat(timespec="seconds")

    result = dict(portfolio)
    positions = [dict(item) for item in result.get("positions", []) if isinstance(item, dict)]
    for index, item in enumerate(positions):
        if _position_secid(item) == secid:
            created_at = item.get("created_at")
            if created_at:
                normalized.setdefault("created_at", created_at)
            positions[index] = normalized
            break
    else:
        normalized.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        positions.append(normalized)
    result["positions"] = positions
    return result


def remove_position(portfolio: dict[str, Any], secid: str) -> dict[str, Any]:
    result = dict(portfolio)
    result["positions"] = [
        dict(item) for item in result.get("positions", [])
        if isinstance(item, dict) and _position_secid(item) != secid
    ]
    return result
