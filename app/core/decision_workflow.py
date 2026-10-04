from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.configuration import is_enabled
from app.core.decision_engine import annotate_shortlist_reasons, decide
from app.core.pipeline_common import clean_secid_rows, latest, merge_by_secid
from app.core.stage_registry import PIPELINE_STAGES
from app.core.run_store import RunStore, run_id_for
from app.portfolio.portfolio_shortlist import annotate_decisions, write_shortlist
from moex_bond_search_and_analysis.rating_signal import load_rating_events


@dataclass(frozen=True)
class DecisionWorkflowRequest:
    root: Path
    output_dir: Path
    config: dict[str, Any]
    explicit_input: str | None = None
    store: RunStore | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class DecisionWorkflowResult:
    decisions: pd.DataFrame
    candidates: pd.DataFrame
    shortlist: dict[str, Any]
    excel_path: Path
    html_path: Path
    json_path: Path
    source_name: str
    enabled_modules: frozenset[str]
    rating_event_count: int


def load_optional(
    root: Path,
    pattern: str,
    sheet: str | int = 0,
    *,
    store: RunStore | None = None,
    run_id: str | None = None,
    module: str | None = None,
) -> pd.DataFrame:
    if store is not None and run_id and module:
        stored = store.read_frame(run_id, module)
        if stored is not None:
            return clean_secid_rows(stored)
    path = latest(root, pattern, required=False)
    if not path:
        return pd.DataFrame(columns=["Код ценной бумаги"])
    try:
        return clean_secid_rows(pd.read_excel(path, sheet_name=sheet))
    except Exception:
        return clean_secid_rows(pd.read_excel(path, sheet_name=0))


def choose_base(
    root: Path,
    config: dict[str, Any],
    explicit: str | None,
    *,
    store: RunStore | None = None,
    run_id: str | None = None,
) -> tuple[pd.DataFrame, str]:
    if explicit:
        path = Path(explicit)
        return clean_secid_rows(pd.read_excel(path, sheet_name=0)), path.name
    candidates = [
        ("credit", "bond_credit_analysis_*.xlsx", "Кредитный анализ"),
        ("deep_analysis", "bond_deep_analysis_*.xlsx", "Глубокий анализ"),
        ("analysis", "bond_analysis_*.xlsx", "Анализ"),
        ("market_search", "bond_search_*.xlsx", "Результаты поиска"),
    ]
    for key, pattern, sheet in candidates:
        if not is_enabled(config, key):
            continue
        if store is not None and run_id:
            stored = store.read_frame(run_id, key)
            if stored is not None:
                return clean_secid_rows(stored), f"sqlite:{run_id}:{key}"
        path = latest(root, pattern, required=False)
        if path:
            try:
                return clean_secid_rows(pd.read_excel(path, sheet_name=sheet)), path.name
            except Exception:
                return clean_secid_rows(pd.read_excel(path, sheet_name=0)), path.name
    raise FileNotFoundError("Нет ни одного доступного результата для финального решения")


def _write_outputs(
    result: pd.DataFrame,
    candidates: pd.DataFrame,
    request: DecisionWorkflowRequest,
    enabled: set[str],
    source_name: str,
    rating_event_count: int,
    stamp: str,
) -> tuple[Path, Path, Path]:
    request.output_dir.mkdir(parents=True, exist_ok=True)
    xlsx = request.output_dir / f"bond_decisions_{stamp}.xlsx"
    html = request.output_dir / f"bond_decisions_{stamp}.html"
    json_path = request.output_dir / f"bond_candidates_{stamp}.json"
    config_table = pd.DataFrame({
        "Параметр": ["Стратегия", "Включённые модули", "Базовый источник", "Рейтинговых событий"],
        "Значение": [
            request.config.get("strategy"),
            ", ".join(sorted(enabled)),
            source_name,
            rating_event_count,
        ],
    })
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Решения", index=False)
        candidates.to_excel(writer, sheet_name="Кандидаты в портфель", index=False)
        config_table.to_excel(writer, sheet_name="Конфигурация", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    json_path.write_text(
        json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return xlsx, html, json_path


def run_decision_workflow(request: DecisionWorkflowRequest) -> DecisionWorkflowResult:
    enabled = {stage.key for stage in PIPELINE_STAGES if is_enabled(request.config, stage.key)}
    run_id = request.run_id or run_id_for(request.root)
    df, source_name = choose_base(
        request.root, request.config, request.explicit_input,
        store=request.store, run_id=run_id,
    )
    rating_events = load_rating_events(request.root)

    optional = [
        ("cashflow", "bond_cashflow_*.xlsx", "Cashflow"),
        ("news", "bond_news_*.xlsx", "Новости"),
        ("liquidity", "bond_purchase_volume_*.xlsx", "Объем покупки"),
        ("ofz_spread", "bond_ofz_spread_*.xlsx", "Спред к ОФЗ"),
        ("analysis", "bond_analysis_*.xlsx", "Анализ"),
        ("deep_analysis", "bond_deep_analysis_*.xlsx", "Глубокий анализ"),
        ("credit", "bond_credit_analysis_*.xlsx", "Кредитный анализ"),
    ]
    for key, pattern, sheet in optional:
        if key in enabled:
            df = merge_by_secid(df, load_optional(
                request.root, pattern, sheet,
                store=request.store, run_id=run_id, module=key,
            ))

    result = pd.DataFrame([
        decide(row, enabled, source_name, rating_events)
        for _, row in df.iterrows()
    ])
    result = annotate_decisions(result)
    result = result.sort_values(["Допущена в портфель", "Финальный балл"], ascending=[False, False])

    stamp = datetime.now().strftime("%Y-%m-%d")
    request.output_dir.mkdir(parents=True, exist_ok=True)
    shortlist = write_shortlist(result, request.output_dir, stamp)
    result = annotate_shortlist_reasons(result, shortlist)
    if request.store is not None and run_id:
        request.store.write_frame(run_id, "decision", result)
    candidates = result[result["Допущена в портфель"] == "ДА"].copy()
    xlsx, html, json_path = _write_outputs(
        result, candidates, request, enabled, source_name, len(rating_events), stamp
    )
    return DecisionWorkflowResult(
        decisions=result,
        candidates=candidates,
        shortlist=shortlist,
        excel_path=xlsx,
        html_path=html,
        json_path=json_path,
        source_name=source_name,
        enabled_modules=frozenset(enabled),
        rating_event_count=len(rating_events),
    )
