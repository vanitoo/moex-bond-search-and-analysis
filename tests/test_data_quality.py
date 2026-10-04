import json
from pathlib import Path

import pandas as pd

from app.core.data_quality import build_quality_report, eligible_secids
from app.core.run_store import RunStore


def _event(secid: str, module: str, status: str) -> dict:
    return {"timestamp": "2026-10-05T12:00:00", "secid": secid, "module": module, "status": status, "reason": status}


def test_quality_gate_blocks_missing_required_source(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_05"
    decisions = run_dir / "decisions"
    decisions.mkdir(parents=True)
    run_id = run_dir.name
    store = RunStore(tmp_path / "bondlab.db")
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "market_search", pd.DataFrame([
        {"Код ценной бумаги": "RU000A10AAAA"},
        {"Код ценной бумаги": "RU000A10BBBB"},
    ]))
    required = ["market_search", "cashflow", "liquidity", "ofz_spread", "analysis", "deep_analysis", "credit", "decision"]
    events = []
    for secid in ("RU000A10AAAA", "RU000A10BBBB"):
        for module in required:
            if secid == "RU000A10BBBB" and module == "credit":
                continue
            events.append(_event(secid, module, "PASS"))
        events.append(_event(secid, "news", "PASS"))
    (decisions / "module_results.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in events) + "\n", encoding="utf-8"
    )
    report = build_quality_report(run_dir, store, run_id)
    statuses = {x["secid"]: x["status"] for x in report["securities"]}
    assert statuses["RU000A10AAAA"] == "COMPLETE"
    assert statuses["RU000A10BBBB"] == "INCOMPLETE"
    assert eligible_secids(report, allow_degraded=False) == {"RU000A10AAAA"}
    rows = store.read_quality_rows(run_id)
    assert any(x["secid"] == "RU000A10BBBB" and x["source"] == "credit" and x["status"] == "MISSING" for x in rows)


def test_optional_news_problem_is_degraded_not_incomplete(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_05"
    decisions = run_dir / "decisions"
    decisions.mkdir(parents=True)
    run_id = run_dir.name
    store = RunStore(tmp_path / "bondlab.db")
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "market_search", pd.DataFrame([{"Код ценной бумаги": "RU000A10AAAA"}]))
    events = [_event("RU000A10AAAA", x, "PASS") for x in ["market_search", "cashflow", "liquidity", "ofz_spread", "credit", "decision"]]
    events.append(_event("RU000A10AAAA", "news", "NO_DATA"))
    (decisions / "module_results.jsonl").write_text(
        "\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8"
    )
    report = build_quality_report(run_dir, store, run_id)
    assert report["securities"][0]["status"] == "DEGRADED"
    assert eligible_secids(report, allow_degraded=False) == set()
    assert eligible_secids(report, allow_degraded=True) == {"RU000A10AAAA"}



def test_business_rejection_is_not_data_failure(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_05"
    decisions = run_dir / "decisions"
    decisions.mkdir(parents=True)
    run_id = run_dir.name
    store = RunStore(tmp_path / "bondlab.db")
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "market_search", pd.DataFrame([{"Код ценной бумаги": "RU000A10AAAA"}]))
    modules = ["market_search", "cashflow", "liquidity", "ofz_spread", "analysis", "deep_analysis", "credit"]
    events = [_event("RU000A10AAAA", x, "PASS") for x in modules]
    rejected = _event("RU000A10AAAA", "decision", "FAIL")
    rejected["reason_code"] = "FINAL_REJECT"
    events.append(rejected)
    events.append(_event("RU000A10AAAA", "news", "PASS"))
    (decisions / "module_results.jsonl").write_text(
        "\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8"
    )
    report = build_quality_report(run_dir, store, run_id)
    assert report["securities"][0]["status"] == "COMPLETE"


def test_retryable_missing_credit_repairs_from_stage_9(tmp_path: Path):
    from app.core.data_quality import repair_start_stage, repairable_sources

    run_dir = tmp_path / "bond_2026_10_05"
    decisions = run_dir / "decisions"
    decisions.mkdir(parents=True)
    run_id = run_dir.name
    store = RunStore(tmp_path / "bondlab.db")
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "market_search", pd.DataFrame([{"Код ценной бумаги": "RU000A10AAAA"}]))
    modules = ["market_search", "cashflow", "liquidity", "ofz_spread", "analysis", "deep_analysis", "decision"]
    events = [_event("RU000A10AAAA", x, "PASS") for x in modules]
    events.append(_event("RU000A10AAAA", "news", "PASS"))
    (decisions / "module_results.jsonl").write_text(
        "\n".join(json.dumps(x) for x in events) + "\n", encoding="utf-8"
    )
    report = build_quality_report(run_dir, store, run_id)
    assert repairable_sources(report) == ["credit"]
    assert repair_start_stage(report) == 9
