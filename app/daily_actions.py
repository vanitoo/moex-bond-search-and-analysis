from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_recommendation import recommend_candidate
from portfolio_store import load_portfolio


ACTION_ORDER = {
    "ПРОДАТЬ": 0,
    "СОКРАТИТЬ НА 50%": 1,
    "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ": 2,
    "ДОКУПИТЬ": 3,
    "ДЕРЖАТЬ": 4,
    "КУПИТЬ": 5,
    "ЗАМЕНИТЬ": 6,
    "НЕ ПОКУПАТЬ": 7,
    "ОЖИДАЕТ ДАННЫХ": 8,
}


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip()) or "portfolio"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _latest_monitor_files(history_dir: Path, portfolio_name: str) -> list[Path]:
    pattern = f"{_safe_name(portfolio_name)}_*.json"
    return sorted(history_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)


def _position_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in payload.get("positions", []):
        secid = str(row.get("Код ценной бумаги") or "").strip()
        if secid:
            result[secid] = row
    return result


def _monitor_actions(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_rows = _position_map(current)
    previous_rows = _position_map(previous or {})
    actions: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for secid, row in current_rows.items():
        action = str(row.get("Рекомендация мониторинга") or "ДЕРЖАТЬ")
        actions.append({
            "action": action,
            "secid": secid,
            "name": row.get("Название") or secid,
            "reason": row.get("Причины рекомендации") or "—",
            "score": row.get("Финальный балл"),
            "rating": row.get("Рейтинг") or "",
            "rating_action": row.get("Последнее рейтинговое действие") or "",
            "rating_forecast": row.get("Прогноз рейтинга") or "",
            "ofz_spread_bp": row.get("Спред к ОФЗ, б.п."),
            "signal_first_seen": row.get("Сигнал впервые") or "",
            "signal_days": row.get("Сигнал дней") or 0,
            "signal_trend": row.get("Динамика сигнала") or "",
        })
        old = previous_rows.get(secid)
        if old:
            old_action = str(old.get("Рекомендация мониторинга") or "")
            old_trend = str(old.get("Динамика сигнала") or "")
            new_trend = str(row.get("Динамика сигнала") or "")
            if old_action and (old_action != action or old_trend != new_trend and new_trend in {"УСИЛИЛСЯ", "ОСЛАБ", "ИСЧЕЗ", "ПОЯВИЛСЯ"}):
                changes.append({
                    "secid": secid,
                    "name": row.get("Название") or secid,
                    "from": old_action,
                    "to": action,
                    "reason": row.get("Причины рекомендации") or "—",
                    "signal_trend": new_trend,
                    "signal_days": row.get("Сигнал дней") or 0,
                })
    return actions, changes


def _candidate_actions(run_dir: Path, portfolio: dict[str, Any], amount: float) -> list[dict[str, Any]]:
    master_path = run_dir / "decisions" / "bonds_master.json"
    if not master_path.exists():
        return []
    master = _read_json(master_path)
    bonds = master.get("bonds", [])
    by_secid = {str(item.get("secid")): item for item in bonds if item.get("secid")}
    results: list[dict[str, Any]] = []
    for bond in bonds:
        rec = recommend_candidate(portfolio, bond, amount, by_secid)
        if rec["action"] not in {"КУПИТЬ", "ДОКУПИТЬ", "ЗАМЕНИТЬ"}:
            continue
        results.append({
            "action": rec["action"],
            "secid": rec["secid"],
            "name": rec["name"],
            "reason": "; ".join(rec.get("positives") or []) or "Положительное решение модели",
            "score": rec.get("score"),
            "confidence": rec.get("confidence"),
            "amount": rec.get("amount"),
            "replacement": (rec.get("replacement") or {}).get("name"),
        })
    results.sort(key=lambda x: (ACTION_ORDER.get(x["action"], 99), -(x.get("score") or -999)))
    return results


def _reconcile_actions(monitor: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never recommend adding to a held bond while monitor says reduce/check/sell.

    A held position with a clean DЕРЖАТЬ signal may be upgraded to ДОКУПИТЬ when
    the portfolio recommendation engine independently supports adding it.
    """
    by_secid = {str(item.get("secid")): dict(item) for item in monitor}
    extras: list[dict[str, Any]] = []
    for candidate in candidates:
        secid = str(candidate.get("secid") or "")
        current = by_secid.get(secid)
        if current is None:
            extras.append(candidate)
            continue
        if candidate.get("action") != "ДОКУПИТЬ":
            continue
        if current.get("action") == "ДЕРЖАТЬ":
            merged = dict(current)
            merged["action"] = "ДОКУПИТЬ"
            positive_reason = str(candidate.get("reason") or "").strip()
            monitor_reason = str(current.get("reason") or "").strip()
            merged["reason"] = "; ".join(x for x in [positive_reason, monitor_reason] if x and x != "—") or "Положительное решение модели"
            merged["amount"] = candidate.get("amount")
            merged["confidence"] = candidate.get("confidence")
            by_secid[secid] = merged
    return list(by_secid.values()) + extras


def build_daily_actions(
    portfolio_name: str,
    run_dir: Path,
    portfolio_dir: Path,
    history_dir: Path,
    amount: float = 50_000.0,
) -> dict[str, Any]:
    files = _latest_monitor_files(history_dir, portfolio_name)
    if not files:
        raise FileNotFoundError(f"Нет снимка мониторинга для портфеля {portfolio_name}")
    current = _read_json(files[0])
    previous = _read_json(files[1]) if len(files) > 1 else None
    monitor, changes = _monitor_actions(current, previous)
    portfolio = load_portfolio(portfolio_dir, portfolio_name)
    candidates = _candidate_actions(run_dir, portfolio, amount)

    actions = _reconcile_actions(monitor, candidates)
    actions.sort(key=lambda x: (ACTION_ORDER.get(x["action"], 99), -(x.get("score") or -999)))
    counts: dict[str, int] = {}
    for item in actions:
        counts[item["action"]] = counts.get(item["action"], 0) + 1

    return {
        "portfolio": portfolio_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "monitor_snapshot": str(files[0]),
        "previous_snapshot": str(files[1]) if len(files) > 1 else None,
        "counts": counts,
        "actions": actions,
        "changes": changes,
    }


def write_daily_actions(payload: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(str(payload.get("portfolio") or "portfolio"))
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    timestamped = report_dir / f"daily_actions_{name}_{stamp}.json"
    latest = report_dir / f"daily_actions_{name}_latest.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    timestamped.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    return timestamped, latest


def main() -> None:
    parser = argparse.ArgumentParser(description="Сводка действий по портфелю на сегодня")
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--portfolio-dir", default="data/virtual_portfolios")
    parser.add_argument("--history-dir", default="data/portfolio_monitor_history")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--amount", type=float, default=50_000.0)
    args = parser.parse_args()

    payload = build_daily_actions(
        args.name,
        Path(args.run_dir),
        Path(args.portfolio_dir),
        Path(args.history_dir),
        args.amount,
    )
    timestamped, latest = write_daily_actions(payload, Path(args.report_dir))
    for item in payload["actions"]:
        persistence = item.get("signal_trend") or ""
        days = item.get("signal_days") or 0
        suffix = f" [{persistence}; {days} дн.]" if persistence and persistence != "НЕТ СИГНАЛА" else ""
        print(f"{item['action']}: {item['secid']}{suffix} — {item['reason']}")
    if payload["changes"]:
        print("\nИзменения с прошлого снимка:")
        for item in payload["changes"]:
            print(f"{item['secid']}: {item['from']} → {item['to']} ({item.get('signal_trend') or 'без изменения тренда'})")
    print(f"JSON: {timestamped}")
    print(f"LATEST: {latest}")


if __name__ == "__main__":
    main()
