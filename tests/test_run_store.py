from pathlib import Path

import pandas as pd

from app.core.run_store import RunStore, run_id_for


def test_run_store_roundtrip_preserves_stage_frame(tmp_path: Path):
    store = RunStore(tmp_path / "bondlab.db")
    run_dir = tmp_path / "bond_2026_10_04_001"
    run_id = run_id_for(run_dir)
    store.ensure_run(run_id, run_dir, strategy="balanced")
    source = pd.DataFrame([
        {"Код ценной бумаги": "RU000A10TEST", "Баллы": 90, "Комментарий": "тест"},
        {"Код ценной бумаги": "RU000A10TES2", "Баллы": 80, "Комментарий": None},
    ])
    store.write_frame(run_id, "analysis", source)
    restored = store.read_frame(run_id, "analysis")
    assert restored is not None
    assert restored["Код ценной бумаги"].tolist() == source["Код ценной бумаги"].tolist()
    assert restored["Баллы"].tolist() == [90, 80]
    assert store.modules(run_id) == ("analysis",)


def test_run_store_replaces_same_module_snapshot(tmp_path: Path):
    store = RunStore(tmp_path / "bondlab.db")
    run_dir = tmp_path / "bond_2026_10_04"
    run_id = run_id_for(run_dir)
    store.ensure_run(run_id, run_dir)
    store.write_frame(run_id, "credit", pd.DataFrame([{"Код ценной бумаги": "RU000A10TEST"}]))
    store.write_frame(run_id, "credit", pd.DataFrame([{"Код ценной бумаги": "RU000A10TES2"}]))
    restored = store.read_frame(run_id, "credit")
    assert restored is not None
    assert restored["Код ценной бумаги"].tolist() == ["RU000A10TES2"]
