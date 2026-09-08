from __future__ import annotations

from datetime import datetime

from moex_bond_search_and_analysis.news_sources import AggregatedNews, ProviderStatus, _company_aliases


def test_company_alias_prefers_quoted_brand():
    aliases = _company_aliases('Акционерное общество "Авто Финанс Банк"')
    assert "авто финанс банк" in aliases


def test_coverage_full_when_all_providers_work():
    result = AggregatedNews(providers=[
        ProviderStatus(provider="Google News", ok=True, item_count=2),
        ProviderStatus(provider="MOEX", ok=True, item_count=0),
    ])
    assert result.coverage == "FULL"


def test_coverage_partial_when_one_provider_fails():
    result = AggregatedNews(providers=[
        ProviderStatus(provider="Google News", ok=False, error="blocked"),
        ProviderStatus(provider="MOEX", ok=True, item_count=0),
    ])
    assert result.coverage == "PARTIAL"


def test_coverage_no_data_when_all_fail():
    result = AggregatedNews(providers=[
        ProviderStatus(provider="Google News", ok=False, error="blocked"),
        ProviderStatus(provider="MOEX", ok=False, error="timeout"),
    ])
    assert result.coverage == "NO_DATA"
