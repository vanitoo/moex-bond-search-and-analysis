from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_common import clean_secid_rows, latest, merge_by_secid, safe_float

REQUIRED = {"Полное наименование", "Код ценной бумаги", "Нужна квалификация?", "Цена, %", "Объем сделок с 15 дней, шт.", "Доходность", "Дюрация, месяцев"}


def yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"да", "yes", "true", "1"}


def score_row(row: pd.Series) -> tuple[int, str, list[str], list[str], bool]:
    score, good, risks = 0, [], []
    y = safe_float(row.get("Доходность"), 0) or 0
    price = safe_float(row.get("Цена, %"), 0) or 0
    duration = safe_float(row.get("Дюрация, месяцев"), 99) or 99
    volume = safe_float(row.get("Объем сделок с 15 дней, шт."), 0) or 0
    max_buy = safe_float(row.get("Максимум к покупке, руб."), 0) or 0
    spread = safe_float(row.get("Спред, %"))
    unknown = int(safe_float(row.get("Неизвестных купонов"), 0) or 0)
    hard_stop = yes(row.get("Критический новостной стоп"))

    if 15 <= y <= 22: score += 24; good.append("Рабочая доходность")
    elif y < 15: score += 14
    elif y <= 27: score += 18; risks.append("Повышенная доходность")
    else: score += 6; risks.append("Очень высокая доходность — сигнал риска")

    if 90 <= price <= 105: score += 12; good.append("Цена около номинала")
    elif 80 <= price <= 110: score += 8
    else: score += 3; risks.append("Цена сильно отличается от номинала")

    if duration <= 12: score += 12; good.append("Короткая/умеренная дюрация")
    elif duration <= 24: score += 8
    else: score += 3; risks.append("Высокая чувствительность к ставке")

    if volume >= 200_000: score += 15
    elif volume >= 60_000: score += 10
    else: score += 3; risks.append("Низкий объём торгов")

    if max_buy >= 100_000: score += 15; good.append("Достаточный доступный объём")
    elif max_buy >= 30_000: score += 10
    elif max_buy > 0: score += 4; risks.append("Ограниченный объём покупки")
    else: risks.append("Нет подтверждённого доступного объёма")

    if spread is not None:
        if spread <= 0.5: score += 8; good.append("Узкий спред")
        elif spread <= 1.5: score += 5
        else: risks.append("Широкий спред")

    if unknown == 0: score += 7; good.append("Будущие купоны известны")
    else: risks.append(f"Неизвестных будущих купонов: {unknown}")

    if not yes(row.get("Нужна квалификация?")): score += 7
    else: risks.append("Требуется статус квалифицированного инвестора")

    if str(row.get("Полнота новостей") or "") == "Нет данных": risks.append("Нет новостных данных")
    if hard_stop: score = min(score, 15); risks.append("Критический новостной стоп")
    score = max(0, min(100, round(score)))
    if hard_stop or score < 45: decision = "Не покупать без ручного анализа"
    elif score >= 82: decision = "Рассматривать в первую очередь"
    elif score >= 68: decision = "Рассматривать"
    else: decision = "Требуется углублённая проверка"
    return score, decision, good, risks, hard_stop


def load_stage(path: Path | None, sheet: str) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=["Код ценной бумаги"])
    return clean_secid_rows(pd.read_excel(path, sheet_name=sheet))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--cashflow")
    parser.add_argument("--news")
    parser.add_argument("--volume")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    root = Path(".")
    source = Path(args.input) if args.input else latest(root, "bond_search_*.xlsx")
    df = clean_secid_rows(pd.read_excel(source, sheet_name="Результаты поиска"))
    missing = REQUIRED.difference(df.columns)
    if missing:
        raise ValueError("Нет колонок: " + ", ".join(sorted(missing)))

    cash_path = Path(args.cashflow) if args.cashflow else latest(root, "bond_cashflow_*.xlsx", required=False)
    news_path = Path(args.news) if args.news else latest(root, "bond_news_*.xlsx", required=False)
    volume_path = Path(args.volume) if args.volume else latest(root, "bond_purchase_volume_*.xlsx", required=False)
    df = merge_by_secid(df, load_stage(cash_path, "Cashflow"))
    df = merge_by_secid(df, load_stage(news_path, "Новости"))
    df = merge_by_secid(df, load_stage(volume_path, "Объем покупки"))

    results = [score_row(row) for _, row in df.iterrows()]
    df["Оценка, 0-100"] = [x[0] for x in results]
    df["Рекомендация"] = [x[1] for x in results]
    df["Положительные факторы"] = ["; ".join(x[2]) or "—" for x in results]
    df["Риски и ограничения"] = ["; ".join(x[3]) or "—" for x in results]
    df["Жёсткий стоп"] = ["ДА" if x[4] else "НЕТ" for x in results]
    df["Источник cashflow"] = cash_path.name if cash_path else "НЕ НАЙДЕН"
    df["Источник новостей"] = news_path.name if news_path else "НЕ НАЙДЕН"
    df["Источник ликвидности"] = volume_path.name if volume_path else "НЕ НАЙДЕН"
    df = df.sort_values(["Оценка, 0-100", "Доходность"], ascending=[False, False])

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_analysis_{stamp}.xlsx"
    html = out / f"bond_analysis_{stamp}.html"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Анализ", index=False)
        pd.DataFrame({"Этап": ["1", "2", "3", "4"], "Файл": [source.name, cash_path.name if cash_path else "нет", news_path.name if news_path else "нет", volume_path.name if volume_path else "нет"]}).to_excel(writer, sheet_name="Источники", index=False)
    html.write_text(df.to_html(index=False), encoding="utf-8")
    print(f"Обработано уникальных SECID: {len(df)}")
    print(xlsx); print(html)


if __name__ == "__main__":
    main()
