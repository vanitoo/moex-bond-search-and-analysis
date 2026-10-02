from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "app" / "core"
PORTFOLIO = ROOT / "app" / "portfolio"
SRC = ROOT / "src"
for _path in (str(CORE), str(PORTFOLIO), str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.core.pipeline_architecture import is_enabled, load_config
from app.core.pipeline_common import clean_secid_rows, latest, merge_by_secid
from moex_bond_search_and_analysis.rating_signal import load_rating_events
from app.portfolio.portfolio_shortlist import annotate_decisions, write_shortlist
from app.core.decision_engine import (
    CRITICAL,
    RATING_ORDER,
    annotate_shortlist_reasons as _annotate_shortlist_reasons,
    decide,
    issuer_key as _issuer_key,
    negative_factors as _negative_factors,
    normalize,
    rating,
    yes,
)

def load_optional(root: Path, pattern: str, sheet: str | int = 0) -> pd.DataFrame:
    path = latest(root, pattern, required=False)
    if not path:
        return pd.DataFrame(columns=["Код ценной бумаги"])
    try:
        return clean_secid_rows(pd.read_excel(path, sheet_name=sheet))
    except Exception:
        return clean_secid_rows(pd.read_excel(path, sheet_name=0))


def choose_base(root: Path, config: dict, explicit: str | None) -> tuple[pd.DataFrame, str]:
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
        path = latest(root, pattern, required=False)
        if path:
            try:
                return clean_secid_rows(pd.read_excel(path, sheet_name=sheet)), path.name
            except Exception:
                return clean_secid_rows(pd.read_excel(path, sheet_name=0)), path.name
    raise FileNotFoundError("Нет ни одного доступного результата для финального решения")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--config")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    root = Path(".")
    config = load_config(Path(args.config).expanduser().resolve() if args.config else None)
    enabled = {key for key in config.get("modules", {}) if is_enabled(config, key)}
    df, source_name = choose_base(root, config, args.input)
    rating_events = load_rating_events(root)

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
            df = merge_by_secid(df, load_optional(root, pattern, sheet))

    result = pd.DataFrame([decide(row, enabled, source_name, rating_events) for _, row in df.iterrows()])
    result = annotate_decisions(result)
    result = result.sort_values(["Допущена в портфель", "Финальный балл"], ascending=[False, False])
    candidates = result[result["Допущена в портфель"] == "ДА"].copy()

    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_decisions_{stamp}.xlsx"
    html = out / f"bond_decisions_{stamp}.html"
    json_path = out / f"bond_candidates_{stamp}.json"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Решения", index=False)
        candidates.to_excel(writer, sheet_name="Кандидаты в портфель", index=False)
        pd.DataFrame({"Параметр": ["Стратегия", "Включённые модули", "Базовый источник", "Рейтинговых событий"], "Значение": [config.get("strategy"), ", ".join(sorted(enabled)), source_name, len(rating_events)]}).to_excel(writer, sheet_name="Конфигурация", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    json_path.write_text(json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")
    shortlist = write_shortlist(result, out, stamp)
    result = _annotate_shortlist_reasons(result, shortlist)
    candidates = result[result["Допущена в портфель"] == "ДА"].copy()
    # Перезаписываем Excel/HTML уже с отметкой shortlist.
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Решения", index=False)
        candidates.to_excel(writer, sheet_name="Кандидаты в портфель", index=False)
        pd.DataFrame({"Параметр": ["Стратегия", "Включённые модули", "Базовый источник", "Рейтинговых событий"], "Значение": [config.get("strategy"), ", ".join(sorted(enabled)), source_name, len(rating_events)]}).to_excel(writer, sheet_name="Конфигурация", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    json_path.write_text(
        json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Обработано уникальных SECID: {len(result)}")
    print(f"Учтено рейтинговых событий: {len(rating_events)}")
    print(f"Допущено к покупке: {shortlist['admitted']}")
    print(f"Сильных кандидатов (балл >= {shortlist['thresholds']['strong_score']}): {shortlist['strong']}")
    print(f"Финальный shortlist по разным эмитентам: {shortlist['shortlist_count']}")
    for item in shortlist["shortlist"]:
        print(f"  {item['secid']}: {item['name']} — {item['score']:.0f}, {item['rating'] or 'без рейтинга'}")
    print(xlsx); print(html); print(json_path); print(shortlist["json_path"]); print(shortlist["xlsx_path"])


if __name__ == "__main__":
    main()
