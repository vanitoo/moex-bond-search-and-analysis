from datetime import datetime, timedelta
import os
from pathlib import Path

import run_pipeline


def test_stage_range_covers_every_configured_stage():
    assert run_pipeline.FIRST_STAGE == 1
    assert run_pipeline.LAST_STAGE == len(run_pipeline.STAGES)
    assert run_pipeline.STAGES[run_pipeline.LAST_STAGE - 1] == "8_bonds_decision.py"


def test_market_credit_and_ofz_stage_positions():
    assert run_pipeline.STAGES.index("4b_bonds_purchase_volume.py") + 1 == 5
    assert run_pipeline.STAGES.index("4c_bonds_ofz_spread.py") + 1 == 6
    assert run_pipeline.STAGES.index("5_bonds_analysis.py") + 1 == 7
    assert run_pipeline.STAGES.index("7_bonds_credit_analysis.py") + 1 == 9


def test_stage_specific_arguments():
    root = Path("/project")

    assert run_pipeline.stage_arguments("3b_bonds_news.py", 0.1, root) == []
    assert run_pipeline.stage_arguments(
        "4b_bonds_purchase_volume.py", 0.1, root
    ) == ["--impact-share", "0.1"]
    assert run_pipeline.stage_arguments("4c_bonds_ofz_spread.py", 0.1, root) == []
    assert run_pipeline.stage_arguments(
        "7_bonds_credit_analysis.py", 0.1, root
    ) == ["--data-dir", str(root / "data")]


def test_credit_stage_uses_fresh_ratings_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ratings = data_dir / "issuer_ratings.xlsx"
    ratings.write_bytes(b"not-empty")

    arguments = run_pipeline.stage_arguments(
        "7_bonds_credit_analysis.py", 0.1, tmp_path
    )

    assert arguments == [
        "--data-dir",
        str(data_dir),
        "--no-fetch-ratings",
    ]


def test_credit_stage_refresh_flag_ignores_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ratings = data_dir / "issuer_ratings.xlsx"
    ratings.write_bytes(b"not-empty")

    arguments = run_pipeline.stage_arguments(
        "7_bonds_credit_analysis.py",
        0.1,
        tmp_path,
        refresh_ratings=True,
    )

    assert arguments == ["--data-dir", str(data_dir)]


def test_old_ratings_cache_is_not_reused(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ratings = data_dir / "issuer_ratings.xlsx"
    ratings.write_bytes(b"not-empty")
    old_time = (datetime.now() - timedelta(hours=48)).timestamp()
    os.utime(ratings, (old_time, old_time))

    arguments = run_pipeline.stage_arguments(
        "7_bonds_credit_analysis.py",
        0.1,
        tmp_path,
        ratings_cache_hours=24,
    )

    assert arguments == ["--data-dir", str(data_dir)]
