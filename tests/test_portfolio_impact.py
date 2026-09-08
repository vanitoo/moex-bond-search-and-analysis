from portfolio_impact import simulate_purchase


def test_purchase_impact_changes_weights_and_yield():
    portfolio = {
        "positions": [
            {"secid": "RU0000000001", "invested": 100000, "issuer": "Issuer A"},
            {"secid": "RU0000000002", "invested": 100000, "issuer": "Issuer B"},
        ]
    }
    bonds = {
        "RU0000000001": {"secid": "RU0000000001", "market": {"yield": 10}, "credit": {"rating": "AA"}},
        "RU0000000002": {"secid": "RU0000000002", "market": {"yield": 20}, "credit": {"rating": "AA"}},
        "RU0000000003": {
            "secid": "RU0000000003",
            "market": {"yield": 30},
            "credit": {"rating": "BBB"},
            "liquidity": {"max_purchase_rub": 60000},
            "raw": {"credit": {"Эмитент": "Issuer C"}},
        },
    }

    result = simulate_purchase(portfolio, bonds["RU0000000003"], 50000, bonds)

    assert round(result["weighted_yield_before"], 2) == 15.00
    assert round(result["weighted_yield_after"], 2) == 18.00
    assert round(result["candidate_share_percent"], 2) == 20.00
    assert round(result["issuer_share_after_percent"], 2) == 20.00
    assert result["liquidity_ok"] is True
    assert result["effective_positions_after"] > result["effective_positions_before"]


def test_liquidity_limit_is_detected():
    portfolio = {"positions": [{"secid": "RU0000000001", "invested": 100000}]}
    candidate = {"secid": "RU0000000002", "market": {"yield": 20}, "liquidity": {"max_purchase_rub": 30000}}
    result = simulate_purchase(portfolio, candidate, 50000, {"RU0000000002": candidate})
    assert result["liquidity_ok"] is False
    assert any("ликвидности" in note for note in result["notes"])
