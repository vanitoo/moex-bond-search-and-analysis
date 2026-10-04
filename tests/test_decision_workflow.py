from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.core.decision_workflow import choose_base, load_optional


def test_load_optional_returns_empty_secid_contract_when_missing(tmp_path: Path):
    result = load_optional(tmp_path, "missing_*.xlsx", "Sheet")
    assert list(result.columns) == ["Код ценной бумаги"]
    assert result.empty


def test_choose_base_prefers_credit_when_enabled(tmp_path: Path):
    path = tmp_path / "bond_credit_analysis_2026-10-04.xlsx"
    pd.DataFrame([{"Код ценной бумаги": "SEC-1"}]).to_excel(path, sheet_name="Кредитный анализ", index=False)
    frame, source = choose_base(tmp_path, {"modules": {"credit": {"enabled": True}}}, None)
    assert frame.iloc[0]["Код ценной бумаги"] == "SEC-1"
    assert source == path.name


def test_choose_base_fails_explicitly_without_outputs(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Нет ни одного"):
        choose_base(tmp_path, {}, None)
