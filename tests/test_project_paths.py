from app.core.project_paths import (
    CONFIGS_ROOT,
    DATA_ROOT,
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    REPORTS_ROOT,
    RUNS_ROOT,
    VIRTUAL_PORTFOLIOS_ROOT,
)


def test_project_paths_share_one_repository_root():
    assert RUNS_ROOT == PROJECT_ROOT / "runs"
    assert DATA_ROOT == PROJECT_ROOT / "data"
    assert REPORTS_ROOT == PROJECT_ROOT / "reports"
    assert CONFIGS_ROOT == PROJECT_ROOT / "configs"
    assert DEFAULT_CONFIG == CONFIGS_ROOT / "balanced.json"
    assert VIRTUAL_PORTFOLIOS_ROOT == DATA_ROOT / "virtual_portfolios"
