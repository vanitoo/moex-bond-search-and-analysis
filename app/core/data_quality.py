from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.run_store import RunStore

REQUIRED_SOURCES = ("market_search", "cashflow", "liquidity", "ofz_spread", "credit", "decision")
OPTIONAL_SOURCES = ("news",)

# These codes describe missing/partial data. Business rejection codes such as
# FINAL_REJECT, NO_PURCHASE_VOLUME or HIGH_OFZ_SPREAD are valid observations,
# not pipeline-health failures.
DEGRADED_CODES = {"INCOMPLETE_CASHFLOW", "ORDERBOOK_UNKNOWN", "SECTOR_DATA_PARTIAL", "NEWS_NOT_FOUND"}
INCOMPLETE_CODES = {"STAGE_PROCESS_ERROR", "OUTPUT_NOT_FOUND", "CREDIT_RATING_MISSING", "CORPORATE_FINANCIALS_MISSING", "FINAL_NO_DATA"}
RETRYABLE_CODES = {"STAGE_PROCESS_ERROR", "OUTPUT_NOT_FOUND", "INCOMPLETE_CASHFLOW", "ORDERBOOK_UNKNOWN"}
REPAIR_STAGE = {
    "market_search": 1,
    "cashflow": 2,
    "news": 3,  # rerun downloader before news analysis
    "liquidity": 5,
    "ofz_spread": 6,
    "credit": 9,
    "decision": 10,
}


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


def _health_for_event(source: str, event: dict[str, Any] | None) -> tuple[str, bool, str, str]:
    if event is None:
        return "MISSING", True, "MISSING", "Нет результата источника/этапа"
    event_status = str(event.get("status") or "UNKNOWN").upper()
    code = str(event.get("reason_code") or "").upper()
    reason = str(event.get("reason") or "")
    if event_status == "ERROR" or code in INCOMPLETE_CODES:
        return "INCOMPLETE", code in RETRYABLE_CODES, code or "ERROR", reason
    if code in DEGRADED_CODES:
        return "DEGRADED", code in RETRYABLE_CODES, code, reason
    if event_status in {"NO_DATA"}:
        # Unknown NO_DATA is data-health degradation, but not blindly retryable.
        return "DEGRADED", False, code or "NO_DATA", reason
    # FAIL/WARNING may be a valid business/risk result. If it is not one of the
    # explicit data-quality codes above, the data itself was successfully loaded.
    return "COMPLETE", False, code or event_status, reason


def repairable_sources(report: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for security in report.get("securities", []):
        for source, details in (security.get("sources") or {}).items():
            if details.get("retryable") and details.get("status") in {"MISSING", "INCOMPLETE", "DEGRADED"}:
                result.add(source)
    return sorted(result, key=lambda source: REPAIR_STAGE.get(source, 999))


def repair_start_stage(report: dict[str, Any]) -> int | None:
    sources = repairable_sources(report)
    if not sources:
        return None
    return min(REPAIR_STAGE[source] for source in sources if source in REPAIR_STAGE)

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
            status, retryable, reason_code, reason = _health_for_event(source, event)
            rows.append({
                "secid": secid, "source": source, "status": status, "required": required,
                "fetched_at": event.get("timestamp") if event else now,
                "records": 1 if event else 0,
                "error": reason if status in {"MISSING", "INCOMPLETE"} else None,
                "details": {"reason": reason, "reason_code": reason_code, "retryable": retryable},
            })
            sources[source] = {
                "status": status, "required": required, "reason": reason,
                "reason_code": reason_code, "retryable": retryable,
            }

        required_statuses = [sources[x]["status"] for x in REQUIRED_SOURCES]
        optional_statuses = [sources[x]["status"] for x in OPTIONAL_SOURCES]
        if any(x in {"MISSING", "INCOMPLETE"} for x in required_statuses):
            overall = "INCOMPLETE"
        elif any(x == "DEGRADED" for x in required_statuses) or any(x in {"MISSING", "INCOMPLETE", "DEGRADED"} for x in optional_statuses):
            overall = "DEGRADED"
        else:
            overall = "COMPLETE"
        complete_required = sum(1 for x in required_statuses if x == "COMPLETE")
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
