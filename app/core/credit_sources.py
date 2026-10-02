from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from credit_engine import best_match, normalize
from moex_bond_search_and_analysis.cbr_banks import (
    BANK_COLUMNS,
    fetch_bank_metrics_for_issuers,
)
from moex_bond_search_and_analysis.financials import (
    fetch_financials_for_inns,
    merge_financial_rows,
)
from moex_bond_search_and_analysis.issuer_credit_model import classify_issuer
from moex_bond_search_and_analysis.ratings import (
    fetch_expert_ra_ratings,
    merge_rating_rows,
)


@dataclass(frozen=True)
class FinancialRefreshOptions:
    cache_days: int
    workers: int
    delay_seconds: float
    retries: int


@dataclass(frozen=True)
class BankRefreshOptions:
    cache_days: int
    delay_seconds: float


@dataclass(frozen=True)
class IssuerPopulation:
    corporate_inns: tuple[str, ...]
    bank_issuers: tuple[dict[str, str], ...]
    type_counts: dict[str, int]


def refresh_ratings(
    ratings: pd.DataFrame,
    ratings_path: Path,
    *,
    enabled: bool,
) -> pd.DataFrame:
    if not enabled:
        return ratings
    try:
        fetched = fetch_expert_ra_ratings()
        merged = merge_rating_rows(ratings, fetched)
        merged.to_excel(ratings_path, index=False)
        print(
            f"Автоматически загружено рейтингов «Эксперт РА»: "
            f"{len(fetched)}. Кэш: {ratings_path}"
        )
        return merged
    except (requests.RequestException, OSError, ValueError) as exc:
        print(
            f"Внимание: автоматическое обновление рейтингов не удалось: {exc}. "
            "Используется существующий локальный файл."
        )
        return ratings


def classify_population(deep: pd.DataFrame, ratings: pd.DataFrame) -> IssuerPopulation:
    corporate_inns: list[str] = []
    bank_issuers: list[dict[str, str]] = []
    type_counts: dict[str, int] = {}
    seen_banks: set[str] = set()

    for _, source_row in deep.iterrows():
        matched_rating = best_match(source_row, ratings)
        rating_issuer = "" if matched_rating is None else matched_rating.get("Эмитент")
        model = classify_issuer(source_row.get("Полное наименование"), rating_issuer)
        type_counts[model.label] = type_counts.get(model.label, 0) + 1

        if model.key == "corporate":
            corporate_inns.append(str(source_row.get("ИНН") or ""))
            continue

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

    return IssuerPopulation(
        corporate_inns=tuple(corporate_inns),
        bank_issuers=tuple(bank_issuers),
        type_counts=type_counts,
    )


def refresh_financials(
    existing: pd.DataFrame,
    financials_path: Path,
    data_dir: Path,
    population: IssuerPopulation,
    *,
    enabled: bool,
    options: FinancialRefreshOptions,
) -> pd.DataFrame:
    if not enabled:
        return existing

    print(
        "Типы эмитентов перед финансовым сбором: "
        + ", ".join(
            f"{key}: {value}" for key, value in sorted(population.type_counts.items())
        )
    )
    try:
        fetched, stats = fetch_financials_for_inns(
            population.corporate_inns,
            cache_dir=data_dir / "financial_cache" / "fns_bfo",
            cache_days=max(0, options.cache_days),
            workers=max(1, min(options.workers, 4)),
            delay_seconds=max(0.0, options.delay_seconds),
            retries=max(1, options.retries),
        )
        merged = merge_financial_rows(existing, fetched)
        merged.to_excel(financials_path, index=False)
        print(
            "Финансы ГИР БО ФНС: "
            f"запрошено ИНН {stats.requested}, "
            f"получено {stats.fetched}, "
            f"из кэша {stats.cached}, "
            f"нет отчётности {stats.not_found}, "
            f"ошибок {len(stats.errors)}. "
            f"Кэш: {financials_path}"
        )
        if stats.errors:
            print(
                "Внимание: часть финансовых данных получить не удалось: "
                + "; ".join(stats.errors[:10])
                + ("; ..." if len(stats.errors) > 10 else "")
            )
        return merged
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(
            f"Внимание: автоматическое обновление финансов ГИР БО не удалось: {exc}. "
            "Используется существующий локальный файл."
        )
        return existing


def refresh_bank_metrics(
    existing: pd.DataFrame,
    bank_metrics_path: Path,
    data_dir: Path,
    population: IssuerPopulation,
    *,
    enabled: bool,
    options: BankRefreshOptions,
) -> pd.DataFrame:
    if not enabled:
        return existing

    try:
        fetched, stats = fetch_bank_metrics_for_issuers(
            population.bank_issuers,
            cache_dir=data_dir / "bank_cache" / "cbr_f135",
            cache_days=max(0, options.cache_days),
            delay_seconds=max(0.0, options.delay_seconds),
        )
        merged = existing
        if not fetched.empty:
            merged = pd.concat([existing, fetched], ignore_index=True).reindex(
                columns=BANK_COLUMNS
            )
            merged["_key"] = (
                merged["ИНН"].astype(str).str.replace(r"\D", "", regex=True)
                + "|"
                + merged["Эмитент"].astype(str).str.strip().str.lower()
            )
            merged = (
                merged.drop_duplicates("_key", keep="last")
                .drop(columns=["_key"])
                .reset_index(drop=True)
            )
            merged.to_excel(bank_metrics_path, index=False)

        print(
            "Банковские нормативы ЦБ РФ: "
            f"запрошено {stats.requested}, получено {stats.fetched}, "
            f"из кэша {stats.cached}, не найдено {stats.not_found}, "
            f"ошибок {len(stats.errors)}. "
            f"Кэш: {bank_metrics_path}"
        )
        if stats.errors:
            print(
                "Внимание: часть банковских данных получить не удалось: "
                + "; ".join(stats.errors[:10])
                + ("; ..." if len(stats.errors) > 10 else "")
            )
        return merged
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(
            f"Внимание: обновление банковских нормативов ЦБ не удалось: {exc}. "
            "Используется существующий локальный файл, если он есть."
        )
        return existing
