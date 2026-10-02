# 🧾 Третий слой анализа облигаций: рейтинг и финансовое состояние эмитента
#
# Вход: последний bond_deep_analysis_YYYY-MM-DD.xlsx, созданный скриптом №6.
# Дополнительные источники (необязательные):
#   data/issuer_ratings.xlsx или .csv
#   data/issuer_financials.xlsx или .csv
#
# При первом запуске отсутствующие шаблоны создаются автоматически.
# Выход:
#   bond_credit_analysis_YYYY-MM-DD.xlsx
#   bond_credit_analysis_YYYY-MM-DD.html

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from moex_bond_search_and_analysis.ratings import (
    enrich_issuer_identifiers,
    fetch_expert_ra_ratings,
    merge_rating_rows,
)
from moex_bond_search_and_analysis.financials import (
    DEFAULT_CACHE_DAYS,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_WORKERS,
    fetch_financials_for_inns,
    merge_financial_rows,
)
from moex_bond_search_and_analysis.issuer_credit_model import (
    IssuerCreditModel,
    classify_issuer,
)
from moex_bond_search_and_analysis.cbr_banks import (
    BANK_COLUMNS,
    DEFAULT_BANK_CACHE_DAYS,
    DEFAULT_BANK_DELAY_SECONDS,
    fetch_bank_metrics_for_issuers,
)
from credit_engine import best_match, evaluate, fmt, normalize, safe_float


RATING_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Рейтинг", "Агентство",
    "Прогноз", "Дата рейтинга", "Предыдущий рейтинг", "Дата предыдущего рейтинга",
    "Источник", "Комментарий",
]

FINANCIAL_TEMPLATE_COLUMNS = [
    "Код ценной бумаги", "Эмитент", "ИНН", "Период", "Валюта",
    "Выручка", "EBITDA", "Чистая прибыль", "Операционный денежный поток",
    "Денежные средства", "Общий долг", "Краткосрочный долг",
    "Процентные расходы", "Собственный капитал", "Оборотные активы",
    "Краткосрочные обязательства", "Источник", "Комментарий",
]

REQUIRED_DEEP_COLUMNS = {
    "Полное наименование", "Код ценной бумаги", "Итоговый балл", "Решение",
    "Жёсткий стоп", "Доходность", "Риски", "Недостающие данные",
}

def find_latest_deep_file(directory: Path) -> Path:
    files = [p for p in directory.glob("bond_deep_analysis_*.xlsx") if not p.name.startswith("~$")]
    if not files:
        raise FileNotFoundError("Не найден bond_deep_analysis_YYYY-MM-DD.xlsx. Сначала запустите скрипт №6.")
    return max(files, key=lambda p: p.stat().st_mtime)


