from datetime import datetime
from io import BytesIO
from unittest.mock import Mock

import pandas as pd

from moex_bond_search_and_analysis.ratings import (
    EXPERT_RA_AUTO_COMMENT,
    RATING_COLUMNS,
    enrich_issuer_identifiers,
    fetch_expert_ra_ratings,
    merge_rating_rows,
    parse_expert_ra_export,
)


def export_bytes() -> bytes:
    raw = pd.DataFrame(
        [
            ["Служебная строка", None, None, None, None, None, None],
            [
                "Эмитент/Объект",
                "ИНН",
                "ISIN",
                "Рейтинг",
                "Дата присвоения/актуализации/изменения рейтинга",
                "Прогноз",
                "Пресс-релиз",
            ],
            [
                'ООО "Тест"',
                "ИНН: 1234567890",
                "RU000A100000",
                "ruA+",
                "28.07.2026",
                "Стабильный",
                "https://raexpert.ru/releases/test",
            ],
        ]
    )
    buffer = BytesIO()
    raw.to_excel(buffer, index=False, header=False)
    return buffer.getvalue()


def test_parse_expert_ra_export():
    result = parse_expert_ra_export(export_bytes())

    assert result.columns.tolist() == RATING_COLUMNS
    assert result.iloc[0]["Код ценной бумаги"] == "RU000A100000"
    assert result.iloc[0]["ИНН"] == "1234567890"
    assert result.iloc[0]["Рейтинг"] == "ruA+"
    assert result.iloc[0]["Агентство"] == "АО «Эксперт РА»"


def test_fetch_expert_ra_ratings_uses_official_export():
    response = Mock()
    response.content = export_bytes()
    response.headers = {
        "Content-Type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    }
    response.raise_for_status.return_value = None
    session = Mock()
    session.post.return_value = response

    result = fetch_expert_ra_ratings(
        session=session, as_of=datetime(2026, 7, 28)
    )

    assert len(result) == 1
    _, kwargs = session.post.call_args
    assert kwargs["params"]["virtual_date"] == "28.07.2026"
    assert kwargs["params"]["isSinglePage"] == 1


def test_merge_preserves_manual_rows():
    manual = pd.DataFrame(
        [
            {
                "Код ценной бумаги": "RU000A100000",
                "ИНН": "1234567890",
                "Рейтинг": "ruAA",
                "Агентство": "АО «Эксперт РА»",
                "Комментарий": "Проверено вручную",
            }
        ],
        columns=RATING_COLUMNS,
    )
    fetched = parse_expert_ra_export(export_bytes())

    result = merge_rating_rows(manual, fetched)

    assert len(result) == 1
    assert result.iloc[0]["Рейтинг"] == "ruAA"
    assert result.iloc[0]["Комментарий"] == "Проверено вручную"


def test_merge_replaces_old_automatic_rating():
    existing = pd.DataFrame(
        [
            {
                "Код ценной бумаги": "RU000A100000",
                "Эмитент": 'ООО "Тест"',
                "ИНН": "1234567890",
                "Рейтинг": "ruBBB",
                "Агентство": "АО «Эксперт РА»",
                "Дата рейтинга": "01.01.2025",
                "Комментарий": EXPERT_RA_AUTO_COMMENT,
            }
        ],
        columns=RATING_COLUMNS,
    )
    fetched = parse_expert_ra_export(export_bytes())

    result = merge_rating_rows(existing, fetched)

    assert len(result) == 1
    assert result.iloc[0]["Рейтинг"] == "ruA+"
    assert result.iloc[0]["Дата рейтинга"] == "28.07.2026"


def test_merge_keeps_distinct_issuers_without_isin_and_inn():
    fetched = pd.DataFrame(
        [
            {
                "Эмитент": "Компания Один",
                "Рейтинг": "ruA",
                "Агентство": "АО «Эксперт РА»",
                "Комментарий": EXPERT_RA_AUTO_COMMENT,
            },
            {
                "Эмитент": "Компания Два",
                "Рейтинг": "ruBBB",
                "Агентство": "АО «Эксперт РА»",
                "Комментарий": EXPERT_RA_AUTO_COMMENT,
            },
        ],
        columns=RATING_COLUMNS,
    )

    result = merge_rating_rows(pd.DataFrame(columns=RATING_COLUMNS), fetched)

    assert len(result) == 2
    assert set(result["Эмитент"]) == {"Компания Один", "Компания Два"}


def test_enrich_issuer_identifiers_from_moex():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "securities": {
            "columns": ["secid", "emitent_title", "emitent_inn"],
            "data": [["RU000A100000", 'ООО "Тест"', "1234567890"]],
        }
    }
    session = Mock()
    session.get.return_value = response
    source = pd.DataFrame(
        [
            {
                "Код ценной бумаги": "RU000A100000",
                "Полное наименование": "Тест БО-01",
            }
        ]
    )

    result, failures = enrich_issuer_identifiers(source, session=session)

    assert failures == []
    assert result.iloc[0]["ИНН"] == "1234567890"


def test_enrich_reports_reason_when_inn_is_missing():
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "securities": {
            "columns": ["secid", "emitent_title", "emitent_inn"],
            "data": [["RU000A100000", 'ООО "Тест"', None]],
        }
    }
    session = Mock()
    session.get.return_value = response
    source = pd.DataFrame([{"Код ценной бумаги": "RU000A100000"}])

    _, failures = enrich_issuer_identifiers(source, session=session)

    assert len(failures) == 1
    assert "пустой ИНН" in failures[0]
