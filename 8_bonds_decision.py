from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_architecture import is_enabled, load_config
from pipeline_common import clean_secid_rows, latest, merge_by_secid, safe_float

RATING_ORDER = ["D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA"]
CRITICAL = ("дефолт", "просроч", "банкрот", "не покрывает процент", "отрицательный операционный")


def normalize(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower().replace("ё", "е"))


def rating(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "none", "null", "—", "-"}:
        return ""
    text = re.sub(r"[^A-Z+\-]", "", raw.upper().replace("(RU)", "").replace("RU", ""))
    return text if text in RATING_ORDER else ""


def yes(value: Any) -> bool:
    return normalize(value) in {"да", "true", "1", "yes"}


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


def decide(row: pd.Series, enabled: set[str], source_name: str) -> dict:
    scores: list[tuple[str, float, float]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []
    used: list[str] = []
    no_data: list[str] = []

    market_score = safe_float(row.get("Оценка, 0-100"))
    deep_score = safe_float(row.get("Итоговый балл"))
    credit_score = safe_float(row.get("Итоговый кредитный балл"))

    if "analysis" in enabled and market_score is not None:
        scores.append(("Первичный анализ", market_score, 1.0)); used.append("analysis")
    if "deep_analysis" in enabled and deep_score is not None:
        scores.append(("Глубокий анализ", deep_score, 1.2)); used.append("deep_analysis")
    if "credit" in enabled:
        if credit_score is not None:
            scores.append(("Кредитный анализ", credit_score, 1.3)); used.append("credit")
        else:
            no_data.append("credit")

    if not scores:
        y = safe_float(row.get("Доходность"), 0) or 0
        price = safe_float(row.get("Цена, %") or row.get("Цена"), 100) or 100
        duration = safe_float(row.get("Дюрация, месяцев"), 24) or 24
        base = 50
        if 15 <= y <= 25: base += 15
        elif y > 30: base -= 10
        if 85 <= price <= 110: base += 10
        if duration <= 18: base += 10
        scores.append(("Базовый рыночный отбор", max(0, min(100, base)), 1.0)); used.append("market_search")

    current_rating = rating(row.get("Рейтинг"))
    risks = normalize(row.get("Риски") or row.get("Риски и ограничения"))
    if "credit" in enabled:
        if current_rating in {"D", "C", "CC", "CCC"}:
            blockers.append(f"Недопустимый рейтинг {current_rating}")
        if any(marker in risks for marker in CRITICAL):
            blockers.append("Критическое событие в кредитных рисках")

    if "news" in enabled:
        critical_news = yes(row.get("Критический новостной стоп"))
        news_files = int(safe_float(row.get("Новостных файлов"), 0) or 0)
        if critical_news:
            blockers.append("Критический новостной стоп")
        elif news_files == 0:
            no_data.append("news")
        else:
            used.append("news")

    max_amount = safe_float(row.get("Максимум к покупке, руб."))
    max_qty = int(safe_float(row.get("Максимум к покупке, шт."), 0) or 0)
    spread = safe_float(row.get("Спред, %"))
    if "liquidity" in enabled:
        if max_amount is None:
            no_data.append("liquidity")
        elif max_amount <= 0 or max_qty <= 0:
            blockers.append("Нет подтверждённого доступного объёма покупки")
        else:
            used.append("liquidity")
            if spread is not None and spread > 3:
                blockers.append(f"Критически широкий bid/ask-спред {spread:.2f}%")
            elif spread is not None and spread > 1.5:
                warnings.append(f"Широкий bid/ask-спред {spread:.2f}%")

    ofz_bp = safe_float(row.get("Спред к ОФЗ, б.п.") or row.get("Спред, б.п."))
    if "ofz_spread" in enabled:
        if ofz_bp is None:
            no_data.append("ofz_spread")
        else:
            used.append("ofz_spread")
            if ofz_bp >= 1000: warnings.append(f"Экстремальный спред к ОФЗ {ofz_bp:.0f} б.п.")
            elif ofz_bp >= 600: warnings.append(f"Высокий спред к ОФЗ {ofz_bp:.0f} б.п.")

    weighted = sum(value * weight for _, value, weight in scores) / sum(weight for _, _, weight in scores)
    score = int(round(max(0, min(100, weighted))))
    if blockers:
        decision, eligible, max_share = "Не покупать", False, "0%"
        score = min(score, 25)
    elif score >= 82:
        decision, eligible, max_share = "Купить", True, "до 3–5%"
    elif score >= 68:
        decision, eligible, max_share = "Рассматривать", False, "до 1–3% после проверки"
    elif score >= 50:
        decision, eligible, max_share = "Требуется ручная проверка", False, "до 1%"
    else:
        decision, eligible, max_share = "Не покупать", False, "0%"

    reasons.extend(f"{name}: {value:.0f}/100" for name, value, _ in scores)
    disabled = sorted(set(["cashflow", "news", "liquidity", "ofz_spread", "analysis", "deep_analysis", "credit"]) - enabled)
    completeness = "Полная" if not no_data else f"Неполная: нет данных {', '.join(sorted(set(no_data)))}"

    return {
        "Полное наименование": row.get("Полное наименование"),
        "Код ценной бумаги": row.get("Код ценной бумаги"),
        "Доходность": row.get("Доходность"),
        "Финальное решение": decision,
        "Допущена в портфель": "ДА" if eligible else "НЕТ",
        "Финальный балл": score,
        "Максимальная доля": max_share,
        "Максимум к покупке, руб.": round(max_amount or 0, 2),
        "Максимум к покупке, шт.": max_qty,
        "Спред, %": spread,
        "Рейтинг": current_rating,
        "Причины": "; ".join(reasons) or "—",
        "Блокеры": "; ".join(blockers) or "—",
        "Предупреждения": "; ".join(warnings) or "—",
        "Учтённые модули": "; ".join(sorted(set(used))) or "—",
        "Отключённые модули": "; ".join(disabled) or "—",
        "Модули без данных": "; ".join(sorted(set(no_data))) or "—",
        "Полнота оценки": completeness,
        "Базовый источник": source_name,
    }


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

    result = pd.DataFrame([decide(row, enabled, source_name) for _, row in df.iterrows()])
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
        pd.DataFrame({"Параметр": ["Стратегия", "Включённые модули", "Базовый источник"], "Значение": [config.get("strategy"), ", ".join(sorted(enabled)), source_name]}).to_excel(writer, sheet_name="Конфигурация", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    json_path.write_text(json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Обработано уникальных SECID: {len(result)}")
    print(xlsx); print(html); print(json_path)


if __name__ == "__main__":
    main()
