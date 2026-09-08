from portfolio_recommendation import recommend_candidate


def bond(secid, *, score=80, rating="A", ytm=18, max_purchase=100000, status="Купить", risk_spread=300):
    return {
        "secid": secid,
        "name": secid,
        "market": {"yield": ytm},
        "liquidity": {"max_purchase_rub": max_purchase},
        "ofz_spread": {"spread_bp": risk_spread},
        "credit": {"rating": rating},
        "decision": {"score": score, "status": status},
        "news": {"critical_stop": False},
        "modules": {},
    }


def portfolio(*secids):
    return {
        "name": "test",
        "positions": [
            {"secid": secid, "name": secid, "quantity": 10, "invested": 100000, "yield": 15, "rating": "A"}
            for secid in secids
        ],
    }


def test_buy_new_candidate_with_complete_data():
    old = bond("OLD", score=78)
    candidate = bond("NEW", score=82)
    result = recommend_candidate(portfolio("OLD"), candidate, 20_000, {"OLD": old, "NEW": candidate})
    assert result["action"] == "КУПИТЬ"
    assert result["confidence"] == "высокая"


def test_add_to_existing_position():
    candidate = bond("HELD", score=85)
    result = recommend_candidate(portfolio("HELD"), candidate, 10_000, {"HELD": candidate})
    assert result["action"] == "ДОКУПИТЬ"


def test_replace_materially_weaker_position():
    weak = bond("WEAK", score=60, rating="BBB")
    candidate = bond("NEW", score=85, rating="A")
    result = recommend_candidate(portfolio("WEAK"), candidate, 20_000, {"WEAK": weak, "NEW": candidate})
    assert result["action"] == "ЗАМЕНИТЬ"
    assert result["replacement"]["secid"] == "WEAK"


def test_do_not_buy_when_liquidity_limit_exceeded():
    candidate = bond("NEW", score=90, max_purchase=10_000)
    result = recommend_candidate({"name": "test", "positions": []}, candidate, 50_000, {"NEW": candidate})
    assert result["action"] == "НЕ ПОКУПАТЬ"
    assert any("лимита ликвидности" in reason for reason in result["negatives"])


def test_wait_when_key_modules_are_missing():
    candidate = {
        "secid": "NEW",
        "name": "NEW",
        "market": {"yield": 20},
        "cashflow": {},
        "modules": {},
    }
    result = recommend_candidate({"name": "test", "positions": []}, candidate, 20_000, {"NEW": candidate})
    assert result["action"] == "ОЖИДАЕТ ДАННЫХ"
    assert result["warnings"]
    assert any("не хватает данных" in reason or "решение ещё не сформировано" in reason for reason in result["warnings"])
