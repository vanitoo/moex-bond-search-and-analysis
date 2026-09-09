from __future__ import annotations

from copy import deepcopy
from typing import Any


PROFILE_FIELDS = (
    "yield_more",
    "yield_less",
    "price_more",
    "price_less",
    "duration_more",
    "duration_less",
    "volume_more",
    "bond_volume_more",
    "require_known_coupons",
)

SELECTION_PROFILES: dict[str, dict[str, Any]] = {
    "strict_current": {
        "label": "Жёсткий — текущий",
        "description": (
            "Текущий строгий отбор: короткая дюрация, высокая минимальная ликвидность "
            "и только заранее известные купоны. Быстро уменьшает вселенную бумаг."
        ),
        "settings": {
            "yield_more": 15.0,
            "yield_less": 40.0,
            "price_more": 70.0,
            "price_less": 120.0,
            "duration_more": 3.0,
            "duration_less": 18.0,
            "volume_more": 2000.0,
            "bond_volume_more": 60000.0,
            "require_known_coupons": True,
        },
    },
    "soft_balanced": {
        "label": "Мягкий — сбалансированный",
        "description": (
            "Шире пропускает бумаги в полный анализ: мягче цена, доходность и ликвидность; "
            "не отбрасывает флоатеры только из-за неизвестных будущих купонов."
        ),
        "settings": {
            "yield_more": 10.0,
            "yield_less": 40.0,
            "price_more": 60.0,
            "price_less": 130.0,
            "duration_more": 2.0,
            "duration_less": 30.0,
            "volume_more": 500.0,
            "bond_volume_more": 30000.0,
            "require_known_coupons": False,
        },
    },
    "short": {
        "label": "Короткие",
        "description": (
            "Поиск преимущественно коротких облигаций с дюрацией 1–18 месяцев. "
            "Подходит для более низкой чувствительности к изменению ставок."
        ),
        "settings": {
            "yield_more": 10.0,
            "yield_less": 40.0,
            "price_more": 60.0,
            "price_less": 130.0,
            "duration_more": 1.0,
            "duration_less": 18.0,
            "volume_more": 500.0,
            "bond_volume_more": 30000.0,
            "require_known_coupons": False,
        },
    },
    "medium": {
        "label": "Средние",
        "description": (
            "Фокус на средней дюрации 12–36 месяцев. Баланс между текущим денежным потоком "
            "и чувствительностью цены к ставкам."
        ),
        "settings": {
            "yield_more": 10.0,
            "yield_less": 40.0,
            "price_more": 60.0,
            "price_less": 130.0,
            "duration_more": 12.0,
            "duration_less": 36.0,
            "volume_more": 500.0,
            "bond_volume_more": 30000.0,
            "require_known_coupons": False,
        },
    },
    "long": {
        "label": "Длинные",
        "description": (
            "Фокус на дюрации 24–84 месяца. Такие бумаги сильнее реагируют на изменение ставок; "
            "после отбора особенно важны кредитный риск и структура портфеля."
        ),
        "settings": {
            "yield_more": 10.0,
            "yield_less": 40.0,
            "price_more": 60.0,
            "price_less": 130.0,
            "duration_more": 24.0,
            "duration_less": 84.0,
            "volume_more": 500.0,
            "bond_volume_more": 30000.0,
            "require_known_coupons": False,
        },
    },
    "wide": {
        "label": "Широкий рынок",
        "description": (
            "Минимальный предварительный отсев. Больше бумаг доходит до новостей, ликвидности, "
            "кредитного анализа и финального решения; полный запуск будет тяжелее."
        ),
        "settings": {
            "yield_more": 5.0,
            "yield_less": 45.0,
            "price_more": 40.0,
            "price_less": 150.0,
            "duration_more": 1.0,
            "duration_less": 120.0,
            "volume_more": 0.0,
            "bond_volume_more": 10000.0,
            "require_known_coupons": False,
        },
    },
}


def profile_ids() -> list[str]:
    return list(SELECTION_PROFILES)


def profile_label(profile_id: str) -> str:
    profile = SELECTION_PROFILES.get(profile_id)
    return str(profile.get("label")) if profile else "Пользовательский"


def profile_description(profile_id: str) -> str:
    profile = SELECTION_PROFILES.get(profile_id)
    return str(profile.get("description")) if profile else "Параметры изменены вручную."


def apply_selection_profile(settings: dict[str, Any], profile_id: str) -> dict[str, Any]:
    if profile_id not in SELECTION_PROFILES:
        raise KeyError(f"Неизвестный профиль отбора: {profile_id}")
    result = deepcopy(settings)
    result.update(deepcopy(SELECTION_PROFILES[profile_id]["settings"]))
    result["selection_profile"] = profile_id
    return result


def matching_profile(settings: dict[str, Any]) -> str | None:
    for profile_id, profile in SELECTION_PROFILES.items():
        expected = profile["settings"]
        matched = True
        for field in PROFILE_FIELDS:
            actual = settings.get(field)
            target = expected[field]
            if isinstance(target, bool):
                if bool(actual) != target:
                    matched = False
                    break
            else:
                try:
                    if abs(float(actual) - float(target)) > 1e-9:
                        matched = False
                        break
                except (TypeError, ValueError):
                    matched = False
                    break
        if matched:
            return profile_id
    return None
