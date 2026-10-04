from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.core.credit_workflow import (
    FINANCIAL_TEMPLATE_COLUMNS,
    RATING_TEMPLATE_COLUMNS,
    REQUIRED_DEEP_COLUMNS,
    CreditWorkflowRequest,
    create_templates,
    load_deep,
    load_optional_table,
)


def test_create_templates_preserves_historical_excel_schema(tmp_path: Path):
    ratings, financials = create_templates(tmp_path)
    assert list(pd.read_excel(ratings).columns) == RATING_TEMPLATE_COLUMNS
    assert list(pd.read_excel(financials).columns) == FINANCIAL_TEMPLATE_COLUMNS


def test_load_optional_table_prefers_csv_and_fills_missing_columns(tmp_path: Path):
    path = tmp_path / "issuer_ratings.xlsx"
    pd.DataFrame([{"ИНН": "123"}]).to_csv(path.with_suffix(".csv"), index=False)
    result = load_optional_table(path, ["ИНН", "Рейтинг"])
    assert result.loc[0, "ИНН"] == 123
    assert "Рейтинг" in result.columns


def test_load_deep_validates_stage_contract(tmp_path: Path):
    path = tmp_path / "deep.xlsx"
    pd.DataFrame([{"Код ценной бумаги": "SEC"}]).to_excel(path, sheet_name="Глубокий анализ", index=False)
    with pytest.raises(ValueError, match="отсутствуют.*колонки"):
        load_deep(path)


def test_credit_workflow_request_accepts_in_memory_stage_input():
    from app.core.credit_sources import BankRefreshOptions, FinancialRefreshOptions
    frame = pd.DataFrame(columns=sorted(REQUIRED_DEEP_COLUMNS))
    request = CreditWorkflowRequest(
        source=Path("sqlite-source"),
        data_dir=Path("data"),
        fetch_ratings=False,
        fetch_financials=False,
        fetch_bank_metrics=False,
        financial_options=FinancialRefreshOptions(cache_days=1, workers=1, delay_seconds=0, retries=1),
        bank_options=BankRefreshOptions(cache_days=1, delay_seconds=0),
        input_frame=frame,
        source_label="sqlite:run:deep_analysis",
    )
    assert request.input_frame is frame
    assert request.source_label.startswith("sqlite:")
