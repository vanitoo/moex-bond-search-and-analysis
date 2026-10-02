from pathlib import Path

from run_paths import latest_analysis_run, latest_pipeline_run, new_run_dir


def test_new_runs_live_under_runs_directory(tmp_path: Path):
    assert new_run_dir(tmp_path, "2026_10_02") == tmp_path / "runs" / "bond_2026_10_02"


def test_pipeline_run_prefers_only_directories_with_market_search(tmp_path: Path):
    runs = tmp_path / "runs"
    older = runs / "bond_2026_10_01"
    newer = runs / "bond_2026_10_02"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "bond_search_2026-10-01.xlsx").write_bytes(b"x")

    assert latest_pipeline_run(tmp_path) == older


def test_analysis_run_prefers_directory_with_decisions(tmp_path: Path):
    runs = tmp_path / "runs"
    with_decisions = runs / "bond_2026_10_01"
    newer_without = runs / "bond_2026_10_02"
    (with_decisions / "decisions").mkdir(parents=True)
    newer_without.mkdir(parents=True)

    assert latest_analysis_run(tmp_path) == with_decisions
