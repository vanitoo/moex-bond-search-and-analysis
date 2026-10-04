import pandas as pd
import pytest

from app.core.stage_contract import FrameContract


def test_frame_contract_reports_missing_columns_with_stage_name():
    contract = FrameContract.from_columns("stage X", ["Код ценной бумаги", "Баллы"])
    with pytest.raises(ValueError, match="stage X"):
        contract.validate(pd.DataFrame([{"Код ценной бумаги": "SEC"}]))


def test_frame_contract_clean_drops_rows_without_secid_without_mutating_input():
    contract = FrameContract.from_columns("stage X", ["Код ценной бумаги", "Баллы"])
    source = pd.DataFrame([
        {"Код ценной бумаги": "SEC", "Баллы": 90},
        {"Код ценной бумаги": None, "Баллы": 50},
    ])
    result = contract.clean(source)
    assert len(result) == 1
    assert len(source) == 2
