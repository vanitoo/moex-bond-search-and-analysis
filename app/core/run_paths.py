from __future__ import annotations

from pathlib import Path
from typing import Iterable


RUN_GLOB = "bond_????_??_??"


def analysis_roots(project_root: Path) -> tuple[Path, Path]:
    """New run location first, legacy root location second."""

    return project_root / "runs", project_root


def iter_analysis_dirs(project_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in analysis_roots(project_root):
        if not root.exists():
            continue
        for path in root.glob(RUN_GLOB):
            if not path.is_dir():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def latest_pipeline_run(project_root: Path) -> Path | None:
    """Latest run that has a market-search workbook and can resume the full pipeline."""

    candidates = [
        path
        for path in iter_analysis_dirs(project_root)
        if any(path.glob("bond_search_*.xlsx"))
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def latest_analysis_run(project_root: Path) -> Path | None:
    """Latest analysis for portfolio monitoring.

    Prefer completed/partially completed runs with a decisions directory; fall
    back to any date-named analysis directory for backward compatibility.
    """

    all_runs = list(iter_analysis_dirs(project_root))
    preferred = [path for path in all_runs if (path / "decisions").exists()]
    candidates = preferred or all_runs
    return max(candidates, key=lambda path: path.name) if candidates else None


def new_run_dir(project_root: Path, stamp: str) -> Path:
    return project_root / "runs" / f"bond_{stamp}"
