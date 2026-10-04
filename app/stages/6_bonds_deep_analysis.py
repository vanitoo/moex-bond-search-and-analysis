from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


from app.core.deep_analysis import analyze_deep_row, evaluate, is_yes
from app.core.pipeline_common import latest

REQUIRED = {
    "Полное наименование", "Код ценной бумаги", "Доходность",
    "Оценка, 0-100", "Рекомендация", "Риски и ограничения",
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
