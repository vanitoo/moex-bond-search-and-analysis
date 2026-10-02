from stage_registry import (
    BY_SCRIPT,
    MODULE_DESCRIPTIONS,
    PIPELINE_STAGES,
    PIPELINE_STAGE_SCRIPTS,
    resolve_market_script,
)


def test_pipeline_registry_has_exactly_ten_ordered_stages():
    assert [stage.number for stage in PIPELINE_STAGES] == list(range(1, 11))
    assert len(PIPELINE_STAGE_SCRIPTS) == 10
    assert PIPELINE_STAGE_SCRIPTS[0] == "1_bonds_search_by_criteria.py"
    assert PIPELINE_STAGE_SCRIPTS[-1] == "8_bonds_decision.py"


def test_market_v1_and_v2_share_one_logical_module():
    assert BY_SCRIPT["1_bonds_search_by_criteria.py"].key == "market_search"
    assert BY_SCRIPT["1_bonds_market_scanner_v2.py"].key == "market_search"
    assert resolve_market_script("v1") == "1_bonds_search_by_criteria.py"
    assert resolve_market_script("v2") == "1_bonds_market_scanner_v2.py"


def test_every_runtime_script_has_description():
    for script in BY_SCRIPT:
        assert script in MODULE_DESCRIPTIONS
        assert MODULE_DESCRIPTIONS[script]
