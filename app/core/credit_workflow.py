from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from app.core.credit_engine import build_analysis
from app.core.credit_report import write_excel, write_html
from app.core.stage_contract import FrameContract
from app.core.credit_sources import (
    BankRefreshOptions,
    FinancialRefreshOptions,
    classify_population,
    refresh_bank_metrics,
    refresh_financials,
    refresh_ratings,
)
from moex_bond_search_and_analysis.cbr_banks import BANK_COLUMNS
from moex_bond_search_and_analysis.ratings import enrich_issuer_identifiers


RATING_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Рейтинг", "Агентство",
    "Прогноз", "Дата рейтинга", "Предыдущий рейтинг", "Дата предыдущего рейтинга",
    "Источник", "Комментарий",
]
FINANCIAL_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Период", "Валюта",
    "Выручка", "EBITDA", "Чистая прибыль", "Операционный денежный поток",
    "Денежные средства", "Общий долг", "Краткосрочный долг",
    "Процентные расходы", "Собственный капитал", "Оборотные активы",
    "Краткосрочные обязательства", "Источник", "Комментарий",
]
REQUIRED_DEEP_COLUMNS = {
    "Полное наименование", "Код ценной бумаги", "Итоговый балл", "Решение",
    "Жёсткий стоп", "Доходность", "Риски", "Недостающие данные",
}
DEEP_INPUT_CONTRACT = FrameContract.from_columns("stage 7 / credit analysis", REQUIRED_DEEP_COLUMNS)


@dataclass(frozen=True)
class CreditWorkflowRequest:
    source: Path
    data_dir: Path
    fetch_ratings: bool
    fetch_financials: bool
    fetch_bank_metrics: bool
    financial_options: FinancialRefreshOptions
    bank_options: BankRefreshOptions
    output_dir: Path = Path(".")


@dataclass(frozen=True)
class CreditWorkflowResult:
    analysis: pd.DataFrame
    excel_path: Path
    html_path: Path
    ratings_path: Path
    financials_path: Path
    identified_issuers: int
    identity_failures: tuple[str, ...]


def find_latest_deep_file(directory: Path) -> Path:
    files = [p for p in directory.glob("bond_deep_analysis_*.xlsx") if not p.name.startswith("~$")]
    if not files:
        raise FileNotFoundError("Не найден bond_deep_analysis_YYYY-MM-DD.xlsx. Сначала запустите скрипт №6.")
    return max(files, key=lambda p: p.stat().st_mtime)


def load_deep(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Глубокий анализ")
    return DEEP_INPUT_CONTRACT.clean(df)


def create_templates(data_dir: Path) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    ratings = data_dir / "issuer_ratings.xlsx"
    financials = data_dir / "issuer_financials.xlsx"
    if not ratings.exists() and not ratings.with_suffix(".csv").exists():
        pd.DataFrame(columns=RATING_TEMPLATE_COLUMNS).to_excel(ratings, index=False)
    if not financials.exists() and not financials.with_suffix(".csv").exists():
        pd.DataFrame(columns=FINANCIAL_TEMPLATE_COLUMNS).to_excel(financials, index=False)
    return ratings, financials


def load_optional_table(xlsx_path: Path, required_columns: list[str]) -> pd.DataFrame:
    csv_path = xlsx_path.with_suffix(".csv")
    path = csv_path if csv_path.exists() else xlsx_path
    if not path.exists():
        return pd.DataFrame(columns=required_columns)
    df = pd.read_csv(path, sep=None, engine="python") if path.suffix.lower() == ".csv" else pd.read_excel(path)
    for column in required_columns:
        if column not in df.columns:
            df[column] = None
    return df


def run_credit_workflow(
    request: CreditWorkflowRequest,
    *,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> CreditWorkflowResult:
    ratings_path, financials_path = create_templates(request.data_dir)
    ratings = load_optional_table(ratings_path, RATING_TEMPLATE_COLUMNS)
    ratings = refresh_ratings(ratings, ratings_path, enabled=request.fetch_ratings)
    financials = load_optional_table(financials_path, FINANCIAL_TEMPLATE_COLUMNS)

    deep = load_deep(request.source)
    deep, identity_failures = enrich_issuer_identifiers(deep)
    population = classify_population(deep, ratings)

    financials = refresh_financials(
        financials,
        financials_path,
        request.data_dir,
        population,
        enabled=request.fetch_financials,
        options=request.financial_options,
    )

    bank_metrics_path = request.data_dir / "issuer_bank_metrics.xlsx"
    bank_metrics = (
        load_optional_table(bank_metrics_path, BANK_COLUMNS)
        if bank_metrics_path.exists()
        else pd.DataFrame(columns=BANK_COLUMNS)
    )
    bank_metrics = refresh_bank_metrics(
        bank_metrics,
        bank_metrics_path,
        request.data_dir,
        population,
        enabled=request.fetch_bank_metrics,
        options=request.bank_options,
    )

    analysis = build_analysis(deep, ratings, financials, bank_metrics, progress=progress)
    request.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    excel = request.output_dir / f"bond_credit_analysis_{stamp}.xlsx"
    html = request.output_dir / f"bond_credit_analysis_{stamp}.html"
    write_excel(analysis, excel, request.source)
    write_html(analysis, html, request.source)

    return CreditWorkflowResult(
        analysis=analysis,
        excel_path=excel,
        html_path=html,
        ratings_path=ratings_path,
        financials_path=financials_path,
        identified_issuers=len(deep) - len(identity_failures),
        identity_failures=tuple(identity_failures),
    )
