from pathlib import Path

import pandas as pd

from app.core.configuration import is_enabled, load_config
from app.core.pipeline_architecture import _status_for_row, collect_stage
from app.core.run_store import RunStore


def test_balanced_config_enables_modules():
    config = load_config(Path(__file__).resolve().parents[1] / "configs" / "balanced.json")
    assert is_enabled(config, "news") is True
    assert config["strategy"] == "balanced"


def test_news_without_files_is_no_data():
    row = pd.Series({"Новостных файлов": 0, "Критический новостной стоп": "НЕТ"})
    status, passed, hard_stop, _, code, _ = _status_for_row("news", row)
    assert status == "NO_DATA"
    assert passed is None
    assert hard_stop is False
    assert code == "NEWS_NOT_FOUND"


def test_critical_news_is_hard_stop():
    row = pd.Series({
        "Новостных файлов": 2,
        "Критический новостной стоп": "ДА",
        "Негативные события": "Дефолт/просрочка",
    })
    status, passed, hard_stop, _, code, _ = _status_for_row("news", row)
    assert status == "FAIL"
    assert passed is False
    assert hard_stop is True
    assert code == "CRITICAL_NEWS"


def test_missing_orderbook_is_warning_not_high_liquidity():
    row = pd.Series({
        "Максимум к покупке, руб.": 100_000,
        "Объём предложения в стакане, руб.": 0,
    })
    status, passed, _, score_delta, code, _ = _status_for_row("liquidity", row)
    assert status == "WARNING"
    assert passed is True
    assert score_delta < 0
    assert code == "ORDERBOOK_UNKNOWN"


def test_default_config_path_resolves_from_project_root():
    config = load_config(None)
    assert config["strategy"] == "balanced"
    assert "modules" in config


def test_collect_stage_prefers_sqlite_without_reading_excel(tmp_path: Path, monkeypatch):
    from app.core.stage_registry import ModuleSpec
    store = RunStore(tmp_path / "bondlab.db")
    run_id = "run-1"
    store.ensure_run(run_id, tmp_path)
    store.write_frame(run_id, "analysis", pd.DataFrame([
        {"Код ценной бумаги": "RU000A10TEST", "Оценка, 0-100": 90}
    ]))
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Excel must not be read")))
    collect_stage(
        tmp_path,
        ModuleSpec("analysis", "5_bonds_analysis.py", "bond_analysis_*.xlsx", 0),
        {"modules": {"analysis": {}}},
        store=store,
        run_id=run_id,
    )
    assert (tmp_path / "decisions" / "module_results.jsonl").exists()