def load_deep(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Глубокий анализ")
    missing = REQUIRED_DEEP_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError("Во входном файле отсутствуют колонки: " + ", ".join(sorted(missing)))
    return df.dropna(subset=["Код ценной бумаги"]).copy()


def create_templates(data_dir: Path) -> tuple[Path, Path]:
    data_dir.mkdir(parents=True, exist_ok=True)
    ratings = data_dir / "issuer_ratings.xlsx"
    financials = data_dir / "issuer_financials.xlsx"
    if not ratings.exists() and not ratings.with_suffix(".csv").exists():
        pd.DataFrame(columns=RATING_TEMPLATE_COLUMNS).to_excel(ratings, index=False)
        print(f"Создан шаблон рейтингов: {ratings}")
    if not financials.exists() and not financials.with_suffix(".csv").exists():
        pd.DataFrame(columns=FINANCIAL_TEMPLATE_COLUMNS).to_excel(financials, index=False)
        print(f"Создан шаблон финансов: {financials}")
    return ratings, financials


def load_optional_table(xlsx_path: Path, required_columns: list[str]) -> pd.DataFrame:
    csv_path = xlsx_path.with_suffix(".csv")
    path = csv_path if csv_path.exists() else xlsx_path
    if not path.exists():
        return pd.DataFrame(columns=required_columns)
    df = pd.read_csv(path, sep=None, engine="python") if path.suffix.lower() == ".csv" else pd.read_excel(path)
    for column in required_columns:
        if column not in df.columns:
            df[column] = None
    return df


def build_analysis(
    deep: pd.DataFrame,
    ratings: pd.DataFrame,
    financials: pd.DataFrame,
    bank_metrics_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, (_, source) in enumerate(deep.iterrows(), start=1):
        name = str(source.get("Полное наименование") or "")
        secid = str(source.get("Код ценной бумаги") or "")
        print(f"[{index}/{len(deep)}] Кредитный анализ: {name} ({secid})")
        rating = best_match(source, ratings)
        fin = best_match(source, financials)
        model = classify_issuer(
            name,
            "" if rating is None else rating.get("Эмитент"),
            "" if fin is None else fin.get("Эмитент"),
        )
        bank_metrics = None
        if model.key == "bank" and bank_metrics_table is not None and not bank_metrics_table.empty:
            bank_metrics = best_match(source, bank_metrics_table)
        result = evaluate(source, rating, fin, model, bank_metrics)
        metrics = result.metrics
        used_fin = fin if model.key == "corporate" else None
        rows.append({
            "Полное наименование": name,
            "Код ценной бумаги": secid,
            "Эмитент": (
                "" if rating is None else rating.get("Эмитент")
            ) or ("" if fin is None else fin.get("Эмитент")) or "",
            "ИНН": (
                "" if rating is None else rating.get("ИНН")
            ) or ("" if fin is None else fin.get("ИНН")) or "",
            "Доходность": source.get("Доходность"),
            "Тип эмитента": model.label,
            "Ключ модели": model.key,
            "Методика кредитного анализа": model.methodology,
            "Баллы второго слоя": source.get("Итоговый балл"),
            "Решение второго слоя": source.get("Решение"),
            "Рейтинг": "" if rating is None else rating.get("Рейтинг"),
            "Агентство": "" if rating is None else rating.get("Агентство"),
            "Прогноз": "" if rating is None else rating.get("Прогноз"),
            "Дата рейтинга": "" if rating is None else rating.get("Дата рейтинга"),
            "Баллы рейтинга": result.rating_score,
            "Период отчётности": "" if used_fin is None else used_fin.get("Период"),
            "Чистый долг/EBITDA": metrics["Чистый долг/EBITDA"],
            "Долг/EBITDA": metrics["Долг/EBITDA"],
            "Покрытие процентов": metrics["Покрытие процентов"],
            "Текущая ликвидность": metrics["Текущая ликвидность"],
            "Долг/Капитал": metrics["Долг/Капитал"],
            "Маржа EBITDA": metrics["Маржа EBITDA"],
            "Маржа чистой прибыли": metrics["Маржа чистой прибыли"],
            "OCF/Долг": metrics["OCF/Долг"],
            "Н1.0": metrics.get("Н1.0"),
            "Н1.1": metrics.get("Н1.1"),
            "Н1.2": metrics.get("Н1.2"),
            "Н2": metrics.get("Н2"),
            "Н3": metrics.get("Н3"),
            "Н4": metrics.get("Н4"),
            "Баллы финансов": result.financial_score,
            "Полнота данных": result.completeness_score,
            "Штрафы": result.penalty,
            "Итоговый кредитный балл": result.final_score,
            "Финальное решение": result.recommendation,
            "Уровень риска": result.risk_level,
            "Максимальная доля": result.max_share,
            "Уверенность": result.confidence,
            "Жёсткий стоп": "ДА" if result.hard_stop else "НЕТ",
            "Положительные факторы": "; ".join(result.positives) or "—",
            "Риски": "; ".join(result.risks) or "Явные риски не обнаружены",
            "Недостающие данные": "; ".join(result.missing) or "—",
            "Источник рейтинга": "" if rating is None else rating.get("Источник"),
            "Источник финансов": "" if used_fin is None else used_fin.get("Источник"),
            "Источник банковских данных": "" if bank_metrics is None else bank_metrics.get("Источник"),
            "Дата банковских данных": "" if bank_metrics is None else bank_metrics.get("Дата отчётности"),
            "_class": result.recommendation_class,
        })
    return pd.DataFrame(rows).sort_values(
        ["Итоговый кредитный балл", "Баллы второго слоя", "Доходность"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


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
            sheet.column_dimensions[cells[0].column_letter].width = min(70, max(len(str(c.value or "")) for c in cells) + 2)


def list_html(value: Any, css: str = "") -> str:
    items = [x.strip() for x in str(value or "").split(";") if x.strip() and x.strip() != "—"]
    if not items:
        return "<div class='muted'>Нет данных</div>"
    return f"<ul class='{css}'>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>"


def write_html(df: pd.DataFrame, output: Path, source: Path) -> None:
    cards = []
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
    output.write_text(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Кредитный анализ облигаций</title><style>
    body{{margin:0;background:#f4f6f8;color:#17202a;font-family:Arial,sans-serif}}main{{max-width:1400px;margin:auto;padding:24px}}h1{{margin-bottom:6px}}.sub,.muted{{color:#667085}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}button{{padding:9px 13px;border:1px solid #d0d5dd;border-radius:9px;background:white;cursor:pointer}}.bond{{background:white;border:1px solid #e4e7ec;border-left:6px solid #98a2b3;border-radius:14px;padding:18px;margin:14px 0}}.bond.buy{{border-left-color:#039855}}.bond.consider{{border-left-color:#1570ef}}.bond.small{{border-left-color:#f79009}}.bond.wait{{border-left-color:#dc6803}}.bond.avoid{{border-left-color:#d92d20}}.head{{display:flex;justify-content:space-between;gap:20px}}h2{{margin:0 0 5px}}.score{{font-size:25px;font-weight:700}}.decision{{margin:14px 0;font-weight:700}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.grid div{{background:#f9fafb;padding:10px;border-radius:8px}}.grid b,.grid span{{display:block}}.grid span{{margin-top:5px}}.cols{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}ul{{padding-left:20px}}.good{{color:#027a48}}.bad{{color:#b42318}}a{{color:#175cd3;text-decoration:none}}@media(max-width:800px){{.grid,.cols{{grid-template-columns:1fr}}}}
    </style></head><body><main><h1>Третий слой: кредитный анализ</h1><div class="sub">Сформировано {datetime.now().strftime('%d.%m.%Y %H:%M')} · источник: {html.escape(source.name)}</div><div class="filters"><button onclick="filterCards('all')">Все ({len(df)})</button><button onclick="filterCards('buy')">К покупке ({counts.get('buy',0)})</button><button onclick="filterCards('consider')">Рассматривать ({counts.get('consider',0)})</button><button onclick="filterCards('small')">Небольшой долей ({counts.get('small',0)})</button><button onclick="filterCards('wait')">Ждать ({counts.get('wait',0)})</button><button onclick="filterCards('avoid')">Не покупать ({counts.get('avoid',0)})</button><button onclick="filterCards('missing')">Мало данных ({counts.get('missing',0)})</button></div>{''.join(cards)}<p class="muted">Отчёт не является индивидуальной инвестиционной рекомендацией. Проверяйте первоисточники, дату отчётности и методику расчёта EBITDA.</p></main><script>function filterCards(c){{document.querySelectorAll('.bond').forEach(x=>x.style.display=(c==='all'||x.dataset.class===c)?'block':'none')}}</script></body></html>""", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Третий слой анализа облигаций")
    parser.add_argument("--input", type=Path, help="Файл bond_deep_analysis_YYYY-MM-DD.xlsx")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Каталог рейтингов и финансов")
    parser.add_argument(
        "--no-fetch-ratings",
        action="store_true",
        help="Не обновлять рейтинги с официального сайта «Эксперт РА»",
    )
    parser.add_argument(
        "--no-fetch-financials",
        action="store_true",
        help="Не обновлять финансовые показатели из публичного ГИР БО ФНС",
    )
    parser.add_argument(
        "--financial-cache-days",
        type=int,
        default=DEFAULT_CACHE_DAYS,
        help="Сколько дней считать кэш финансов ГИР БО свежим",
    )
    parser.add_argument(
        "--financial-workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Параллельные запросы к ГИР БО ФНС (1–4)",
    )
    parser.add_argument(
        "--financial-delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Минимальная пауза между запросами к ГИР БО ФНС",
    )
    parser.add_argument(
        "--financial-retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Количество попыток на один запрос к ГИР БО ФНС",
    )
    parser.add_argument(
        "--no-fetch-bank-metrics",
        action="store_true",
        help="Не обновлять обязательные нормативы банков из формы 0409135 Банка России",
    )
    parser.add_argument(
        "--bank-cache-days",
        type=int,
        default=DEFAULT_BANK_CACHE_DAYS,
        help="Сколько дней считать кэш банковских нормативов ЦБ свежим",
    )
    parser.add_argument(
        "--bank-delay-seconds",
        type=float,
        default=DEFAULT_BANK_DELAY_SECONDS,
        help="Пауза между запросами по банкам к веб-сервису Банка России",
    )
    args = parser.parse_args()
    try:
        source = args.input or find_latest_deep_file(Path.cwd())
        ratings_path, financials_path = create_templates(args.data_dir)
        ratings = load_optional_table(ratings_path, RATING_TEMPLATE_COLUMNS)
        if not args.no_fetch_ratings:
            try:
                fetched_ratings = fetch_expert_ra_ratings()
                ratings = merge_rating_rows(ratings, fetched_ratings)
                ratings.to_excel(ratings_path, index=False)
                print(
                    f"Автоматически загружено рейтингов «Эксперт РА»: "
                    f"{len(fetched_ratings)}. Кэш: {ratings_path}"
                )
            except (requests.RequestException, OSError, ValueError) as exc:
                print(
                    f"Внимание: автоматическое обновление рейтингов не удалось: {exc}. "
                    "Используется существующий локальный файл."
                )
        financials = load_optional_table(financials_path, FINANCIAL_TEMPLATE_COLUMNS)
        deep = load_deep(source)
        deep, identity_failures = enrich_issuer_identifiers(deep)
        identified = len(deep) - len(identity_failures)
        print(f"ИНН эмитентов определён через MOEX ISS: {identified}/{len(deep)}")
        if identity_failures:
            print(
                "Внимание: ИНН не найден для: "
                + ", ".join(identity_failures)
            )

        if not args.no_fetch_financials:
            try:
                cache_dir = args.data_dir / "financial_cache" / "fns_bfo"
                corporate_inns: list[str] = []
                issuer_type_counts: dict[str, int] = {}
                for _, source_row in deep.iterrows():
                    matched_rating = best_match(source_row, ratings)
                    model = classify_issuer(
                        source_row.get("Полное наименование"),
                        "" if matched_rating is None else matched_rating.get("Эмитент"),
                    )
                    issuer_type_counts[model.label] = issuer_type_counts.get(model.label, 0) + 1
                    if model.key == "corporate":
                        corporate_inns.append(str(source_row.get("ИНН") or ""))

                print(
                    "Типы эмитентов перед финансовым сбором: "
                    + ", ".join(f"{key}: {value}" for key, value in sorted(issuer_type_counts.items()))
                )
                fetched_financials, financial_stats = fetch_financials_for_inns(
                    corporate_inns,
                    cache_dir=cache_dir,
                    cache_days=max(0, args.financial_cache_days),
                    workers=max(1, min(args.financial_workers, 4)),
                    delay_seconds=max(0.0, args.financial_delay_seconds),
                    retries=max(1, args.financial_retries),
                )
                financials = merge_financial_rows(financials, fetched_financials)
                financials.to_excel(financials_path, index=False)
                print(
                    "Финансы ГИР БО ФНС: "
                    f"запрошено ИНН {financial_stats.requested}, "
                    f"получено {financial_stats.fetched}, "
                    f"из кэша {financial_stats.cached}, "
                    f"нет отчётности {financial_stats.not_found}, "
                    f"ошибок {len(financial_stats.errors)}. "
                    f"Кэш: {financials_path}"
                )
                if financial_stats.errors:
                    print(
                        "Внимание: часть финансовых данных получить не удалось: "
                        + "; ".join(financial_stats.errors[:10])
                        + ("; ..." if len(financial_stats.errors) > 10 else "")
                    )
            except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
                print(
                    f"Внимание: автоматическое обновление финансов ГИР БО не удалось: {exc}. "
                    "Используется существующий локальный файл."
                )

        bank_metrics_path = args.data_dir / "issuer_bank_metrics.xlsx"
        bank_metrics_table = (
            load_optional_table(bank_metrics_path, BANK_COLUMNS)
            if bank_metrics_path.exists()
            else pd.DataFrame(columns=BANK_COLUMNS)
        )
        if not args.no_fetch_bank_metrics:
            bank_issuers: list[dict[str, str]] = []
            seen_banks: set[str] = set()
            for _, source_row in deep.iterrows():
                matched_rating = best_match(source_row, ratings)
                model = classify_issuer(
                    source_row.get("Полное наименование"),
                    "" if matched_rating is None else matched_rating.get("Эмитент"),
                )
                if model.key != "bank":
                    continue
                issuer_name = (
                    "" if matched_rating is None else str(matched_rating.get("Эмитент") or "")
                ) or str(source_row.get("Полное наименование") or "")
                inn = str(source_row.get("ИНН") or "")
                key = re.sub(r"\D", "", inn) or normalize(issuer_name)
                if key in seen_banks:
                    continue
                seen_banks.add(key)
                bank_issuers.append({"name": issuer_name, "inn": inn})
            try:
                fetched_banks, bank_stats = fetch_bank_metrics_for_issuers(
                    bank_issuers,
                    cache_dir=args.data_dir / "bank_cache" / "cbr_f135",
                    cache_days=max(0, args.bank_cache_days),
                    delay_seconds=max(0.0, args.bank_delay_seconds),
                )
                if not fetched_banks.empty:
                    bank_metrics_table = pd.concat(
                        [bank_metrics_table, fetched_banks],
                        ignore_index=True,
                    ).reindex(columns=BANK_COLUMNS)
                    bank_metrics_table["_key"] = (
                        bank_metrics_table["ИНН"].astype(str).str.replace(r"\D", "", regex=True)
                        + "|"
                        + bank_metrics_table["Эмитент"].astype(str).str.strip().str.lower()
                    )
                    bank_metrics_table = (
                        bank_metrics_table
                        .drop_duplicates("_key", keep="last")
                        .drop(columns=["_key"])
                        .reset_index(drop=True)
                    )
                    bank_metrics_table.to_excel(bank_metrics_path, index=False)
                print(
                    "Банковские нормативы ЦБ РФ: "
                    f"запрошено {bank_stats.requested}, получено {bank_stats.fetched}, "
                    f"из кэша {bank_stats.cached}, не найдено {bank_stats.not_found}, "
                    f"ошибок {len(bank_stats.errors)}. "
                    f"Кэш: {bank_metrics_path}"
                )
                if bank_stats.errors:
                    print(
                        "Внимание: часть банковских данных получить не удалось: "
                        + "; ".join(bank_stats.errors[:10])
                        + ("; ..." if len(bank_stats.errors) > 10 else "")
                    )
            except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
                print(
                    f"Внимание: обновление банковских нормативов ЦБ не удалось: {exc}. "
                    "Используется существующий локальный файл, если он есть."
                )

        result = build_analysis(deep, ratings, financials, bank_metrics_table)
        type_counts = result["Тип эмитента"].value_counts().to_dict()
        print(
            "Кредитные модели: "
            + ", ".join(f"{key}: {value}" for key, value in type_counts.items())
        )
        stamp = datetime.now().strftime("%Y-%m-%d")
        excel = Path(f"bond_credit_analysis_{stamp}.xlsx")
        report = Path(f"bond_credit_analysis_{stamp}.html")
        write_excel(result, excel, source)
        write_html(result, report, source)
        print(f"Готово: {excel}")
        print(f"Готово: {report}")
        if ratings.empty:
            print(
                f"Внимание: рейтинги отсутствуют. Проверьте сеть или заполните "
                f"{ratings_path} вручную."
            )
        if financials.empty:
            print(
                f"Внимание: финансовые данные отсутствуют. ГИР БО мог не вернуть отчётность "
                f"(например, для банков/части финансовых организаций или при ограничении доступа). "
                f"Ручной fallback: {financials_path}."
            )
        return 0
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
