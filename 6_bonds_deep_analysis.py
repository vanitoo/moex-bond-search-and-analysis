from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from pipeline_common import latest, safe_float

REQUIRED = {
    "Полное наименование", "Код ценной бумаги", "Доходность",
    "Оценка, 0-100", "Рекомендация", "Риски и ограничения",
}


def is_yes(value: object) -> bool:
    return str(value or "").strip().lower() in {"да", "true", "1", "yes"}


def evaluate(row: pd.Series) -> dict:
    market_score = int(round(safe_float(row.get("Оценка, 0-100"), 0) or 0))
    structure_score = 25
    news_score = 20
    liquidity_score = 15
    completeness = 10
    penalty = 0
    positives: list[str] = []
    risks: list[str] = []
    missing: list[str] = []
    hard_stop = is_yes(row.get("Жёсткий стоп")) or is_yes(row.get("Критический новостной стоп"))

    future_coupons = int(safe_float(row.get("Будущих купонов"), 0) or 0)
    unknown_coupons = int(safe_float(row.get("Неизвестных купонов"), 0) or 0)
    amortizations = int(safe_float(row.get("Будущих амортизаций"), 0) or 0)
    offer = str(row.get("Ближайшая оферта") or "").strip()
    max_buy = safe_float(row.get("Максимум к покупке, руб."), 0) or 0
    spread = safe_float(row.get("Спред, %"))
    ofz_spread_bp = safe_float(row.get("Спред к ОФЗ, б.п."))
    ofz_yield = safe_float(row.get("Доходность сопоставимой ОФЗ, %"))
    ofz_quality = str(row.get("Качество данных спреда") or "").strip()
    news_files = int(safe_float(row.get("Новостных файлов"), 0) or 0)
    negative_news = str(row.get("Негативные события") or "—")
    positive_news = str(row.get("Позитивные события") or "—")

    if future_coupons > 0:
        positives.append(f"Будущих купонов: {future_coupons}")
    else:
        missing.append("График будущих купонов")
        structure_score -= 8
    if unknown_coupons:
        risks.append(f"Неизвестных будущих купонов: {unknown_coupons}")
        structure_score -= min(12, unknown_coupons * 2)
    else:
        positives.append("Будущие купоны определены")
    if amortizations:
        positives.append(f"Учтены амортизации: {amortizations}")
    if offer:
        positives.append(f"Ближайшая оферта: {offer}")

    if ofz_spread_bp is None:
        missing.append("Спред к ОФЗ")
        completeness -= 1
    elif 100 <= ofz_spread_bp < 600:
        positives.append(f"Премия к ОФЗ: {ofz_spread_bp:.0f} б.п.")
    elif ofz_spread_bp >= 600:
        risks.append(f"Высокий спред к ОФЗ: {ofz_spread_bp:.0f} б.п.")
    elif ofz_spread_bp < 100:
        risks.append(f"Низкая премия к ОФЗ: {ofz_spread_bp:.0f} б.п.")

    if news_files == 0:
        missing.append("Новости эмитента")
        news_score -= 8
        completeness -= 3
    else:
        positives.append(f"Проверено новостных файлов: {news_files}")
    if negative_news not in {"", "—", "nan"}:
        risks.append(negative_news)
        news_score -= 10
    if positive_news not in {"", "—", "nan"}:
        positives.append(positive_news)

    if max_buy >= 100_000:
        positives.append("Доступный объём покупки не менее 100 000 ₽")
    elif max_buy >= 30_000:
        liquidity_score -= 4
    elif max_buy > 0:
        risks.append("Малый доступный объём покупки")
        liquidity_score -= 10
    else:
        risks.append("Не подтверждён доступный объём покупки")
        liquidity_score = 0
        completeness -= 3
    if spread is not None and spread > 2:
        risks.append(f"Широкий bid/ask-спред: {spread:.2f}%")
        liquidity_score -= 6

    prior_risks = str(row.get("Риски и ограничения") or "")
    if prior_risks and prior_risks != "—":
        risks.append(prior_risks)

    final_score = round(market_score * 0.30 + max(0, structure_score) + max(0, news_score) + max(0, liquidity_score) + max(0, completeness) - penalty)
    final_score = max(0, min(100, final_score))
    if hard_stop:
        final_score = min(final_score, 20)
        decision = "Не покупать"
    elif len(missing) >= 3:
        final_score = min(final_score, 55)
        decision = "Недостаточно данных"
    elif final_score >= 82:
        decision = "Рассматривать к покупке"
    elif final_score >= 70:
        decision = "Рассматривать"
    elif final_score >= 58:
        decision = "Только небольшой долей"
    elif final_score >= 45:
        decision = "Ждать и проверить вручную"
    else:
        decision = "Не покупать"

    return {
        "Полное наименование": row.get("Полное наименование"),
        "Код ценной бумаги": row.get("Код ценной бумаги"),
        "Доходность": row.get("Доходность"),
        "Доходность сопоставимой ОФЗ, %": ofz_yield,
        "Спред к ОФЗ, б.п.": ofz_spread_bp,
        "ОФЗ сравнения": row.get("ОФЗ сравнения"),
        "Оценка премии к ОФЗ": row.get("Оценка премии к ОФЗ"),
        "Качество данных спреда": ofz_quality,
        "Рыночный балл": market_score,
        "Баллы структуры": max(0, structure_score),
        "Баллы новостей": max(0, news_score),
        "Баллы ликвидности": max(0, liquidity_score),
        "Полнота данных": max(0, completeness),
        "Итоговый балл": final_score,
        "Решение": decision,
        "Жёсткий стоп": "ДА" if hard_stop else "НЕТ",
        "Максимум к покупке, руб.": max_buy,
        "Максимум к покупке, шт.": row.get("Максимум к покупке, шт."),
        "Спред, %": spread,
        "Будущих купонов": future_coupons,
        "Неизвестных купонов": unknown_coupons,
        "Ближайшая оферта": offer,
        "Положительные факторы": "; ".join(positives) or "—",
        "Риски": "; ".join(risks) or "—",
        "Недостающие данные": "; ".join(missing) or "—",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    source = Path(args.input) if args.input else latest(Path("."), "bond_analysis_*.xlsx")
    df = pd.read_excel(source, sheet_name="Анализ")
    missing = REQUIRED.difference(df.columns)
    if missing:
        raise ValueError("Во входном файле нет колонок: " + ", ".join(sorted(missing)))
    result = pd.DataFrame([evaluate(row) for _, row in df.iterrows()]).sort_values("Итоговый балл", ascending=False)
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_deep_analysis_{stamp}.xlsx"
    html = out / f"bond_deep_analysis_{stamp}.html"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Глубокий анализ", index=False)
        pd.DataFrame({"Источник": [source.name], "Описание": ["Включены результаты cashflow, новостей, ликвидности и спреда к ОФЗ, переданные через файл этапа 5"]}).to_excel(writer, sheet_name="Методика", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    print(xlsx); print(html)


if __name__ == "__main__":
    main()
