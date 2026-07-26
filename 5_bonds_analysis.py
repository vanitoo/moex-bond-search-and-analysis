# 📊 Анализ облигаций после первичного отбора
#
# Скрипт читает последний файл bond_search_YYYY-MM-DD.xlsx, созданный скриптом №1,
# присваивает каждой облигации прозрачную балльную оценку и формирует:
#   - bond_analysis_YYYY-MM-DD.xlsx
#   - bond_analysis_YYYY-MM-DD.html
#
# ВАЖНО: это анализ рыночных параметров, а не полноценная оценка кредитного риска.
# Скрипт пока не проверяет отчётность, рейтинг, дефолты, оферты и новости эмитента.

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "Полное наименование",
    "Код ценной бумаги",
    "Нужна квалификация?",
    "Цена, %",
    "Объем сделок с 15 дней, шт.",
    "Доходность",
    "Дюрация, месяцев",
}


@dataclass(frozen=True)
class AnalysisResult:
    score: int
    recommendation: str
    recommendation_class: str
    risk_level: str
    positive_factors: list[str]
    risk_factors: list[str]
    explanation: str


def number(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def normalize_bool_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def requires_qualification(value: Any) -> bool:
    text = normalize_bool_text(value)
    if not text:
        return False
    negative_markers = ("нет", "не требуется", "false", "0", "обычный")
    return not any(marker in text for marker in negative_markers)


def score_yield(yield_value: float) -> tuple[int, str, str | None]:
    if yield_value < 15:
        return 14, "Доходность умеренная", None
    if yield_value <= 22:
        return 30, "Доходность находится в рабочем диапазоне 15–22%", None
    if yield_value <= 27:
        return 23, "Доходность выше средней", "Повышенная доходность требует проверки эмитента"
    if yield_value <= 32:
        return 14, "Высокая потенциальная доходность", "Высокая доходность может означать повышенный кредитный риск"
    return 4, "Очень высокая потенциальная доходность", "Доходность выше 32% — сильный сигнал риска"


def score_price(price: float) -> tuple[int, str, str | None]:
    if 90 <= price <= 105:
        return 15, "Цена близка к номиналу", None
    if 80 <= price < 90:
        return 12, "Цена ниже номинала", None
    if 105 < price <= 110:
        return 11, "Цена немного выше номинала", None
    if 70 <= price < 80:
        return 7, "Заметный дисконт к номиналу", "Низкая цена может быть следствием ухудшения оценки эмитента"
    return 6, "Цена существенно отличается от номинала", "Нужно отдельно проверить причины текущей цены"


def score_duration(duration: float) -> tuple[int, str, str | None]:
    if duration <= 6:
        return 15, "Короткая дюрация снижает чувствительность к ставке", None
    if duration <= 12:
        return 14, "Умеренная дюрация", None
    if duration <= 18:
        return 11, "Средняя дюрация", None
    if duration <= 30:
        return 8, "Повышенная процентная чувствительность", "Цена сильнее реагирует на изменение ключевой ставки"
    return 4, "Длинная дюрация", "Высокая чувствительность цены к изменению ставок"


def score_volume(volume: float) -> tuple[int, str, str | None]:
    if volume >= 500_000:
        return 30, "Очень высокая ликвидность за 15 дней", None
    if volume >= 200_000:
        return 26, "Высокая ликвидность за 15 дней", None
    if volume >= 100_000:
        return 21, "Хорошая ликвидность за 15 дней", None
    if volume >= 60_000:
        return 16, "Минимально приемлемая ликвидность", "Перед покупкой нужно проверить текущий стакан и спред"
    return 8, "Низкая ликвидность", "Может быть трудно купить или продать бумагу по справедливой цене"


def analyze_row(row: pd.Series) -> AnalysisResult:
    yield_value = float(row["Доходность"])
    price = float(row["Цена, %"])
    duration = float(row["Дюрация, месяцев"])
    volume = float(row["Объем сделок с 15 дней, шт."])
    qualification = requires_qualification(row["Нужна квалификация?"])

    positive: list[str] = []
    risks: list[str] = []

    score = 0
    for points, good, risk in (
        score_yield(yield_value),
        score_price(price),
        score_duration(duration),
        score_volume(volume),
    ):
        score += points
        positive.append(good)
        if risk:
            risks.append(risk)

    if qualification:
        score += 2
        risks.append("Бумага предназначена для квалифицированных инвесторов")
    else:
        score += 10
        positive.append("Доступна неквалифицированному инвестору")

    score = max(0, min(100, round(score)))

    if score >= 82 and not any("сильный сигнал" in item for item in risks):
        recommendation = "Рассматривать в первую очередь"
        recommendation_class = "buy"
    elif score >= 68:
        recommendation = "Рассматривать"
        recommendation_class = "consider"
    elif score >= 52:
        recommendation = "Требуется углублённая проверка"
        recommendation_class = "check"
    else:
        recommendation = "Не покупать без ручного анализа"
        recommendation_class = "avoid"

    if yield_value > 32 or price < 75 or volume < 60_000:
        risk_level = "Высокий"
    elif risks:
        risk_level = "Повышенный"
    else:
        risk_level = "Умеренный"

    explanation = (
        f"Оценка {score}/100 рассчитана по доходности, цене, дюрации, "
        "ликвидности и доступности бумаги. Кредитоспособность эмитента "
        "этой версией скрипта не проверяется."
    )

    return AnalysisResult(
        score=score,
        recommendation=recommendation,
        recommendation_class=recommendation_class,
        risk_level=risk_level,
        positive_factors=positive,
        risk_factors=risks,
        explanation=explanation,
    )


def find_latest_search_file(directory: Path) -> Path:
    candidates = [
        path
        for path in directory.glob("bond_search_*.xlsx")
        if not path.name.startswith("~$") and "analysis" not in path.name
    ]
    if not candidates:
        raise FileNotFoundError(
            "Не найден файл bond_search_YYYY-MM-DD.xlsx. Сначала запустите скрипт №1."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_search_results(input_path: Path) -> pd.DataFrame:
    df = pd.read_excel(input_path, sheet_name="Результаты поиска")
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(
            "Во входном Excel отсутствуют обязательные колонки: " + ", ".join(sorted(missing))
        )

    numeric_columns = [
        "Цена, %",
        "Объем сделок с 15 дней, шт.",
        "Доходность",
        "Дюрация, месяцев",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=numeric_columns).copy()
    if df.empty:
        raise ValueError("Во входном файле нет строк с корректными числовыми данными.")
    return df


def build_analysis(df: pd.DataFrame) -> pd.DataFrame:
    results = [analyze_row(row) for _, row in df.iterrows()]
    output = df[[
        "Полное наименование",
        "Код ценной бумаги",
        "Нужна квалификация?",
        "Цена, %",
        "Объем сделок с 15 дней, шт.",
        "Доходность",
        "Дюрация, месяцев",
    ]].copy()

    output["Оценка, 0-100"] = [result.score for result in results]
    output["Рекомендация"] = [result.recommendation for result in results]
    output["Уровень риска"] = [result.risk_level for result in results]
    output["Положительные факторы"] = ["; ".join(result.positive_factors) for result in results]
    output["Риски и ограничения"] = [
        "; ".join(result.risk_factors) if result.risk_factors else "Явные сигналы не обнаружены"
        for result in results
    ]
    output["Пояснение"] = [result.explanation for result in results]
    output["_class"] = [result.recommendation_class for result in results]
    return output.sort_values(
        by=["Оценка, 0-100", "Доходность", "Объем сделок с 15 дней, шт."],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def write_excel(df: pd.DataFrame, output_path: Path, input_path: Path) -> None:
    export_df = df.drop(columns=["_class"])
    methodology = pd.DataFrame(
        {
            "Раздел": [
                "Назначение",
                "Доходность",
                "Цена",
                "Дюрация",
                "Ликвидность",
                "Квалификация",
                "Ограничение",
                "Исходный файл",
            ],
            "Описание": [
                "Предварительное ранжирование уже отобранных облигаций.",
                "До 30 баллов. Очень высокая доходность уменьшает оценку из-за возможного риска.",
                "До 15 баллов. Наибольший балл у цены около номинала.",
                "До 15 баллов. Короткая дюрация получает больше баллов.",
                "До 30 баллов по объёму торгов за последние 15 дней.",
                "До 10 баллов. Бумаги без требования квалификации получают больше баллов.",
                "Рейтинг, отчётность, оферты, дефолты и новости пока не проверяются.",
                input_path.name,
            ],
        }
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name="Анализ", index=False)
        methodology.to_excel(writer, sheet_name="Методика", index=False)

        workbook = writer.book
        analysis_sheet = workbook["Анализ"]
        analysis_sheet.freeze_panes = "A2"
        analysis_sheet.auto_filter.ref = analysis_sheet.dimensions
        for column_cells in analysis_sheet.columns:
            max_length = min(
                70,
                max(len(str(cell.value or "")) for cell in column_cells) + 2,
            )
            analysis_sheet.column_dimensions[column_cells[0].column_letter].width = max_length

        methodology_sheet = workbook["Методика"]
        methodology_sheet.column_dimensions["A"].width = 22
        methodology_sheet.column_dimensions["B"].width = 110


def html_list(items: list[str], empty_text: str) -> str:
    if not items:
        return f"<li>{html.escape(empty_text)}</li>"
    return "".join(f"<li>{html.escape(item)}</li>" for item in items)


def write_html(df: pd.DataFrame, output_path: Path, input_path: Path) -> None:
    generated_at = datetime.now().strftime("%d.%m.%Y в %H:%M:%S")
    counts = df["Рекомендация"].value_counts().to_dict()
    avg_score = float(df["Оценка, 0-100"].mean())

    cards: list[str] = []
    for _, row in df.iterrows():
        result = analyze_row(row)
        secid = html.escape(str(row["Код ценной бумаги"]))
        name = html.escape(str(row["Полное наименование"]))
        moex_url = f"https://www.moex.com/ru/issue.aspx?board=TQCB&code={secid}"
        cards.append(
            f"""
            <article class="bond-card" data-score="{result.score}" data-class="{result.recommendation_class}">
              <div class="card-head">
                <div>
                  <h3>{name}</h3>
                  <a href="{moex_url}" target="_blank" rel="noopener">{secid} ↗</a>
                </div>
                <div class="score">{result.score}<small>/100</small></div>
              </div>
              <div class="badges">
                <span class="badge {result.recommendation_class}">{html.escape(result.recommendation)}</span>
                <span class="badge neutral">Риск: {html.escape(result.risk_level)}</span>
              </div>
              <div class="metrics">
                <div><span>Доходность</span><strong>{number(row['Доходность'])}%</strong></div>
                <div><span>Цена</span><strong>{number(row['Цена, %'])}%</strong></div>
                <div><span>Дюрация</span><strong>{number(row['Дюрация, месяцев'], 1)} мес.</strong></div>
                <div><span>Объём 15 дней</span><strong>{number(row['Объем сделок с 15 дней, шт.'], 0)}</strong></div>
              </div>
              <div class="factors">
                <div><h4>Что выглядит хорошо</h4><ul>{html_list(result.positive_factors, 'Нет данных')}</ul></div>
                <div><h4>Что проверить</h4><ul>{html_list(result.risk_factors, 'Явные сигналы не обнаружены')}</ul></div>
              </div>
            </article>
            """
        )

    document = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Предварительный анализ облигаций</title>
  <style>
    :root {{ --bg:#f4f6f8; --card:#fff; --text:#182230; --muted:#667085; --line:#e4e7ec; --blue:#175cd3; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; font-family:Arial,sans-serif; background:var(--bg); color:var(--text); }}
    .container {{ max-width:1300px; margin:auto; padding:28px; }} h1 {{ margin:0 0 8px; }} .subtitle {{ color:var(--muted); margin-bottom:22px; }}
    .notice {{ background:#fff4e5; border:1px solid #fedf89; padding:14px 16px; border-radius:12px; line-height:1.5; margin-bottom:18px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }}
    .summary div {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px; }}
    .summary span {{ display:block; color:var(--muted); font-size:13px; margin-bottom:7px; }} .summary strong {{ font-size:25px; }}
    .filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:18px 0; }} button {{ border:1px solid var(--line); background:#fff; padding:9px 13px; border-radius:999px; cursor:pointer; }} button.active {{ background:#182230; color:#fff; }}
    .bond-card {{ background:var(--card); border:1px solid var(--line); border-radius:15px; padding:20px; margin-bottom:14px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
    .card-head {{ display:flex; justify-content:space-between; gap:20px; }} h3 {{ margin:0 0 6px; }} a {{ color:var(--blue); text-decoration:none; }}
    .score {{ font-size:29px; font-weight:700; white-space:nowrap; }} .score small {{ font-size:13px; color:var(--muted); }}
    .badges {{ display:flex; gap:8px; flex-wrap:wrap; margin:15px 0; }} .badge {{ padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; }}
    .buy {{ background:#ecfdf3; color:#027a48; }} .consider {{ background:#eff8ff; color:#175cd3; }} .check {{ background:#fffaeb; color:#b54708; }} .avoid {{ background:#fef3f2; color:#b42318; }} .neutral {{ background:#f2f4f7; color:#475467; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }} .metrics div {{ background:#f9fafb; border-radius:10px; padding:12px; }} .metrics span {{ display:block; color:var(--muted); font-size:12px; margin-bottom:5px; }}
    .factors {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-top:14px; }} .factors h4 {{ margin:0 0 7px; }} ul {{ margin:0; padding-left:20px; line-height:1.5; }}
    .footer {{ color:var(--muted); font-size:12px; margin-top:20px; }}
    @media(max-width:800px) {{ .summary,.metrics {{ grid-template-columns:repeat(2,1fr); }} .factors {{ grid-template-columns:1fr; }} .container {{ padding:16px; }} }}
  </style>
</head>
<body>
<main class="container">
  <h1>Предварительный анализ облигаций</h1>
  <div class="subtitle">Сформирован {generated_at} из файла {html.escape(input_path.name)}</div>
  <div class="notice"><strong>Важно:</strong> это только первый аналитический слой. Он ранжирует бумаги по цене, доходности, дюрации и ликвидности. Перед покупкой необходимо отдельно проверить кредитный рейтинг, финансовую отчётность, оферты, амортизацию, дефолты и новости эмитента.</div>
  <section class="summary">
    <div><span>Проанализировано</span><strong>{len(df)}</strong></div>
    <div><span>Средняя оценка</span><strong>{number(avg_score, 1)}</strong></div>
    <div><span>В первую очередь</span><strong>{counts.get('Рассматривать в первую очередь', 0)}</strong></div>
    <div><span>Нужна проверка / отказ</span><strong>{counts.get('Требуется углублённая проверка', 0) + counts.get('Не покупать без ручного анализа', 0)}</strong></div>
  </section>
  <div class="filters">
    <button class="active" data-filter="all">Все</button>
    <button data-filter="buy">В первую очередь</button>
    <button data-filter="consider">Рассматривать</button>
    <button data-filter="check">Проверить</button>
    <button data-filter="avoid">Не покупать</button>
  </div>
  <section id="cards">{''.join(cards)}</section>
  <div class="footer">Баллы не являются инвестиционной рекомендацией и не гарантируют выплату купонов или номинала.</div>
</main>
<script>
  document.querySelectorAll('button[data-filter]').forEach(button => {{
    button.addEventListener('click', () => {{
      document.querySelectorAll('button[data-filter]').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      const filter = button.dataset.filter;
      document.querySelectorAll('.bond-card').forEach(card => {{
        card.style.display = filter === 'all' || card.dataset.class === filter ? '' : 'none';
      }});
    }});
  }});
</script>
</body>
</html>"""
    output_path.write_text(document, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Предварительный анализ результатов скрипта №1")
    parser.add_argument("--input", type=Path, help="Путь к bond_search_YYYY-MM-DD.xlsx")
    parser.add_argument("--no-pause", action="store_true", help="Не ждать Enter перед выходом")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_path = args.input or find_latest_search_file(Path.cwd())
        print(f"📂 Исходный файл: {input_path}")
        source_df = load_search_results(input_path)
        print(f"🔎 Облигаций для анализа: {len(source_df)}")

        analysis_df = build_analysis(source_df)
        report_date = datetime.now().strftime("%Y-%m-%d")
        excel_path = Path(f"bond_analysis_{report_date}.xlsx")
        html_path = Path(f"bond_analysis_{report_date}.html")

        write_excel(analysis_df, excel_path, input_path)
        write_html(analysis_df, html_path, input_path)

        print(f"✅ Excel-отчёт: {excel_path}")
        print(f"🌐 HTML-отчёт: {html_path}")
        print("\n⚠️ Это предварительный анализ рыночных параметров, а не проверка надёжности эмитента.")
        return 0
    except Exception as error:
        print(f"❌ Ошибка: {error}")
        return 1
    finally:
        if not getattr(args, "no_pause", False) and sys.stdin.isatty():
            input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    raise SystemExit(main())
