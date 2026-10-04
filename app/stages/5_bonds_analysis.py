from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core.market_analysis import ofz_spread_adjustment, score_row, yes
from app.core.pipeline_common import clean_secid_rows, latest, merge_by_secid
from app.core.search_contract import SEARCH_REQUIRED_COLUMNS, missing_search_columns, normalize_search_columns

REQUIRED = SEARCH_REQUIRED_COLUMNS


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
    parser.add_argument("--ofz-spread")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    root = Path(".")
    source = Path(args.input) if args.input else latest(root, "bond_search_*.xlsx")
    df = clean_secid_rows(pd.read_excel(source, sheet_name="Результаты поиска"))
    df = normalize_search_columns(df)
    missing = missing_search_columns(df)
    if missing:
        raise ValueError("Нет колонок: " + ", ".join(sorted(missing)))

    cash_path = Path(args.cashflow) if args.cashflow else latest(root, "bond_cashflow_*.xlsx", required=False)
    news_path = Path(args.news) if args.news else latest(root, "bond_news_*.xlsx", required=False)
    volume_path = Path(args.volume) if args.volume else latest(root, "bond_purchase_volume_*.xlsx", required=False)
    ofz_path = Path(args.ofz_spread) if args.ofz_spread else latest(root, "bond_ofz_spread_*.xlsx", required=False)
    df = merge_by_secid(df, load_stage(cash_path, "Cashflow"))
    df = merge_by_secid(df, load_stage(news_path, "Новости"))
    df = merge_by_secid(df, load_stage(volume_path, "Объем покупки"))
    df = merge_by_secid(df, load_stage(ofz_path, "Спред к ОФЗ"))

    results = [score_row(row) for _, row in df.iterrows()]
    df["Оценка, 0-100"] = [x[0] for x in results]
    df["Рекомендация"] = [x[1] for x in results]
    df["Положительные факторы"] = ["; ".join(x[2]) or "—" for x in results]
    df["Риски и ограничения"] = ["; ".join(x[3]) or "—" for x in results]
    df["Жёсткий стоп"] = ["ДА" if x[4] else "НЕТ" for x in results]
    df["Поправка за спред к ОФЗ"] = [x[5] for x in results]
    df["Источник cashflow"] = cash_path.name if cash_path else "НЕ НАЙДЕН"
    df["Источник новостей"] = news_path.name if news_path else "НЕ НАЙДЕН"
    df["Источник ликвидности"] = volume_path.name if volume_path else "НЕ НАЙДЕН"
    df["Источник спреда к ОФЗ"] = ofz_path.name if ofz_path else "НЕ НАЙДЕН"
    df = df.sort_values(["Оценка, 0-100", "Доходность"], ascending=[False, False])

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_analysis_{stamp}.xlsx"
    html = out / f"bond_analysis_{stamp}.html"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Анализ", index=False)
        pd.DataFrame(
            {
                "Этап": ["1", "2", "3", "4b", "4c"],
                "Файл": [
                    source.name,
                    cash_path.name if cash_path else "нет",
                    news_path.name if news_path else "нет",
                    volume_path.name if volume_path else "нет",
                    ofz_path.name if ofz_path else "нет",
                ],
            }
        ).to_excel(writer, sheet_name="Источники", index=False)
        pd.DataFrame(
            {
                "Диапазон спреда к ОФЗ": ["< 0 б.п.", "0–99", "100–299", "300–599", "600–999", ">= 1000"],
                "Поправка к баллу": [-6, -3, 3, 6, 1, -6],
                "Смысл": [
                    "Корпоративная бумага даёт меньше ОФЗ",
                    "Премия почти не компенсирует кредитный риск",
                    "Умеренная премия",
                    "Хорошая премия без экстремального сигнала риска",
                    "Высокая премия: нужна кредитная проверка",
                    "Экстремальная премия: вероятен серьёзный риск",
                ],
            }
        ).to_excel(writer, sheet_name="Методика ОФЗ", index=False)
    html.write_text(df.to_html(index=False), encoding="utf-8")
    print(f"Обработано уникальных SECID: {len(df)}")
    print(xlsx); print(html)


if __name__ == "__main__":
    main()
