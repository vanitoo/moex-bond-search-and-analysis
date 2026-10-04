from pathlib import Path

import pandas as pd

from moex_bond_search_and_analysis.app import App
from moex_bond_search_and_analysis.schemas import Bond, SearchByCriteriaConditions


def test_v1_search_exposes_dataframe_before_report_export(tmp_path: Path, monkeypatch):
    app = App()
    bond = Bond(
        name="Test bond",
        secid="RU000A10TEST",
        is_qualified_investors="Нет",
        price=99.5,
        volume=10000,
        yield_=18.2,
        duration=12.0,
        coupon_months=[],
    )
    monkeypatch.setattr(app.moex, "search_bonds", lambda conditions: [bond])
    monkeypatch.chdir(tmp_path)
    published = []
    frame = app.search_by_criteria(SearchByCriteriaConditions(), result_callback=published.append)
    assert len(published) == 1
    assert published[0].iloc[0]["Код ценной бумаги"] == "RU000A10TEST"
    assert frame.iloc[0]["Доходность"] == 18.2
