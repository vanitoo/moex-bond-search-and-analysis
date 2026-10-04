import json
import os
import time
from pathlib import Path

from app.cli.portfolio import _fresh_analysis_run


def _complete_run(root: Path, name: str, age_hours: float) -> Path:
    run = root / "runs" / name
    decisions = run / "decisions"
    decisions.mkdir(parents=True)
    master = decisions / "bonds_master.json"
    shortlist = decisions / "portfolio_shortlist.json"
    master.write_text(json.dumps({"bonds": []}), encoding="utf-8")
    shortlist.write_text(json.dumps({"shortlist": []}), encoding="utf-8")
    stamp = time.time() - age_hours * 3600
    os.utime(master, (stamp, stamp))
    os.utime(shortlist, (stamp, stamp))
    return run


def test_fresh_analysis_reuses_recent_completed_run(tmp_path: Path):
    recent = _complete_run(tmp_path, "bond_2026_10_05", 1)
    _complete_run(tmp_path, "bond_2026_10_04", 20)
    assert _fresh_analysis_run(12, tmp_path) == recent


def test_fresh_analysis_rejects_stale_or_incomplete_runs(tmp_path: Path):
    _complete_run(tmp_path, "bond_2026_10_04", 20)
    incomplete = tmp_path / "runs" / "bond_2026_10_05"
    incomplete.mkdir(parents=True)
    assert _fresh_analysis_run(12, tmp_path) is None
