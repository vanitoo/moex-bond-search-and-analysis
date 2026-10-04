from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.core.pipeline_common import latest
from app.core.project_paths import PROJECT_ROOT
from app.core.run_store import RunStore, default_store_path, run_id_for


@dataclass(frozen=True)
class StageFrame:
    frame: pd.DataFrame
    source: str


def load_stage_frame(
    *,
    run_dir: Path,
    module: str,
    pattern: str,
    sheet: str | int = 0,
    explicit: Path | str | None = None,
    required: bool = True,
    project_root: Path = PROJECT_ROOT,
) -> StageFrame:
    """Resolve a stage input: explicit file -> current-run SQLite -> legacy XLSX."""
    if explicit:
        path = Path(explicit)
        return StageFrame(_read_excel(path, sheet), path.name)

    run_id = run_id_for(run_dir)
    stored = RunStore(default_store_path(project_root)).read_frame(run_id, module)
    if stored is not None:
        return StageFrame(stored, f"sqlite:{run_id}:{module}")

    path = latest(run_dir, pattern, required=required)
    if path is None:
        return StageFrame(pd.DataFrame(columns=["Код ценной бумаги"]), "НЕ НАЙДЕН")
    return StageFrame(_read_excel(path, sheet), path.name)


def _read_excel(path: Path, sheet: str | int) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet)
    except ValueError:
        return pd.read_excel(path, sheet_name=0)
