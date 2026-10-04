from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


from app.core.deep_analysis import analyze_deep_row, evaluate, is_yes
from app.core.stage_io import load_stage_frame, publish_stage_frame
from app.core.stage_contract import FrameContract

REQUIRED = {
    "Полное наименование", "Код ценной бумаги", "Доходность",
    "Оценка, 0-100", "Рекомендация", "Риски и ограничения",
}
INPUT_CONTRACT = FrameContract.from_columns("stage 6 / deep analysis", REQUIRED)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    stage_input = load_stage_frame(run_dir=Path("."), module="analysis", pattern="bond_analysis_*.xlsx", sheet="Анализ", explicit=args.input)
    df = stage_input.frame
    INPUT_CONTRACT.validate(df)
    result = pd.DataFrame([evaluate(row) for _, row in df.iterrows()]).sort_values("Итоговый балл", ascending=False)
    publish_stage_frame("deep_analysis", result)
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    xlsx = out / f"bond_deep_analysis_{stamp}.xlsx"
    html = out / f"bond_deep_analysis_{stamp}.html"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        result.to_excel(writer, sheet_name="Глубокий анализ", index=False)
        pd.DataFrame({"Источник": [stage_input.source], "Описание": ["Включены результаты cashflow, новостей, ликвидности и спреда к ОФЗ из нормализованного результата этапа 5"]}).to_excel(writer, sheet_name="Методика", index=False)
    html.write_text(result.to_html(index=False), encoding="utf-8")
    print(xlsx); print(html)


if __name__ == "__main__":
    main()
