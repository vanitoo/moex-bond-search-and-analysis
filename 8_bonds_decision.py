from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_common import latest, merge_by_secid, safe_float

RATING_ORDER = ["D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+", "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA"]
CRITICAL = ("дефолт", "просроч", "банкрот", "не покрывает процент", "отрицательный операционный")


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def rating(value: Any) -> str:
    text = str(value or "").upper().replace("(RU)", "").replace("RU", "")
    text = re.sub(r"[^A-Z+\-]", "", text)
    for item in sorted(RATING_ORDER, key=len, reverse=True):
        if item in text:
            return item
    return ""


def rating_at_least(value: str, minimum: str) -> bool:
    return value in RATING_ORDER and RATING_ORDER.index(value) >= RATING_ORDER.index(minimum)


def yes(value: Any) -> bool:
    return normalize(value) in {"да", "true", "1", "yes"}


def decide(row: pd.Series) -> dict:
    secid = str(row.get("Код ценной бумаги") or "")
    second_score = int(round(safe_float(row.get("Баллы второго слоя"), 0) or 0))
    credit_score = int(round(safe_float(row.get("Итоговый кредитный балл"), 0) or 0))
    current_rating = rating(row.get("Рейтинг"))
    confidence = str(row.get("Уверенность") or "Низкая")
    risks = normalize(row.get("Риски"))
    missing = normalize(row.get("Недостающие данные"))
    max_amount = safe_float(row.get("Максимум к покупке, руб."), 0) or 0
    max_qty = int(safe_float(row.get("Максимум к покупке, шт."), 0) or 0)
    spread = safe_float(row.get("Спред, %"))

    blockers: list[str] = []
    checks: list[str] = []
    reasons: list[str] = []
    if yes(row.get("Жёсткий стоп")):
        blockers.append("Жёсткий стоп предыдущего слоя")
    if any(marker in risks for marker in CRITICAL):
        blockers.append("Критическое событие в рисках")
    if current_rating in {"D", "C", "CC", "CCC"}:
        blockers.append(f"Недопустимый рейтинг {current_rating}")
    if max_amount <= 0 or max_qty <= 0:
        blockers.append("Нет подтверждённого доступного объёма покупки")
    if spread is not None and spread > 3:
        blockers.append(f"Критически широкий спред {spread:.2f}%")

    no_rating = not current_rating or "кредитный рейтинг" in missing
    no_financials = "финансовая отчетность" in missing
    low_confidence = normalize(confidence) == "низкая"

    if blockers:
        decision, eligible, score, max_share = "Не покупать", False, min(credit_score, 20), "0%"
    elif no_rating or no_financials or low_confidence:
        decision, eligible, score, max_share = "Недостаточно данных", False, min(credit_score, 59), "0%"
        if no_rating: checks.append("Добавить актуальный рейтинг")
        if no_financials: checks.append("Добавить финансовую отчётность")
    else:
        negative_forecast = any(x in normalize(row.get("Прогноз")) for x in ("негатив", "развива"))
        buy = second_score >= 70 and credit_score >= 82 and rating_at_least(current_rating, "BBB-") and not negative_forecast
        if buy:
            decision, eligible, score = "Купить", True, credit_score
            max_share = "до 7%" if credit_score >= 90 and rating_at_least(current_rating, "A-") else "до 5%" if credit_score >= 85 else "до 3%"
            reasons.extend([f"Второй слой {second_score}/100", f"Кредитный балл {credit_score}/100", f"Рейтинг {current_rating}"])
        elif credit_score < 45 or (current_rating and not rating_at_least(current_rating, "B+")):
            decision, eligible, score, max_share = "Не покупать", False, credit_score, "0%"
        else:
            decision, eligible, score, max_share = "Рассматривать", False, credit_score, "до 1–3% после проверки"
            checks.append("Не выполнены все пороги автоматической покупки")

    return {
        "Полное наименование": row.get("Полное наименование"),
        "Код ценной бумаги": secid,
        "Доходность": row.get("Доходность"),
        "Баллы второго слоя": second_score,
        "Итоговый кредитный балл": credit_score,
        "Рейтинг": current_rating,
        "Прогноз": row.get("Прогноз"),
        "Уверенность": confidence,
        "Финальное решение": decision,
        "Допущена в портфель": "ДА" if eligible else "НЕТ",
        "Финальный балл": score,
        "Максимальная доля": max_share,
        "Максимум к покупке, руб.": round(max_amount, 2),
        "Максимум к покупке, шт.": max_qty,
        "Спред, %": spread,
        "Причины": "; ".join(reasons) or "—",
        "Блокеры": "; ".join(blockers) or "—",
        "Ручные проверки": "; ".join(checks) or "—",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--volume")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    root = Path(".")
    source = Path(args.input) if args.input else latest(root, "bond_credit_analysis_*.xlsx")
    df = pd.read_excel(source, sheet_name="Кредитный анализ")
    volume_path = Path(args.volume) if args.volume else latest(root, "bond_purchase_volume_*.xlsx", required=False)
    if volume_path:
        volume = pd.read_excel(volume_path, sheet_name="Объем покупки")
        needed = [c for c in ("Код ценной бумаги", "Максимум к покупке, руб.", "Максимум к покупке, шт.", "Спред, %") if c in volume.columns]
        df = merge_by_secid(df, volume[needed])
    result = pd.DataFrame([decide(row) for _, row in df.iterrows()]).sort_values(["Допущена в портфель", "Финальный балл"], ascending=[False, False])
    candidates = result[result["Допущена в портфель"] == "ДА"].copy()
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_decisions_{stamp}.xlsx"
    html = out / f"bond_decisions_{stamp}.html"
    json_path = out / f"bond_candidates_{stamp}.json"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Решения", index=False)
        candidates.to_excel(writer, sheet_name="Кандидаты в портфель", index=False)
        pd.DataFrame({"Правило": ["Ликвидность", "Лимит позиции"], "Описание": ["Без подтверждённого доступного объёма покупка запрещена", "Портфель обязан соблюдать и долю стратегии, и максимум этапа 4"]}).to_excel(writer, sheet_name="Правила", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    json_path.write_text(json.dumps(candidates.to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(xlsx); print(html); print(json_path)


if __name__ == "__main__":
    main()
