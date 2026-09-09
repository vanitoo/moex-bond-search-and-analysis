from datetime import date

from portfolio_income import analyze_portfolio_income


def test_income_calendar_multiplies_cashflows_by_quantity():
    portfolio = {
        "name": "p1",
        "positions": [
            {
                "secid": "RU1",
                "name": "Bond 1",
                "issuer": "Issuer 1",
                "quantity": 10,
                "invested": 9000,
            },
            {
                "secid": "RU2",
                "name": "Bond 2",
                "issuer": "Issuer 2",
                "quantity": 5,
                "invested": 5000,
            },
        ],
    }

    def fetcher(secid: str):
        if secid == "RU1":
            return {
                "coupons": [
                    {"coupondate": "2026-10-15", "value": 50},
                    {"coupondate": "2027-04-15", "value": 50},
                ],
                "amortizations": [{"amortdate": "2027-06-01", "value": 1000}],
                "offers": [],
            }
        return {
            "coupons": [{"coupondate": "2026-11-20", "value": 40}],
            "amortizations": [],
            "offers": [],
        }

    result = analyze_portfolio_income(portfolio, today=date(2026, 9, 9), fetcher=fetcher)
    summary = result["summary"]
    assert summary["coupons_12m"] == 1200.0
    assert summary["principal_12m"] == 10000.0
    assert summary["cashflow_12m"] == 11200.0
    assert summary["next_payment_date"] == "2026-10-15"
    assert summary["income_months"] == 3
    assert summary["rebalance_needed"] is True


def test_unknown_coupon_is_counted_but_not_added_to_income():
    portfolio = {
        "name": "p2",
        "positions": [{"secid": "RU1", "quantity": 2, "invested": 2000}],
    }

    def fetcher(_: str):
        return {
            "coupons": [{"coupondate": "2026-10-01", "value": None}],
            "amortizations": [],
            "offers": [],
        }

    result = analyze_portfolio_income(portfolio, today=date(2026, 9, 9), fetcher=fetcher)
    assert result["summary"]["coupons_12m"] == 0.0
    assert result["summary"]["unknown_coupon_events"] == 1
