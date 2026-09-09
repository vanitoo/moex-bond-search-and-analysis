from pathlib import Path

from daily_runner import latest_analysis_dir, portfolio_monitor_dir


def test_latest_analysis_dir_prefers_latest_bond_folder(tmp_path: Path):
    older = tmp_path / "bond_2026_08_01"
    newer = tmp_path / "bond_2026_09_01"
    older.mkdir()
    newer.mkdir()
    assert latest_analysis_dir(tmp_path) == newer


def test_portfolio_monitor_dir_is_stable_and_safe(tmp_path: Path):
    path = portfolio_monitor_dir(tmp_path, "Мой портфель 1")
    assert path == tmp_path / "data" / "portfolio_monitor_runs" / "Мой_портфель_1"
