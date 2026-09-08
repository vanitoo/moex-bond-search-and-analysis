from portfolio_plan import apply_allocation_plan


def test_apply_plan_adds_new_position():
    portfolio = {"name": "test", "positions": []}
    lines = [{"secid": "A", "name": "Bond A", "issuer": "Issuer A", "quantity": 3, "amount": 3100.0}]
    result = apply_allocation_plan(portfolio, lines, {"A": {"secid": "A", "name": "Bond A"}}, "2026-09-09")
    assert len(result["positions"]) == 1
    assert result["positions"][0]["quantity"] == 3
    assert result["positions"][0]["invested"] == 3100.0


def test_apply_plan_merges_existing_position():
    portfolio = {
        "name": "test",
        "positions": [{"secid": "A", "name": "Bond A", "quantity": 2, "invested": 2000.0, "purchase_date": "2026-08-01"}],
    }
    lines = [{"secid": "A", "name": "Bond A", "issuer": "Issuer A", "quantity": 3, "amount": 3150.0}]
    result = apply_allocation_plan(portfolio, lines, {"A": {"secid": "A", "name": "Bond A"}}, "2026-09-09")
    position = result["positions"][0]
    assert position["quantity"] == 5
    assert position["invested"] == 5150.0
    assert position["purchase_date"] == "2026-09-09"
