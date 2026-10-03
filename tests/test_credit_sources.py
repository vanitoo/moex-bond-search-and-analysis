import pandas as pd

from app.core.credit_sources import classify_population


def test_classify_population_splits_corporates_and_banks():
    deep = pd.DataFrame([
        {
            "Код ценной бумаги": "SEC-CORP",
            "Полное наименование": "ООО Ромашка 001Р-01",
            "ИНН": "1234567890",
        },
        {
            "Код ценной бумаги": "SEC-BANK",
            "Полное наименование": "Сбербанк БО-01",
            "ИНН": "7707083893",
        },
    ])
    ratings = pd.DataFrame(columns=["Код ценной бумаги", "Эмитент", "ИНН"])

    population = classify_population(deep, ratings)

    assert "1234567890" in population.corporate_inns
    assert all(item["inn"] != "1234567890" for item in population.bank_issuers)
    assert any(item["inn"] == "7707083893" for item in population.bank_issuers)
    assert population.type_counts["Корпоративный"] == 1
    assert population.type_counts["Банк"] == 1


def test_bank_population_deduplicates_same_issuer():
    deep = pd.DataFrame([
        {"Код ценной бумаги": "SEC-1", "Полное наименование": "Сбербанк БО-01", "ИНН": "7707083893"},
        {"Код ценной бумаги": "SEC-2", "Полное наименование": "Сбербанк БО-02", "ИНН": "7707083893"},
    ])
    ratings = pd.DataFrame(columns=["Код ценной бумаги", "Эмитент", "ИНН"])

    population = classify_population(deep, ratings)

    assert len(population.bank_issuers) == 1
