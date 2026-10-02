from pathlib import Path

from app.cli.daily import latest_analysis_dir, portfolio_monitor_dir


def test_latest_analysis_dir_prefers_latest_bond_folder(tmp_path: Path):
    older = tmp_path / "bond_2026_08_01"
    newer = tmp_path / "bond_2026_09_01"
    older.mkdir()
    newer.mkdir()
    assert latest_analysis_dir(tmp_path) == newer


def test_portfolio_monitor_dir_is_stable_and_safe(tmp_path: Path):
    path = portfolio_monitor_dir(tmp_path, "Мой портфель 1")
    assert path == tmp_path / "data" / "portfolio_monitor_runs" / "Мой_портфель_1"


def test_latest_analysis_dir_reads_new_runs_directory(tmp_path: Path):
    runs = tmp_path / "runs"
    older = runs / "bond_2026_09_01"
    newer = runs / "bond_2026_10_01"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (newer / "decisions").mkdir()
    assert latest_analysis_dir(tmp_path) == newer
