from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IssuerCreditModel:
    key: str
    label: str
    methodology: str
    specialist_data_label: str | None


CORPORATE = IssuerCreditModel(
    "corporate",
    "Корпоративный",
    "Корпоративная модель: рейтинг + РСБУ/МСФО-показатели + рыночный/глубокий скоринг",
    None,
)
BANK = IssuerCreditModel(
    "bank",
    "Банк",
    "Банковская модель: рейтинг + обязательные нормативы формы 0409135 Банка России + рыночный/глубокий скоринг; корпоративные Debt/EBITDA не применяются",
    "Специализированные банковские показатели ЦБ РФ",
)
REGION = IssuerCreditModel(
    "region",
    "Регион / муниципалитет",
    "Региональная модель: рейтинг + рыночный/глубокий скоринг; корпоративная EBITDA не применяется",
    "Бюджет и долговая нагрузка региона",
)
STRUCTURED = IssuerCreditModel(
    "structured_finance",
    "Секьюритизация / СФО",
    "Структурная модель: рейтинг транша + рыночный/глубокий скоринг; корпоративная отчётность эмитента не применяется",
    "Структура сделки и кредитное усиление транша",
)


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def classify_issuer(*values: Any) -> IssuerCreditModel:
    text = " | ".join(_norm(value) for value in values if _norm(value))

    structured_markers = (
        "сфо ", "сфо_", "секьюрит", "ипотечный агент", "класс а", "класс б",
        "тб-", "совкомсекьюр", "фабрика пк", "сплит финанс",
    )
    if any(marker in text for marker in structured_markers):
        return STRUCTURED

    region_markers = (
        "область", "край ", "республика ", "минфин ", "адм. г.", "администрация г.",
        "муниципаль", "городской округ",
    )
    if any(marker in text for marker in region_markers):
        return REGION

    bank_exclusions = ("лизинг", "капитал", "секьюр")
    bank_markers = (
        "банк ", 'банк"', "банк)", "сбербанк", "газпромбанк", "россельхозбанк",
        "промсвязьбанк", "псб ", "вэб.рф", "мсп банк", "авто финанс банк",
        "межд.банк", "международный банк",
    )
    if any(marker in text for marker in bank_markers) and not any(
        marker in text for marker in bank_exclusions
    ):
        return BANK

    return CORPORATE
