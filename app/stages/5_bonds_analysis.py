from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.core.market_analysis import ofz_spread_adjustment, score_row, yes
from app.core.pipeline_common import clean_secid_rows, merge_by_secid
from app.core.stage_io import load_stage_frame
from app.core.search_contract import SEARCH_REQUIRED_COLUMNS, missing_search_columns, normalize_search_columns

REQUIRED = SEARCH_REQUIRED_COLUMNS


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
    base_input = load_stage_frame(run_dir=root, module="market_search", pattern="bond_search_*.xlsx",
                                  sheet="Результаты поиска", explicit=args.input)
    df = normalize_search_columns(clean_secid_rows(base_input.frame))
    missing = missing_search_columns(df)
    if missing:
        raise ValueError("Нет колонок: " + ", ".join(sorted(missing)))

    cash = load_stage_frame(run_dir=root, module="cashflow", pattern="bond_cashflow_*.xlsx", sheet="Cashflow", explicit=args.cashflow, required=False)
    news = load_stage_frame(run_dir=root, module="news", pattern="bond_news_*.xlsx", sheet="Новости", explicit=args.news, required=False)
    volume = load_stage_frame(run_dir=root, module="liquidity", pattern="bond_purchase_volume_*.xlsx", sheet="Объем покупки", explicit=args.volume, required=False)
    ofz = load_stage_frame(run_dir=root, module="ofz_spread", pattern="bond_ofz_spread_*.xlsx", sheet="Спред к ОФЗ", explicit=args.ofz_spread, required=False)
    df = merge_by_secid(df, clean_secid_rows(cash.frame))
    df = merge_by_secid(df, clean_secid_rows(news.frame))
    df = merge_by_secid(df, clean_secid_rows(volume.frame))
    df = merge_by_secid(df, clean_secid_rows(ofz.frame))

    results = [score_row(row) for _, row in df.iterrows()]
    df["Оценка, 0-100"] = [x[0] for x in results]
    df["Рекомендация"] = [x[1] for x in results]
    df["Положительные факторы"] = ["; ".join(x[2]) or "—" for x in results]
    df["Риски и ограничения"] = ["; ".join(x[3]) or "—" for x in results]
    df["Жёсткий стоп"] = ["ДА" if x[4] else "НЕТ" for x in results]
    df["Поправка за спред к ОФЗ"] = [x[5] for x in results]
    df["Источник cashflow"] = cash.source
    df["Источник новостей"] = news.source
    df["Источник ликвидности"] = volume.source
    df["Источник спреда к ОФЗ"] = ofz.source
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
                    base_input.source,
                    cash.source,
                    news.source,
                    volume.source,
                    ofz.source,
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
