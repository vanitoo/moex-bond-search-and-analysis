from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.run_store import RunStore

REQUIRED_SOURCES = ("market_search", "cashflow", "liquidity", "ofz_spread", "credit", "decision")
OPTIONAL_SOURCES = ("news",)
GOOD = {"PASS"}
DEGRADED = {"WARNING", "NO_DATA"}
BAD = {"FAIL", "ERROR"}


def _latest_events(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = run_dir / "decisions" / "module_results.jsonl"
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return latest
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        secid = str(event.get("secid") or "").strip().upper()
        module = str(event.get("module") or "").strip()
        if secid and module:
            latest[(secid, module)] = event
    return latest


def build_quality_report(run_dir: Path, store: RunStore, run_id: str) -> dict[str, Any]:
    market = store.read_frame(run_id, "market_search")
    secids: list[str] = []
    if market is not None:
        for column in ("Код ценной бумаги", "SECID", "secid"):
            if column in market.columns:
                secids = sorted({str(x).strip().upper() for x in market[column].dropna() if str(x).strip()})
                break
    events = _latest_events(run_dir)
    rows: list[dict[str, Any]] = []
    securities: list[dict[str, Any]] = []
    now = datetime.now().isoformat(timespec="seconds")

    for secid in secids:
        sources: dict[str, dict[str, Any]] = {}
        for source in (*REQUIRED_SOURCES, *OPTIONAL_SOURCES):
            required = source in REQUIRED_SOURCES
            event = events.get((secid, source))
            if event is None:
                status = "MISSING"
                reason = "Нет результата источника/этапа"
            else:
                status = str(event.get("status") or "UNKNOWN").upper()
                reason = str(event.get("reason") or "")
            rows.append({
                "secid": secid, "source": source, "status": status, "required": required,
                "fetched_at": event.get("timestamp") if event else now,
                "records": 1 if event else 0, "error": reason if status in BAD | {"MISSING"} else None,
                "details": {"reason": reason, "reason_code": event.get("reason_code") if event else "MISSING"},
            })
            sources[source] = {"status": status, "required": required, "reason": reason}

        required_statuses = [sources[x]["status"] for x in REQUIRED_SOURCES]
        optional_statuses = [sources[x]["status"] for x in OPTIONAL_SOURCES]
        if any(x in BAD or x in {"MISSING", "UNKNOWN"} for x in required_statuses):
            overall = "INCOMPLETE"
        elif any(x in DEGRADED for x in required_statuses) or any(x in BAD | DEGRADED | {"MISSING", "UNKNOWN"} for x in optional_statuses):
            overall = "DEGRADED"
        else:
            overall = "COMPLETE"
        complete_required = sum(1 for x in required_statuses if x in GOOD)
        quality_score = round(100.0 * complete_required / len(REQUIRED_SOURCES), 1)
        securities.append({"secid": secid, "status": overall, "quality_score": quality_score, "sources": sources})

    store.write_quality_rows(run_id, rows)
    counts = {status: sum(1 for item in securities if item["status"] == status) for status in ("COMPLETE", "DEGRADED", "INCOMPLETE")}
    pipeline_status = "INCOMPLETE" if counts["INCOMPLETE"] else ("DEGRADED" if counts["DEGRADED"] else "COMPLETE")
    report = {
        "run_id": run_id, "generated_at": now, "status": pipeline_status,
        "counts": counts, "total": len(securities), "required_sources": list(REQUIRED_SOURCES),
        "optional_sources": list(OPTIONAL_SOURCES), "securities": securities,
    }
    target = run_dir / "decisions" / "data_quality.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_quality_report(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "decisions" / "data_quality.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def eligible_secids(report: dict[str, Any], *, allow_degraded: bool = True) -> set[str]:
    allowed = {"COMPLETE", "DEGRADED"} if allow_degraded else {"COMPLETE"}
    return {str(item["secid"]) for item in report.get("securities", []) if item.get("status") in allowed}


def print_quality_summary(report: dict[str, Any]) -> None:
    icon = {"COMPLETE": "🟢", "DEGRADED": "🟡", "INCOMPLETE": "🔴"}.get(report.get("status"), "⚪")
    counts = report.get("counts") or {}
    print("\n════════ DATA QUALITY ════════")
    print(f"Pipeline:   {icon} {report.get('status')}")
    print(f"Проверено:  {report.get('total', 0)}")
    print(f"🟢 Complete:   {counts.get('COMPLETE', 0)}")
    print(f"🟡 Degraded:   {counts.get('DEGRADED', 0)}")
    print(f"🔴 Incomplete: {counts.get('INCOMPLETE', 0)}")
