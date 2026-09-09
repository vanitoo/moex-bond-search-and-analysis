from selection_profiles import (
    SELECTION_PROFILES,
    apply_selection_profile,
    matching_profile,
    profile_label,
)


def test_strict_profile_matches_existing_filter() -> None:
    settings = {
        "yield_more": 15.0,
        "yield_less": 40.0,
        "price_more": 70.0,
        "price_less": 120.0,
        "duration_more": 3.0,
        "duration_less": 18.0,
        "volume_more": 2000.0,
        "bond_volume_more": 60000.0,
        "require_known_coupons": True,
    }
    assert matching_profile(settings) == "strict_current"


def test_apply_short_profile_changes_duration_and_keeps_other_settings() -> None:
    settings = {"enabled": True, "version": "v2", "workers": 5}
    result = apply_selection_profile(settings, "short")
    assert result["enabled"] is True
    assert result["version"] == "v2"
    assert result["duration_more"] == 1.0
    assert result["duration_less"] == 18.0
    assert result["selection_profile"] == "short"
    assert matching_profile(result) == "short"


def test_duration_profiles_are_separated() -> None:
    short = SELECTION_PROFILES["short"]["settings"]
    medium = SELECTION_PROFILES["medium"]["settings"]
    long = SELECTION_PROFILES["long"]["settings"]
    assert short["duration_less"] <= medium["duration_less"]
    assert medium["duration_more"] < long["duration_more"]
    assert long["duration_less"] > medium["duration_less"]


def test_manual_change_becomes_custom() -> None:
    result = apply_selection_profile({}, "soft_balanced")
    result["bond_volume_more"] = 12345.0
    assert matching_profile(result) is None
    assert profile_label("missing") == "Пользовательский"
