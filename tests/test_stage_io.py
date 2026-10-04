from pathlib import Path

import pandas as pd

from app.core.run_store import RunStore, default_store_path, run_id_for
from app.core.stage_io import load_stage_frame, publish_stage_frame


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


def test_publish_stage_frame_writes_only_with_pipeline_context(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "bondlab.db"
    store = RunStore(store_path)
    run_dir = tmp_path / "bond_2026_10_04"
    run_id = run_id_for(run_dir)
    store.ensure_run(run_id, run_dir)
    monkeypatch.setenv("BONDLAB_RUN_ID", run_id)
    monkeypatch.setenv("BONDLAB_RUN_STORE", str(store_path))
    frame = pd.DataFrame([{"Код ценной бумаги": "RU000A10TEST", "Баллы": 91}])
    assert publish_stage_frame("analysis", frame) is True
    restored = store.read_frame(run_id, "analysis")
    assert restored is not None
    assert restored.iloc[0]["Баллы"] == 91


def test_publish_stage_frame_is_noop_for_standalone_execution(monkeypatch):
    monkeypatch.delenv("BONDLAB_RUN_ID", raising=False)
    monkeypatch.delenv("BONDLAB_RUN_STORE", raising=False)
    assert publish_stage_frame("analysis", pd.DataFrame()) is False
