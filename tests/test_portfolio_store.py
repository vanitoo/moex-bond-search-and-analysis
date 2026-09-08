from pathlib import Path

from portfolio_store import (
    create_portfolio,
    list_portfolios,
    load_portfolio,
    remove_position,
    save_portfolio,
    upsert_position,
)


def test_create_and_load_portfolio(tmp_path: Path) -> None:
    create_portfolio(tmp_path, "Основной")
    portfolios = list_portfolios(tmp_path)
    assert len(portfolios) == 1
    name = next(iter(portfolios))
    payload = load_portfolio(tmp_path, name)
    assert payload["positions"] == []


def test_upsert_and_remove_position(tmp_path: Path) -> None:
    create_portfolio(tmp_path, "Test")
    portfolio = load_portfolio(tmp_path, "Test")
    portfolio = upsert_position(portfolio, {
        "secid": "RU000A123456",
        "quantity": 10,
        "invested": 9500,
        "purchase_price_percent": 95,
        "purchase_date": "2026-09-08",
    })
    save_portfolio(tmp_path, portfolio)
    loaded = load_portfolio(tmp_path, "Test")
    assert loaded["positions"][0]["quantity"] == 10
    assert loaded["positions"][0]["invested"] == 9500

    loaded = upsert_position(loaded, {
        "secid": "RU000A123456",
        "quantity": 12,
        "invested": 11400,
        "purchase_price_percent": 95,
        "purchase_date": "2026-09-08",
    })
    assert len(loaded["positions"]) == 1
    assert loaded["positions"][0]["quantity"] == 12

    loaded = remove_position(loaded, "RU000A123456")
    assert loaded["positions"] == []
