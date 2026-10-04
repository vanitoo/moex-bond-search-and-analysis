from pathlib import Path

import pandas as pd

from app.core.run_store import RunStore, default_store_path, run_id_for
from app.core.stage_io import load_stage_frame


def test_stage_input_prefers_explicit_file_over_sqlite(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_04"; run_dir.mkdir()
    store = RunStore(default_store_path(tmp_path))
    run_id = run_id_for(run_dir)
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "analysis", pd.DataFrame([{"Код ценной бумаги": "DB"}]))
    explicit = tmp_path / "explicit.xlsx"
    pd.DataFrame([{"Код ценной бумаги": "FILE"}]).to_excel(explicit, index=False)
    result = load_stage_frame(run_dir=run_dir, module="analysis", pattern="bond_analysis_*.xlsx",
                              explicit=explicit, project_root=tmp_path)
    assert result.frame.iloc[0]["Код ценной бумаги"] == "FILE"


def test_stage_input_prefers_sqlite_over_legacy_excel(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_04"; run_dir.mkdir()
    store = RunStore(default_store_path(tmp_path))
    run_id = run_id_for(run_dir)
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "analysis", pd.DataFrame([{"Код ценной бумаги": "DB"}]))
    pd.DataFrame([{"Код ценной бумаги": "FILE"}]).to_excel(run_dir / "bond_analysis_old.xlsx", index=False)
    result = load_stage_frame(run_dir=run_dir, module="analysis", pattern="bond_analysis_*.xlsx",
                              project_root=tmp_path)
    assert result.frame.iloc[0]["Код ценной бумаги"] == "DB"
    assert result.source == f"sqlite:{run_id}:analysis"


def test_stage_input_falls_back_to_excel(tmp_path: Path):
    run_dir = tmp_path / "bond_2026_10_04"; run_dir.mkdir()
    path = run_dir / "bond_analysis_old.xlsx"
    pd.DataFrame([{"Код ценной бумаги": "FILE"}]).to_excel(path, index=False)
    result = load_stage_frame(run_dir=run_dir, module="analysis", pattern="bond_analysis_*.xlsx",
                              project_root=tmp_path)
    assert result.frame.iloc[0]["Код ценной бумаги"] == "FILE"
