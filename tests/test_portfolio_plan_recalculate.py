from portfolio_plan import recalculate_allocation_plan


def test_recalculate_plan_updates_amounts_and_reserve():
    lines = [
        {"secid": "A", "name": "A", "quantity": 3, "unit_cost": 1000.0, "amount": 3000.0, "share_percent": 30.0},
        {"secid": "B", "name": "B", "quantity": 2, "unit_cost": 900.0, "amount": 1800.0, "share_percent": 18.0},
    ]
    result = recalculate_allocation_plan(lines, {"A": 4, "B": 1}, 10000.0)
    assert result["invested"] == 4900.0
    assert result["reserve"] == 5100.0
    assert result["over_budget"] is False
    assert [line["quantity"] for line in result["lines"]] == [4, 1]


def test_recalculate_plan_drops_zero_quantity_and_flags_over_budget():
    lines = [
        {"secid": "A", "name": "A", "quantity": 1, "unit_cost": 3000.0, "amount": 3000.0, "share_percent": 30.0},
        {"secid": "B", "name": "B", "quantity": 1, "unit_cost": 2500.0, "amount": 2500.0, "share_percent": 25.0},
    ]
    result = recalculate_allocation_plan(lines, {"A": 0, "B": 3}, 5000.0)
    assert [line["secid"] for line in result["lines"]] == ["B"]
    assert result["invested"] == 7500.0
    assert result["reserve"] == -2500.0
    assert result["over_budget"] is True
