# ✅ Финальный движок решений по облигациям
#
# Пункт 3 дорожной карты: единые правила «Купить / Рассматривать /
# Не покупать / Недостаточно данных».
#
# Вход: последний bond_credit_analysis_YYYY-MM-DD.xlsx, созданный скриптом №7.
# Выход:
#   bond_decisions_YYYY-MM-DD.xlsx
#   bond_decisions_YYYY-MM-DD.html
#   bond_candidates_YYYY-MM-DD.json
#
# JSON содержит только бумаги с решением «Купить» и предназначен для следующего
# этапа — формирования виртуальных портфелей по стратегиям.

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "Полное наименование",
    "Код ценной бумаги",
    "Доходность",
    "Баллы второго слоя",
    "Итоговый кредитный балл",
    "Финальное решение",
    "Рейтинг",
    "Прогноз",
    "Уверенность",
    "Жёсткий стоп",
    "Риски",
    "Недостающие данные",
}

RATING_ORDER = [
    "D", "C", "CC", "CCC", "B-", "B", "B+", "BB-", "BB", "BB+",
    "BBB-", "BBB", "BBB+", "A-", "A", "A+", "AA-", "AA", "AA+", "AAA",
]

CRITICAL_RISK_MARKERS = (
    "дефолт",
    "просроч",
    "банкрот",
    "ebitda не покрывает",
    "отрицательный операционный денежный поток",
    "оборотных активов меньше",
    "крайне высокий риск",
)


@dataclass(frozen=True)
class Decision:
    decision: str
    css_class: str
    portfolio_eligible: bool
    final_score: int
    confidence: str
    max_share: str
    reasons: list[str]
    blockers: list[str]
    manual_checks: list[str]


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def safe_float(value: Any) -> float | None:
    if value is None or value == "" or pd.isna(value):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalize_rating(value: Any) -> str:
    text = str(value or "").upper().strip().replace("(RU)", "").replace("RU", "")
    text = re.sub(r"[^A-Z+\-]", "", text)
    for rating in sorted(RATING_ORDER, key=len, reverse=True):
        if rating in text:
            return rating
    return ""


def rating_at_least(current: str, minimum: str) -> bool:
    return (
        current in RATING_ORDER
        and minimum in RATING_ORDER
        and RATING_ORDER.index(current) >= RATING_ORDER.index(minimum)
    )


def is_yes(value: Any) -> bool:
    return normalize(value) in {"да", "true", "1", "yes"}


