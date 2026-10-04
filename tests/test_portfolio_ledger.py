from pathlib import Path

from app.portfolio.portfolio_ledger import append_transaction, cash_balance, read_ledger


def test_ledger_cash_flow(tmp_path: Path):
    append_transaction(tmp_path, "Основной", "DEPOSIT", amount=50000)
    append_transaction(tmp_path, "Основной", "BUY", amount=12000, secid="RU000A10TEST", quantity=12, unit_cost=1000)
    append_transaction(tmp_path, "Основной", "COUPON", amount=500, secid="RU000A10TEST")
    append_transaction(tmp_path, "Основной", "SELL", amount=3000, secid="RU000A10TEST", quantity=3, unit_cost=1000)
    append_transaction(tmp_path, "Основной", "REDEMPTION", amount=9000, secid="RU000A10TEST")
    rows = read_ledger(tmp_path, "Основной")
    assert [row["type"] for row in rows] == ["DEPOSIT", "BUY", "COUPON", "SELL", "REDEMPTION"]
    assert cash_balance(rows) == 50500.0


def test_invalid_buy_requires_security_and_quantity(tmp_path: Path):
    try:
        append_transaction(tmp_path, "P", "BUY", amount=1000)
    except ValueError as exc:
        assert "SECID" in str(exc)
    else:
        raise AssertionError("BUY without SECID must fail")
