from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.core.credit_workflow import (
    FINANCIAL_TEMPLATE_COLUMNS,
    RATING_TEMPLATE_COLUMNS,
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
    with pytest.raises(ValueError, match="отсутствуют колонки"):
        load_deep(path)