def split_items(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text == "—" or text.lower() == "nan":
        return []
    return [item.strip() for item in text.split(";") if item.strip() and item.strip() != "—"]


def find_latest_credit_file(directory: Path) -> Path:
    files = [
        path for path in directory.glob("bond_credit_analysis_*.xlsx")
        if not path.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(
            "Не найден bond_credit_analysis_YYYY-MM-DD.xlsx. "
            "Сначала запустите скрипты №5, №6 и №7."
        )
    return max(files, key=lambda path: path.stat().st_mtime)


def load_credit_analysis(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Кредитный анализ")
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError("Во входном файле отсутствуют колонки: " + ", ".join(sorted(missing)))
    return df.dropna(subset=["Код ценной бумаги"]).copy()


def metric_is_critical(row: pd.Series) -> list[str]:
    blockers: list[str] = []
    nd_ebitda = safe_float(row.get("Чистый долг/EBITDA"))
    coverage = safe_float(row.get("Покрытие процентов"))
    current = safe_float(row.get("Текущая ликвидность"))
    net_margin = safe_float(row.get("Маржа чистой прибыли"))
    ocf_debt = safe_float(row.get("OCF/Долг"))

    if nd_ebitda is not None and nd_ebitda > 6:
        blockers.append(f"Критическая долговая нагрузка: чистый долг/EBITDA {nd_ebitda:.2f}")
    if coverage is not None and coverage < 1:
        blockers.append(f"Процентные расходы не покрываются EBITDA: {coverage:.2f}")
    if current is not None and current < 0.7:
        blockers.append(f"Критически низкая текущая ликвидность: {current:.2f}")
    if net_margin is not None and net_margin < -0.10:
        blockers.append(f"Значительная отрицательная чистая маржа: {net_margin:.1%}")
    if ocf_debt is not None and ocf_debt < -0.05:
        blockers.append(f"Отрицательный операционный поток относительно долга: {ocf_debt:.2f}")
    return blockers


def make_decision(row: pd.Series) -> Decision:
    second_score = int(round(safe_float(row.get("Баллы второго слоя")) or 0))
    credit_score = int(round(safe_float(row.get("Итоговый кредитный балл")) or 0))
    rating = normalize_rating(row.get("Рейтинг"))
    forecast = normalize(row.get("Прогноз"))
    source_confidence = str(row.get("Уверенность") or "Низкая").strip()
    risks = split_items(row.get("Риски"))
    missing = split_items(row.get("Недостающие данные"))
    risks_text = normalize(" ".join(risks))

    reasons: list[str] = []
    blockers: list[str] = []
    manual_checks: list[str] = []

    if is_yes(row.get("Жёсткий стоп")):
        blockers.append("Жёсткий стоп установлен предыдущим аналитическим слоем")

    for marker in CRITICAL_RISK_MARKERS:
        if marker in risks_text:
            blockers.append(f"Критический риск: {marker}")

    if rating in {"D", "C", "CC", "CCC"}:
        blockers.append(f"Недопустимый кредитный рейтинг {rating}")

    blockers.extend(metric_is_critical(row))

    # Сначала стопы. Их нельзя компенсировать высокой доходностью или средним баллом.
    if blockers:
        return Decision(
            decision="Не покупать",
            css_class="avoid",
            portfolio_eligible=False,
            final_score=min(credit_score, 20),
            confidence=source_confidence,
            max_share="0%",
            reasons=["Сработало одно или несколько обязательных стоп-правил"],
            blockers=blockers,
            manual_checks=missing,
        )

    # Для допуска к покупке рейтинг и финансовые данные обязательны.
    missing_normalized = normalize(" ".join(missing))
    no_rating = not rating or "кредитный рейтинг" in missing_normalized
    no_financials = "финансовая отчетность" in missing_normalized
    low_confidence = normalize(source_confidence) == "низкая"

    if no_rating:
        manual_checks.append("Добавить актуальный подтверждённый кредитный рейтинг")
    if no_financials:
        manual_checks.append("Добавить последнюю финансовую отчётность эмитента")
    manual_checks.extend(item for item in missing if item not in manual_checks)

    if no_rating or no_financials or low_confidence:
        return Decision(
            decision="Недостаточно данных",
            css_class="missing",
            portfolio_eligible=False,
            final_score=min(credit_score, 59),
            confidence=source_confidence,
            max_share="0% до заполнения данных",
            reasons=["Нельзя безопасно вынести финальное решение без рейтинга и финансовых данных"],
            blockers=[],
            manual_checks=manual_checks,
        )

    if "негатив" in forecast or "развива" in forecast:
        manual_checks.append(f"Перепроверить прогноз рейтинга: {row.get('Прогноз')}")

    if second_score >= 70:
        reasons.append(f"Второй аналитический слой пройден: {second_score}/100")
    else:
        manual_checks.append(f"Второй слой ниже порога покупки: {second_score}/100")

    if credit_score >= 82:
        reasons.append(f"Кредитный анализ пройден: {credit_score}/100")
    elif credit_score >= 65:
        reasons.append(f"Кредитный балл допускает дальнейшее рассмотрение: {credit_score}/100")
    else:
        manual_checks.append(f"Кредитный балл ниже рабочего порога: {credit_score}/100")

    if rating_at_least(rating, "BBB-"):
        reasons.append(f"Рейтинг {rating} не ниже минимального уровня BBB-")
    else:
        manual_checks.append(f"Рейтинг {rating} ниже минимального уровня BBB- для автоматической покупки")

    negative_forecast = "негатив" in forecast or "развива" in forecast

    # «Купить» означает допуск в пул кандидатов, а не немедленную покупку на всю сумму.
    buy_allowed = (
        second_score >= 70
        and credit_score >= 82
        and rating_at_least(rating, "BBB-")
        and not negative_forecast
        and normalize(source_confidence) in {"средняя", "высокая"}
    )

    if buy_allowed:
        if credit_score >= 90 and rating_at_least(rating, "A-"):
            max_share = "до 7%"
        elif credit_score >= 85:
            max_share = "до 5%"
        else:
            max_share = "до 3%"
        return Decision(
            decision="Купить",
            css_class="buy",
            portfolio_eligible=True,
            final_score=credit_score,
            confidence=source_confidence,
            max_share=max_share,
            reasons=reasons,
            blockers=[],
            manual_checks=manual_checks,
        )

    # Слабый рейтинг или низкий совокупный балл — не просто «подумать», а отказ.
    if credit_score < 45 or (rating and not rating_at_least(rating, "B+")):
        blockers.append("Совокупный кредитный риск выше допустимого уровня")
        if rating:
            blockers.append(f"Кредитный рейтинг {rating}")
        return Decision(
            decision="Не покупать",
            css_class="avoid",
            portfolio_eligible=False,
            final_score=credit_score,
            confidence=source_confidence,
            max_share="0%",
            reasons=reasons,
            blockers=blockers,
            manual_checks=manual_checks,
        )

    return Decision(
        decision="Рассматривать",
        css_class="consider",
        portfolio_eligible=False,
        final_score=credit_score,
        confidence=source_confidence,
        max_share="до 1–3% после ручной проверки",
        reasons=reasons or ["Жёсткие стопы не сработали"],
        blockers=[],
        manual_checks=manual_checks or risks,
    )


def build_decisions(source: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(source.iterrows(), start=1):
        decision = make_decision(row)
        print(
            f"[{index}/{len(source)}] {row['Код ценной бумаги']}: "
            f"{decision.decision} ({decision.final_score}/100)"
        )
        rows.append({
            "Полное наименование": row.get("Полное наименование"),
            "Код ценной бумаги": row.get("Код ценной бумаги"),
            "Доходность": row.get("Доходность"),
            "Рейтинг": normalize_rating(row.get("Рейтинг")),
            "Агентство": row.get("Агентство"),
            "Прогноз": row.get("Прогноз"),
            "Баллы второго слоя": row.get("Баллы второго слоя"),
            "Кредитный балл": row.get("Итоговый кредитный балл"),
            "Финальное решение": decision.decision,
            "Допущена в виртуальный портфель": "ДА" if decision.portfolio_eligible else "НЕТ",
            "Максимальная доля": decision.max_share,
            "Уверенность": decision.confidence,
            "Причины решения": "; ".join(decision.reasons) or "—",
            "Стоп-факторы": "; ".join(decision.blockers) or "—",
            "Что проверить вручную": "; ".join(decision.manual_checks) or "—",
            "Чистый долг/EBITDA": row.get("Чистый долг/EBITDA"),
            "Покрытие процентов": row.get("Покрытие процентов"),
            "Текущая ликвидность": row.get("Текущая ликвидность"),
            "Риски предыдущего слоя": row.get("Риски"),
            "Недостающие данные": row.get("Недостающие данные"),
            "_class": decision.css_class,
        })

    order = {"Купить": 0, "Рассматривать": 1, "Недостаточно данных": 2, "Не покупать": 3}
    result = pd.DataFrame(rows)
    result["_order"] = result["Финальное решение"].map(order).fillna(9)
    return result.sort_values(
        ["_order", "Кредитный балл", "Доходность"],
        ascending=[True, False, False],
    ).drop(columns=["_order"]).reset_index(drop=True)


def write_excel(df: pd.DataFrame, output: Path, source: Path) -> None:
    candidates = df[df["Допущена в виртуальный портфель"] == "ДА"].drop(columns=["_class"])
    methodology = pd.DataFrame({
        "Правило": [
            "Порядок", "Не покупать", "Недостаточно данных", "Купить",
            "Рассматривать", "Виртуальный портфель", "Исходный файл",
        ],
        "Описание": [
            "Сначала стопы, затем полнота данных, затем минимальные пороги каждого слоя.",
            "Дефолт, банкротство, рейтинг CCC и ниже или критические финансовые метрики.",
            "Нет актуального рейтинга, финансовой отчётности или уверенность низкая.",
            "Слой №6 >= 70, кредитный балл >= 82, рейтинг >= BBB-, прогноз не негативный.",
            "Стопов нет, но один или несколько порогов покупки не выполнены.",
            "Только решение «Купить» формирует входной пул. Стратегия портфеля выберет из него часть бумаг.",
            source.name,
        ],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.drop(columns=["_class"]).to_excel(writer, sheet_name="Решения", index=False)
        candidates.to_excel(writer, sheet_name="Кандидаты в портфель", index=False)
        methodology.to_excel(writer, sheet_name="Правила", index=False)
        for sheet_name in ("Решения", "Кандидаты в портфель", "Правила"):
            sheet = writer.book[sheet_name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                width = min(70, max(len(str(cell.value or "")) for cell in cells) + 2)
                sheet.column_dimensions[cells[0].column_letter].width = width


def html_list(value: Any, css: str = "") -> str:
    items = split_items(value)
    if not items:
        return "<div class='muted'>Нет</div>"
    return f"<ul class='{css}'>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def write_html(df: pd.DataFrame, output: Path, source: Path) -> None:
    cards: list[str] = []
    for _, row in df.iterrows():
        css = str(row["_class"])
        secid = html.escape(str(row["Код ценной бумаги"]))
        cards.append(f"""
        <article class="bond {css}" data-class="{css}">
          <div class="head">
            <div><h2>{html.escape(str(row['Полное наименование']))}</h2>
            <a href="https://www.moex.com/ru/issue.aspx?board=TQCB&code={secid}" target="_blank">{secid}</a></div>
            <div class="score">{int(safe_float(row['Кредитный балл']) or 0)}/100</div>
          </div>
          <div class="decision">{html.escape(str(row['Финальное решение']))} · лимит: {html.escape(str(row['Максимальная доля']))}</div>
          <div class="grid">
            <div><b>Рейтинг</b><span>{html.escape(str(row['Рейтинг'] or '—'))}</span></div>
            <div><b>Доходность</b><span>{html.escape(str(row['Доходность']))}%</span></div>
            <div><b>Второй слой</b><span>{html.escape(str(row['Баллы второго слоя']))}/100</span></div>
            <div><b>Уверенность</b><span>{html.escape(str(row['Уверенность']))}</span></div>
            <div><b>В портфельный пул</b><span>{html.escape(str(row['Допущена в виртуальный портфель']))}</span></div>
          </div>
          <div class="cols">
            <section><h3>Почему</h3>{html_list(row['Причины решения'], 'good')}</section>
            <section><h3>Стоп-факторы</h3>{html_list(row['Стоп-факторы'], 'bad')}</section>
            <section><h3>Проверить вручную</h3>{html_list(row['Что проверить вручную'])}</section>
          </div>
        </article>""")

    counts = df["_class"].value_counts().to_dict()
    output.write_text(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>Финальные решения по облигациям</title>
    <style>
    body{{margin:0;background:#f4f6f8;color:#17202a;font-family:Arial,sans-serif}}main{{max-width:1400px;margin:auto;padding:24px}}
    .sub,.muted{{color:#667085}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}button{{padding:9px 13px;border:1px solid #d0d5dd;border-radius:9px;background:white;cursor:pointer}}
    .bond{{background:white;border:1px solid #e4e7ec;border-left:7px solid #98a2b3;border-radius:14px;padding:18px;margin:14px 0}}
    .bond.buy{{border-left-color:#039855}}.bond.consider{{border-left-color:#1570ef}}.bond.missing{{border-left-color:#f79009}}.bond.avoid{{border-left-color:#d92d20}}
    .head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:0 0 5px}}.score{{font-size:25px;font-weight:700}}.decision{{margin:14px 0;font-size:18px;font-weight:700}}
    .grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.grid div{{background:#f9fafb;padding:10px;border-radius:8px}}.grid b,.grid span{{display:block}}.grid span{{margin-top:5px}}
    .cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}ul{{padding-left:20px}}.good{{color:#067647}}.bad{{color:#b42318}}
    @media(max-width:850px){{.grid,.cols{{grid-template-columns:1fr}}.head{{flex-direction:column}}}}
    </style></head><body><main><h1>Финальные решения по облигациям</h1>
    <div class="sub">Источник: {html.escape(source.name)} · создано {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
    <p><b>«Купить» означает допуск в пул кандидатов.</b> Реальный состав и доли определит следующий скрипт виртуального портфеля.</p>
    <div class="filters">
      <button onclick="show('all')">Все ({len(df)})</button>
      <button onclick="show('buy')">Купить ({counts.get('buy',0)})</button>
      <button onclick="show('consider')">Рассматривать ({counts.get('consider',0)})</button>
      <button onclick="show('missing')">Мало данных ({counts.get('missing',0)})</button>
      <button onclick="show('avoid')">Не покупать ({counts.get('avoid',0)})</button>
    </div>{''.join(cards)}</main><script>
    function show(cls){{document.querySelectorAll('.bond').forEach(x=>x.style.display=(cls==='all'||x.dataset.class===cls)?'block':'none')}}
    </script></body></html>""", encoding="utf-8")


def write_candidates_json(df: pd.DataFrame, output: Path, source: Path) -> None:
    candidates = df[df["Допущена в виртуальный портфель"] == "ДА"]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source.name,
        "meaning": "Пул кандидатов для построения виртуальных портфелей; это не готовый портфель.",
        "candidates": [
            {
                "secid": str(row["Код ценной бумаги"]),
                "name": str(row["Полное наименование"]),
                "yield": safe_float(row["Доходность"]),
                "rating": str(row["Рейтинг"] or ""),
                "credit_score": int(safe_float(row["Кредитный балл"]) or 0),
                "max_share": str(row["Максимальная доля"]),
                "confidence": str(row["Уверенность"]),
            }
            for _, row in candidates.iterrows()
        ],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Финальные правила решений по облигациям")
    parser.add_argument("--input", type=Path, help="Файл bond_credit_analysis_YYYY-MM-DD.xlsx")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()

    try:
        input_path = args.input or find_latest_credit_file(Path.cwd())
        input_path = input_path.resolve()
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Исходный файл: {input_path}")
        source = load_credit_analysis(input_path)
        decisions = build_decisions(source)
        stamp = datetime.now().strftime("%Y-%m-%d")
        xlsx = output_dir / f"bond_decisions_{stamp}.xlsx"
        html_path = output_dir / f"bond_decisions_{stamp}.html"
        json_path = output_dir / f"bond_candidates_{stamp}.json"

        write_excel(decisions, xlsx, input_path)
        write_html(decisions, html_path, input_path)
        write_candidates_json(decisions, json_path, input_path)

        print(f"Excel: {xlsx}")
        print(f"HTML: {html_path}")
        print(f"Кандидаты для виртуального портфеля: {json_path}")
        print(f"Допущено кандидатов: {(decisions['Допущена в виртуальный портфель'] == 'ДА').sum()}")
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
