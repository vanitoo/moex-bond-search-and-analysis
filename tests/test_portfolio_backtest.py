from datetime import date
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "11_portfolio_backtest.py"
spec = importlib.util.spec_from_file_location("portfolio_backtest", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_interpolate_curve():
    curve = [(100, 15.0), (200, 17.0)]
    assert module.interpolate_curve(curve, 150) == 16.0
    assert module.interpolate_curve(curve, 50) == 15.0
    assert module.interpolate_curve(curve, 250) == 17.0


def test_score_rejects_ofz_and_accepts_liquid_corporate():
    ofz = {
        "SECID": "SU26238RMFS4",
        "FACEUNIT": "SUR",
        "_clean": 95.0,
        "_yield": 16.0,
        "_days": 365,
        "_spread_bp": 0.0,
        "VALUE": 10_000_000,
        "NUMTRADES": 100,
    }
    corporate = dict(ofz, SECID="RU000A000001", _yield=20.0, _spread_bp=400.0)
    assert module.score_candidate(ofz, 500_000, 5) is None
    assert module.score_candidate(corporate, 500_000, 5) is not None


def test_monitor_signal_sells_on_combined_deterioration():
    position = module.Position(
        secid="RU000A000001",
        name="Test",
        quantity=10,
        invested=10_000,
        average_full_price=1_000,
        last_full_price=1_000,
        last_clean_price=100.0,
        last_accrued=10.0,
        last_yield=20.0,
        last_spread_bp=300.0,
    )
    row = {"_clean": 90.0, "_yield": 55.0, "_spread_bp": 1100.0}
    action, reason = module.monitor_signal(position, row)
    assert action == "SELL"
    assert "спред" in reason


def test_target_day_prefers_offer_before_maturity():
    row = {"OFFERDATE": "2026-06-01", "MATDATE": "2027-06-01"}
    assert module.target_day(row, date(2026, 1, 1)) == date(2026, 6, 1)
