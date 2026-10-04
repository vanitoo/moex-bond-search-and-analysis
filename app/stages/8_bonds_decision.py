from __future__ import annotations

import argparse
from pathlib import Path

from app.core.configuration import load_config
from app.core.decision_engine import (
    CRITICAL, annotate_shortlist_reasons as _annotate_shortlist_reasons,
    decide, issuer_key as _issuer_key, negative_factors as _negative_factors,
    normalize, yes,
)
from app.core.decision_workflow import (
    DecisionWorkflowRequest, choose_base, load_optional, run_decision_workflow,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--config")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    config = load_config(Path(args.config).expanduser().resolve() if args.config else None)
    result = run_decision_workflow(DecisionWorkflowRequest(
        root=Path("."),
        output_dir=Path(args.output_dir),
        config=config,
        explicit_input=args.input,
    ))

    shortlist = result.shortlist
    print(f"Обработано уникальных SECID: {len(result.decisions)}")
    print(f"Учтено рейтинговых событий: {result.rating_event_count}")
    print(f"Допущено к покупке: {shortlist['admitted']}")
    print(f"Сильных кандидатов (балл >= {shortlist['thresholds']['strong_score']}): {shortlist['strong']}")
    print(f"Финальный shortlist по разным эмитентам: {shortlist['shortlist_count']}")
    for item in shortlist["shortlist"]:
        print(f"  {item['secid']}: {item['name']} — {item['score']:.0f}, {item['rating'] or 'без рейтинга'}")
    print(result.excel_path)
    print(result.html_path)
    print(result.json_path)
    print(shortlist["json_path"])
    print(shortlist["xlsx_path"])


if __name__ == "__main__":
    main()
