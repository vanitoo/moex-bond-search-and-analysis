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
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "app" / "core"
SRC = ROOT / "src"
for _path in (str(CORE), str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from moex_bond_search_and_analysis.ratings import enrich_issuer_identifiers
from moex_bond_search_and_analysis.financials import (
    DEFAULT_CACHE_DAYS,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_WORKERS,
)
from moex_bond_search_and_analysis.issuer_credit_model import classify_issuer
from moex_bond_search_and_analysis.cbr_banks import (
    BANK_COLUMNS,
    DEFAULT_BANK_CACHE_DAYS,
    DEFAULT_BANK_DELAY_SECONDS,
)
from credit_engine import (
    CreditResult,
    RATING_ORDER,
    RATING_POINTS,
    best_match,
    calculate_metrics,
    evaluate,
    fmt,
    normalize,
    normalize_rating,
    parse_date,
    ratio,
    rating_direction,
    row_match_score,
    safe_float,
)
from credit_report import list_html, write_excel, write_html
from credit_sources import (
    BankRefreshOptions,
    FinancialRefreshOptions,
    classify_population,
    refresh_bank_metrics,
    refresh_financials,
    refresh_ratings,
)


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
        ratings = refresh_ratings(
            ratings,
            ratings_path,
            enabled=not args.no_fetch_ratings,
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

        population = classify_population(deep, ratings)

        financials = refresh_financials(
            financials,
            financials_path,
            args.data_dir,
            population,
            enabled=not args.no_fetch_financials,
            options=FinancialRefreshOptions(
                cache_days=args.financial_cache_days,
                workers=args.financial_workers,
                delay_seconds=args.financial_delay_seconds,
                retries=args.financial_retries,
            ),
        )

        bank_metrics_path = args.data_dir / "issuer_bank_metrics.xlsx"
        bank_metrics_table = (
            load_optional_table(bank_metrics_path, BANK_COLUMNS)
            if bank_metrics_path.exists()
            else pd.DataFrame(columns=BANK_COLUMNS)
        )
        bank_metrics_table = refresh_bank_metrics(
            bank_metrics_table,
            bank_metrics_path,
            args.data_dir,
            population,
            enabled=not args.no_fetch_bank_metrics,
            options=BankRefreshOptions(
                cache_days=args.bank_cache_days,
                delay_seconds=args.bank_delay_seconds,
            ),
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
