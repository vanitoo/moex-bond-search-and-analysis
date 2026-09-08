from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _help_from_external_cwd(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_decision_entrypoint_imports_src_package(tmp_path: Path):
    result = _help_from_external_cwd("8_bonds_decision.py", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--config" in result.stdout


def test_portfolio_monitor_entrypoint_imports_src_package(tmp_path: Path):
    result = _help_from_external_cwd("10_portfolio_monitor.py", tmp_path)
    assert result.returncode == 0, result.stderr
