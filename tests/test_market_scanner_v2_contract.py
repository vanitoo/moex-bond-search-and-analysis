from moex_bond_search_and_analysis.market_scanner_v2.filters import output_row


def test_v2_output_contains_v1_compatibility_columns():
    row = output_row({
        "SECID": "RU000A10TEST",
        "SHORTNAME": "Test",
        "SECNAME": "Test Bond",
        "BOARDID": "TQCB",
        "FACEVALUE": 1000,
        "OFFER": 99.5,
        "YIELD": 18.2,
        "DURATION": 365,
        "ISQUALIFIEDINVESTORS": 1,
        "Объем за 15 дней, шт.": 75000,
        "Минимальный дневной объем, шт.": 2500,
        "Сделок за 15 дней": 120,
        "История достаточна": "ДА",
        "Будущих купонов": 4,
        "Неизвестных будущих купонов": 0,
        "Купоны известны": "ДА",
    })
    assert row["Нужна квалификация?"] == "ДА"
    assert row["Для квалифицированных инвесторов"] == "ДА"
    assert row["Объем сделок с 15 дней, шт."] == 75000
    assert row["Объем за 15 дней, шт."] == 75000
