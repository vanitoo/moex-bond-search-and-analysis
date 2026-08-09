import json
from pathlib import Path

import pandas as pd

from master_dataset import build_master_dataset


def test_build_master_dataset_merges_modules(tmp_path: Path) -> None:
    run_dir = tmp_path / "bond_2026_08_10"
    run_dir.mkdir()

    with pd.ExcelWriter(run_dir / "bond_search_2026-08-10.xlsx", engine="openpyxl") as writer:
        pd.DataFrame([
            {
                "Код ценной бумаги": "RU000A10TEST",
                "Полное наименование": "Тестовая облигация",
                "Доходность": 19.5,
                "Цена, %": 95.2,
                "Дюрация, месяцев": 11.4,
            }
        ]).to_excel(writer, sheet_name="Результаты поиска", index=False)

    with pd.ExcelWriter(run_dir / "bond_decisions_2026-08-10.xlsx", engine="openpyxl") as writer:
        pd.DataFrame([
            {
                "Код ценной бумаги": "RU000A10TEST",
                "Финальный балл": 84,
                "Финальное решение": "Рассматривать",
                "Допущена в портфель": "ДА",
            }
        ]).to_excel(writer, sheet_name="Решения", index=False)

    target = build_master_dataset(run_dir)
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["bond_count"] == 1
    bond = payload["bonds"][0]
    assert bond["secid"] == "RU000A10TEST"
    assert bond["market"]["yield"] == 19.5
    assert bond["decision"]["score"] == 84.0
    assert bond["decision"]["admitted"] is True
    assert "market_search" in bond["raw"]
    assert "decision" in bond["raw"]


def test_master_dataset_ignores_service_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / "bond_2026_08_10"
    run_dir.mkdir()
    with pd.ExcelWriter(run_dir / "bond_search_2026-08-10.xlsx", engine="openpyxl") as writer:
        pd.DataFrame([
            {"Код ценной бумаги": "nan", "Полное наименование": "служебная строка"},
            {"Код ценной бумаги": "RU000A10TEST", "Полное наименование": "Тест"},
        ]).to_excel(writer, sheet_name="Результаты поиска", index=False)

    payload = json.loads(build_master_dataset(run_dir).read_text(encoding="utf-8"))
    assert [bond["secid"] for bond in payload["bonds"]] == ["RU000A10TEST"]
