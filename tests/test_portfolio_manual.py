from portfolio_manual import make_position


def test_make_position_uses_manual_purchase_data():
    bond = {
        "secid": "RU0000000001",
        "name": "Test Bond",
        "issuer": "Test Issuer",
        "face_value": 1000,
        "accrued_interest": 12.5,
        "market_price_percent": 98.0,
        "yield": 17.2,
        "maturity_date": "2028-01-01",
    }
    position = make_position(
        bond,
        quantity=10,
        purchase_price_percent=97.5,
        invested=9900,
        purchase_date="2026-09-01",
    )
    assert position["secid"] == "RU0000000001"
    assert position["quantity"] == 10
    assert position["purchase_price_percent"] == 97.5
    assert position["invested"] == 9900.0
    assert position["issuer"] == "Test Issuer"
    assert position["source"] == "manual"


def test_make_position_can_calculate_invested_with_nkd():
    bond = {
        "secid": "RU0000000002",
        "name": "Test Bond 2",
        "face_value": 1000,
        "accrued_interest": 10,
        "market_price_percent": 99,
    }
    position = make_position(bond, quantity=2)
    assert position["invested"] == 2000.0
