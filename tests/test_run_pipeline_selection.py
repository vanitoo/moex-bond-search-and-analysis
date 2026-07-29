from argparse import Namespace

import run_pipeline


def test_selected_stage_numbers_keeps_pipeline_order():
    args = Namespace(from_stage=1, to_stage=10, only_module=["decision", "liquidity"])
    numbers = run_pipeline.selected_stage_numbers(args)
    assert numbers == [5, 10]


def test_selected_stage_numbers_uses_range_without_only_module():
    args = Namespace(from_stage=3, to_stage=5, only_module=[])
    assert run_pipeline.selected_stage_numbers(args) == [3, 4, 5]
