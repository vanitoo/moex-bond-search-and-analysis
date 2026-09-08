from portfolio_allocator import allocate_budget


def bond(secid: str, score: float, price: float = 100.0, issuer: str | None = None, risk_rating: str = "A"):
    return {
        "secid": secid,
        "name": secid,
        "issuer": issuer or secid,
        "market": {"price": price, "face_value": 1000.0, "yield": 20.0},
        "decision": {"score": score, "status": "Купить"},
        "credit": {"rating": risk_rating, "score": score},
        "liquidity": {"max_purchase_rub": 100000.0},
        "ofz_spread": {"spread_bp": 400.0},
    }


def test_allocator_spends_budget_in_whole_bonds():
    bonds = {
        "A": bond("A", 90),
        "B": bond("B", 80),
        "C": bond("C", 70),
    }
    result = allocate_budget({"positions": []}, bonds, ["A", "B", "C"], 10000.0)
    assert result["invested"] <= 10000.0
    assert result["reserve"] < 1000.0
    assert sum(line["amount"] for line in result["lines"]) == result["invested"]
    assert all(line["quantity"] == int(line["quantity"]) and line["quantity"] > 0 for line in result["lines"])
    assert result["lines"][0]["amount"] >= result["lines"][-1]["amount"]


def test_allocator_respects_existing_issuer_concentration():
    bonds = {
        "OLD": bond("OLD", 80, issuer="Issuer X"),
        "X2": bond("X2", 95, issuer="Issuer X"),
        "Y": bond("Y", 80, issuer="Issuer Y"),
    }
    portfolio = {
        "positions": [
            {"secid": "OLD", "issuer": "Issuer X", "quantity": 20, "invested": 20000.0, "rating": "A"}
        ]
    }
    result = allocate_budget(portfolio, bonds, ["X2", "Y"], 10000.0, max_issuer_percent=25.0)
    by_id = {line["secid"]: line for line in result["lines"]}
    assert "Y" in by_id
    assert "X2" not in by_id


def test_allocator_excludes_hard_stop_candidate():
    good = bond("GOOD", 85)
    bad = bond("BAD", 95)
    bad["decision"]["status"] = "Не покупать"
    bonds = {"GOOD": good, "BAD": bad}
    result = allocate_budget({"positions": []}, bonds, ["GOOD", "BAD"], 5000.0)
    assert {line["secid"] for line in result["lines"]} == {"GOOD"}
    assert any(item["secid"] == "BAD" for item in result["excluded"])


def test_allocator_can_leave_reserve_when_limits_block_more():
    bonds = {"A": bond("A", 90)}
    result = allocate_budget({"positions": []}, bonds, ["A"], 10000.0, max_position_percent=20.0)
    assert result["invested"] == 2000.0
    assert result["reserve"] == 8000.0
