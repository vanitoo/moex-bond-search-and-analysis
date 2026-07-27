from pathlib import Path

import run_pipeline


def test_stage_range_covers_every_configured_stage():
    assert run_pipeline.FIRST_STAGE == 1
    assert run_pipeline.LAST_STAGE == len(run_pipeline.STAGES)
    assert run_pipeline.STAGES[run_pipeline.LAST_STAGE - 1] == "8_bonds_decision.py"


def test_purchase_and_credit_stage_positions():
    assert run_pipeline.STAGES.index("4b_bonds_purchase_volume.py") + 1 == 5
    assert run_pipeline.STAGES.index("7_bonds_credit_analysis.py") + 1 == 8


def test_stage_specific_arguments():
    root = Path("/project")

    assert run_pipeline.stage_arguments("3b_bonds_news.py", 0.1, root) == []
    assert run_pipeline.stage_arguments(
        "4b_bonds_purchase_volume.py", 0.1, root
    ) == ["--impact-share", "0.1"]
    assert run_pipeline.stage_arguments(
        "7_bonds_credit_analysis.py", 0.1, root
    ) == ["--data-dir", str(root / "data")]
