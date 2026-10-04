from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    roots = [str(ROOT), str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        roots.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(roots)
    return env


def _help_from_external_cwd(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=tmp_path,
        env=_runtime_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_decision_entrypoint_imports_src_package(tmp_path: Path):
    result = _help_from_external_cwd("app/stages/8_bonds_decision.py", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--config" in result.stdout


def test_portfolio_monitor_entrypoint_imports_src_package(tmp_path: Path):
    result = _help_from_external_cwd("app/portfolio/portfolio_monitor.py", tmp_path)
    assert result.returncode == 0, result.stderr


def test_unified_bondlab_entrypoint_works_from_external_cwd(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "bondlab.py"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "pipeline" in result.stdout
    assert "monitor" in result.stdout


def test_credit_entrypoint_error_path_reports_original_error(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "app/stages/7_bonds_credit_analysis.py"),
            "--input",
            str(tmp_path / "missing.xlsx"),
            "--no-fetch-ratings",
            "--no-fetch-financials",
            "--no-fetch-bank-metrics",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "Ошибка:" in result.stderr
    assert "NameError" not in result.stderr
