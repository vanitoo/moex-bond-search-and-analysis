from pathlib import Path

from app.core.configuration import (
    default_config,
    http_config,
    load_config,
    load_runtime_config,
    module_config,
    normalize_config,
    save_config,
)


def test_partial_config_receives_canonical_module_defaults():
    config = normalize_config({"strategy": "custom", "modules": {"credit": {}}})
    credit = module_config(config, "credit")
    assert config["strategy"] == "custom"
    assert credit["fetch_financials"] is True
    assert credit["financial_cache_days"] == 35
    assert credit["financial_workers"] == 1
    assert credit["fetch_bank_metrics"] is True
    assert credit["bank_cache_days"] == 7


def test_overrides_survive_normalization():
    config = normalize_config({
        "modules": {
            "market_search": {
                "version": "v2",
                "yield_more": 11.5,
            },
            "credit": {
                "financial_workers": 2,
            },
        },
    })
    market = module_config(config, "market_search")
    credit = module_config(config, "credit")
    assert market["version"] == "v2"
    assert market["yield_more"] == 11.5
    assert market["yield_less"] == 40.0
    assert credit["financial_workers"] == 2
    assert credit["financial_retries"] == 4


def test_default_config_returns_independent_copies():
    first = default_config()
    second = default_config()
    first["modules"]["credit"]["financial_workers"] = 4
    assert second["modules"]["credit"]["financial_workers"] == 1


def test_save_and_load_config_round_trip(tmp_path: Path):
    path = tmp_path / "custom.json"
    source = {
        "strategy": "custom",
        "modules": {
            "market_search": {
                "version": "v2",
                "yield_more": 9.0,
            },
        },
    }
    save_config(path, source)
    loaded = load_config(path)
    assert loaded["strategy"] == "custom"
    assert loaded["modules"]["market_search"]["version"] == "v2"
    assert loaded["modules"]["market_search"]["yield_more"] == 9.0
    assert loaded["modules"]["credit"]["financial_cache_days"] == 35


def test_unknown_future_top_level_section_is_preserved():
    config = normalize_config({"future": {"feature": True}})
    assert config["future"] == {"feature": True}


def test_http_config_applies_canonical_defaults():
    config = normalize_config({"http": {"accept_language": "en-US"}})
    settings = http_config(config)
    assert settings["accept_language"] == "en-US"
    assert "Mozilla/5.0" in settings["user_agent"]


def test_runtime_config_honors_explicit_bond_config(tmp_path: Path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(
        '{"strategy":"runtime","http":{"user_agent":"RuntimeAgent/1.0"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("BOND_CONFIG", str(path))
    loaded = load_runtime_config()
    assert loaded["strategy"] == "runtime"
    assert loaded["http"]["user_agent"] == "RuntimeAgent/1.0"
