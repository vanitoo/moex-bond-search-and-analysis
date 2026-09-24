import pandas as pd

from moex_bond_search_and_analysis.financials import (
    AUTO_COMMENT,
    FINANCIAL_COLUMNS,
    merge_financial_rows,
    parse_fns_bfo,
)


def sample_payload():
    return [
        {
            "period": "2025",
            "organizationInfo": {
                "inn": "1234567890",
                "name": "ООО Тест",
            },
            "typeCorrections": [
                {
                    "type": 12,
                    "correction": {
                        "id": 100,
                        "periodType": 12,
                        "correctionVersion": 1,
                        "balance": {
                            "current1200": 5000,
                            "current1250": 1000,
                            "current1300": 4000,
                            "current1410": 3000,
                            "current1500": 2500,
                            "current1510": 1500,
                        },
                        "financialResult": {
                            "current2110": 12000,
                            "current2330": 300,
                            "current2400": 900,
                        },
                        "fundsMovement": {
                            "current4100": 1100,
                        },
                    },
                }
            ],
        }
    ]


def test_parse_fns_bfo_maps_standard_form_lines():
    row = parse_fns_bfo(
        sample_payload(),
        inn="1234567890",
        source_url="https://example.test/company",
    )
    assert row is not None
    assert row["Эмитент"] == "ООО Тест"
    assert row["Период"] == "2025"
    assert row["Выручка"] == 12000
    assert row["Чистая прибыль"] == 900
    assert row["Операционный денежный поток"] == 1100
    assert row["Денежные средства"] == 1000
    assert row["Общий долг"] == 4500
    assert row["Краткосрочный долг"] == 1500
    assert row["Процентные расходы"] == 300
    assert row["Собственный капитал"] == 4000
    assert row["Оборотные активы"] == 5000
    assert row["Краткосрочные обязательства"] == 2500
    assert row["EBITDA"] is None


def test_merge_preserves_manual_row_over_automatic():
    manual = pd.DataFrame([{
        "Код ценной бумаги": "",
        "Эмитент": "ООО Тест",
        "ИНН": "1234567890",
        "Период": "2025",
        "Валюта": "тыс. руб.",
        "Выручка": 99999,
        "Комментарий": "Проверено вручную",
    }]).reindex(columns=FINANCIAL_COLUMNS)
    automatic = pd.DataFrame([{
        **{column: None for column in FINANCIAL_COLUMNS},
        "Эмитент": "ООО Тест",
        "ИНН": "1234567890",
        "Период": "2025",
        "Выручка": 12000,
        "Комментарий": AUTO_COMMENT,
    }])
    merged = merge_financial_rows(manual, automatic)
    assert len(merged) == 1
    assert merged.iloc[0]["Выручка"] == 99999
    assert merged.iloc[0]["Комментарий"] == "Проверено вручную"
