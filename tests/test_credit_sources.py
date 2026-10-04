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


from app.core.credit_sources import FinancialRefreshOptions, IssuerPopulation, refresh_financials
from moex_bond_search_and_analysis.financials import FetchStats, FINANCIAL_COLUMNS


def test_refresh_financials_is_fail_soft_on_provider_error(tmp_path, capsys):
    existing = pd.DataFrame([{
        **{column: None for column in FINANCIAL_COLUMNS},
        "ИНН": "1234567890",
        "Эмитент": "ООО Тест",
        "Комментарий": "Проверено вручную",
    }])
    population = IssuerPopulation(
        corporate_inns=("1234567890",),
        bank_issuers=(),
        type_counts={"Корпоративный": 1},
    )

    def broken_fetcher(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    result = refresh_financials(
        existing,
        tmp_path / "issuer_financials.xlsx",
        tmp_path,
        population,
        enabled=True,
        options=FinancialRefreshOptions(
            cache_days=35,
            workers=1,
            delay_seconds=0,
            retries=1,
        ),
        fetcher=broken_fetcher,
    )

    assert result.equals(existing)
    assert "provider unavailable" in capsys.readouterr().out


def test_refresh_financials_merges_partial_provider_result(tmp_path):
    existing = pd.DataFrame(columns=FINANCIAL_COLUMNS)
    population = IssuerPopulation(
        corporate_inns=("1234567890", "0987654321"),
        bank_issuers=(),
        type_counts={"Корпоративный": 2},
    )
    fetched = pd.DataFrame([{
        **{column: None for column in FINANCIAL_COLUMNS},
        "ИНН": "1234567890",
        "Эмитент": "ООО Тест",
        "Период": "2025",
        "Выручка": 1000,
        "Комментарий": "Автоматически из публичного JSON ГИР БО ФНС",
    }])
    stats = FetchStats(
        requested=2,
        fetched=1,
        cached=0,
        not_found=0,
        errors=("ИНН 0987654321: timeout",),
    )

    def partial_fetcher(*args, **kwargs):
        return fetched, stats

    result = refresh_financials(
        existing,
        tmp_path / "issuer_financials.xlsx",
        tmp_path,
        population,
        enabled=True,
        options=FinancialRefreshOptions(
            cache_days=35,
            workers=1,
            delay_seconds=0,
            retries=1,
        ),
        fetcher=partial_fetcher,
    )

    assert len(result) == 1
    assert result.iloc[0]["ИНН"] == "1234567890"
    assert (tmp_path / "issuer_financials.xlsx").exists()
