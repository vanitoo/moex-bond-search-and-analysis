from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.credit_engine import fmt


def write_excel(df: pd.DataFrame, output: Path, source: Path) -> None:
    methodology = pd.DataFrame({
        "Блок": [
            "Назначение", "Корпоративная модель", "Банковская модель",
            "Региональная модель", "Секьюритизация / СФО", "Жёсткие стопы", "Исходный файл",
        ],
        "Описание": [
            "Третий слой: методика выбирается по типу эмитента, чтобы не применять корпоративный Debt/EBITDA там, где он неприменим.",
            "30% второй слой + до 30 баллов рейтинг + до 30 баллов корпоративные финансы + до 10 баллов полнота.",
            "При наличии формы 0409135: 30% второй слой + до 30 баллов рейтинг + до 30 баллов за Н1.0/Н1.1/Н1.2/Н2/Н3/Н4 + до 10 баллов полнота; при отсутствии формы используется осторожный rating-only fallback.",
            "55% второй слой + 35% нормализованный рейтинг + до 10% полнота; до подключения бюджета/госдолга уверенность не выше средней.",
            "55% второй слой + 35% нормализованный рейтинг + до 10% полнота; до подключения структуры транша уверенность не выше средней.",
            "Стоп второго слоя и рейтинги CCC/CC/C/D автоматически запрещают покупку.",
            source.name,
        ],
    })
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.drop(columns=["_class"]).to_excel(writer, sheet_name="Кредитный анализ", index=False)
        methodology.to_excel(writer, sheet_name="Методика", index=False)
        type_stats = (
            df.groupby(["Тип эмитента", "Ключ модели"], dropna=False)
            .agg(
                Выпусков=("Код ценной бумаги", "count"),
                Средний_кредитный_балл=("Итоговый кредитный балл", "mean"),
                Средняя_полнота=("Полнота данных", "mean"),
            )
            .reset_index()
        )
        type_stats.to_excel(writer, sheet_name="Типы эмитентов", index=False)
        sheet = writer.book["Кредитный анализ"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cells in sheet.columns:
            sheet.column_dimensions[cells[0].column_letter].width = min(
                70,
                max(len(str(c.value or "")) for c in cells) + 2,
            )


def list_html(value: Any, css: str = "") -> str:
    items = [
        item.strip()
        for item in str(value or "").split(";")
        if item.strip() and item.strip() != "—"
    ]
    if not items:
        return "<div class='muted'>Нет данных</div>"
    return (
        f"<ul class='{css}'>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in items)
        + "</ul>"
    )


def write_html(df: pd.DataFrame, output: Path, source: Path) -> None:
    cards: list[str] = []
    for _, row in df.iterrows():
        css = row.get("_class", "wait")
        secid = html.escape(str(row["Код ценной бумаги"]))
        if str(row.get("Ключ модели") or "") == "bank":
            metric_grid = f"""
            <div><b>Н1.0</b><span>{fmt(row.get('Н1.0'))}%</span></div>
            <div><b>Н1.1 / Н1.2</b><span>{fmt(row.get('Н1.1'))}% / {fmt(row.get('Н1.2'))}%</span></div>
            <div><b>Н2</b><span>{fmt(row.get('Н2'))}%</span></div>
            <div><b>Н3</b><span>{fmt(row.get('Н3'))}%</span></div>
            <div><b>Н4</b><span>{fmt(row.get('Н4'))}%</span></div>
            """
        else:
            metric_grid = f"""
            <div><b>Чистый долг/EBITDA</b><span>{fmt(row['Чистый долг/EBITDA'])}</span></div>
            <div><b>Покрытие процентов</b><span>{fmt(row['Покрытие процентов'])}</span></div>
            <div><b>Текущая ликвидность</b><span>{fmt(row['Текущая ликвидность'])}</span></div>
            """

        cards.append(f"""
        <article class="bond {css}" data-class="{css}">
          <div class="head"><div><h2>{html.escape(str(row['Полное наименование']))}</h2><a href="https://www.moex.com/ru/issue.aspx?board=TQCB&code={secid}" target="_blank">{secid}</a></div><div class="score">{int(row['Итоговый кредитный балл'])}/100</div></div>
          <div class="decision">{html.escape(str(row['Финальное решение']))} · риск: {html.escape(str(row['Уровень риска']))} · доля: {html.escape(str(row['Максимальная доля']))}</div>
          <div class="muted">{html.escape(str(row['Тип эмитента']))} · {html.escape(str(row['Методика кредитного анализа']))}</div>
          <div class="grid">
            <div><b>Рейтинг</b><span>{html.escape(str(row['Рейтинг'] or '—'))} · {html.escape(str(row['Агентство'] or '—'))}</span></div>
            {metric_grid}
            <div><b>Финансовые/секторные баллы</b><span>{int(row['Баллы финансов'])}/30</span></div>
            <div><b>Уверенность</b><span>{html.escape(str(row['Уверенность']))}</span></div>
          </div>
          <div class="cols"><section><h3>Плюсы</h3>{list_html(row['Положительные факторы'], 'good')}</section><section><h3>Риски</h3>{list_html(row['Риски'], 'bad')}</section><section><h3>Не хватает</h3>{list_html(row['Недостающие данные'])}</section></div>
        </article>""")

    counts = df["_class"].value_counts().to_dict()
    output.write_text(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Кредитный анализ облигаций</title><style>
    body{{margin:0;background:#f4f6f8;color:#17202a;font-family:Arial,sans-serif}}main{{max-width:1400px;margin:auto;padding:24px}}h1{{margin-bottom:6px}}.sub,.muted{{color:#667085}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}button{{padding:9px 13px;border:1px solid #d0d5dd;border-radius:9px;background:white;cursor:pointer}}.bond{{background:white;border:1px solid #e4e7ec;border-left:6px solid #98a2b3;border-radius:14px;padding:18px;margin:14px 0}}.bond.buy{{border-left-color:#039855}}.bond.consider{{border-left-color:#1570ef}}.bond.small{{border-left-color:#f79009}}.bond.wait{{border-left-color:#dc6803}}.bond.avoid{{border-left-color:#d92d20}}.head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:0 0 5px}}.score{{font-size:25px;font-weight:700}}.decision{{margin:14px 0;font-weight:700}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.grid div{{background:#f9fafb;padding:10px;border-radius:8px}}.grid b,.grid span{{display:block}}.grid span{{margin-top:5px}}.cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}ul{{padding-left:20px}}.good{{color:#027a48}}.bad{{color:#b42318}}a{{color:#175cd3;text-decoration:none}}@media(max-width:800px){{.grid,.cols{{grid-template-columns:1fr}}}}
    </style></head><body><main><h1>Третий слой: кредитный анализ</h1><div class="sub">Сформировано {datetime.now().strftime('%d.%m.%Y %H:%M')} · источник: {html.escape(source.name)}</div><div class="filters"><button onclick="filterCards('all')">Все ({len(df)})</button><button onclick="filterCards('buy')">К покупке ({counts.get('buy',0)})</button><button onclick="filterCards('consider')">Рассматривать ({counts.get('consider',0)})</button><button onclick="filterCards('small')">Небольшой долей ({counts.get('small',0)})</button><button onclick="filterCards('wait')">Ждать ({counts.get('wait',0)})</button><button onclick="filterCards('avoid')">Не покупать ({counts.get('avoid',0)})</button><button onclick="filterCards('missing')">Мало данных ({counts.get('missing',0)})</button></div>{''.join(cards)}<p class="muted">Отчёт не является индивидуальной инвестиционной рекомендацией. Проверяйте первоисточники, дату отчётности и методику расчёта EBITDA.</p></main><script>function filterCards(c){{document.querySelectorAll('.bond').forEach(x=>x.style.display=(c==='all'||x.dataset.class===c)?'block':'none')}}</script></body></html>""",
        encoding="utf-8",
    )
