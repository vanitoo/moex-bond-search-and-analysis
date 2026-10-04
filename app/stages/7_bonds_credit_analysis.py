from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.credit_engine import (
    CreditResult, RATING_POINTS, best_match, build_analysis, calculate_metrics,
    evaluate, fmt, normalize, normalize_rating, parse_date, ratio,
    rating_direction, row_match_score, safe_float,
)
from app.core.credit_sources import BankRefreshOptions, FinancialRefreshOptions
from app.core.stage_io import load_stage_frame
from app.core.credit_workflow import (
    FINANCIAL_TEMPLATE_COLUMNS, RATING_TEMPLATE_COLUMNS, REQUIRED_DEEP_COLUMNS,
    create_templates, find_latest_deep_file, load_deep, load_optional_table,
    run_credit_workflow, CreditWorkflowRequest,
)
from moex_bond_search_and_analysis.cbr_banks import DEFAULT_BANK_CACHE_DAYS, DEFAULT_BANK_DELAY_SECONDS
from moex_bond_search_and_analysis.financials import DEFAULT_CACHE_DAYS, DEFAULT_DELAY_SECONDS, DEFAULT_RETRIES, DEFAULT_WORKERS


def main() -> int:
    parser = argparse.ArgumentParser(description="Третий слой анализа облигаций")
    parser.add_argument("--input", type=Path, help="Файл bond_deep_analysis_YYYY-MM-DD.xlsx")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Каталог рейтингов и финансов")
    parser.add_argument("--output-dir", type=Path, default=Path("."), help="Каталог результатов")
    parser.add_argument("--no-fetch-ratings", action="store_true", help="Не обновлять рейтинги с официального сайта «Эксперт РА»")
    parser.add_argument("--no-fetch-financials", action="store_true", help="Не обновлять финансовые показатели из публичного ГИР БО ФНС")
    parser.add_argument("--financial-cache-days", type=int, default=DEFAULT_CACHE_DAYS)
    parser.add_argument("--financial-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--financial-delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--financial-retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--no-fetch-bank-metrics", action="store_true", help="Не обновлять обязательные нормативы банков из формы 0409135 Банка России")
    parser.add_argument("--bank-cache-days", type=int, default=DEFAULT_BANK_CACHE_DAYS)
    parser.add_argument("--bank-delay-seconds", type=float, default=DEFAULT_BANK_DELAY_SECONDS)
    args = parser.parse_args()

    try:
        stage_input = load_stage_frame(run_dir=Path.cwd(), module="deep_analysis", pattern="bond_deep_analysis_*.xlsx", sheet="Глубокий анализ", explicit=args.input)
        source = args.input or Path(stage_input.source)
        result = run_credit_workflow(
            CreditWorkflowRequest(
                source=source,
                input_frame=stage_input.frame,
                source_label=stage_input.source,
                data_dir=args.data_dir,
                output_dir=args.output_dir,
                fetch_ratings=not args.no_fetch_ratings,
                fetch_financials=not args.no_fetch_financials,
                fetch_bank_metrics=not args.no_fetch_bank_metrics,
                financial_options=FinancialRefreshOptions(
                    cache_days=args.financial_cache_days,
                    workers=args.financial_workers,
                    delay_seconds=args.financial_delay_seconds,
                    retries=args.financial_retries,
                ),
                bank_options=BankRefreshOptions(
                    cache_days=args.bank_cache_days,
                    delay_seconds=args.bank_delay_seconds,
                ),
            ),
            progress=lambda index, total, name, secid: print(f"[{index}/{total}] Кредитный анализ: {name} ({secid})"),
        )
        print(f"ИНН эмитентов определён через MOEX ISS: {result.identified_issuers}/{len(result.analysis)}")
        if result.identity_failures:
            print("Внимание: ИНН не найден для: " + ", ".join(result.identity_failures))
        type_counts = result.analysis["Тип эмитента"].value_counts().to_dict()
        print("Кредитные модели: " + ", ".join(f"{key}: {value}" for key, value in type_counts.items()))
        print(f"Готово: {result.excel_path}")
        print(f"Готово: {result.html_path}")
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
