from __future__ import annotations

from typing import Any

import streamlit as st

from selection_profiles import (
    PROFILE_FIELDS,
    apply_selection_profile,
    matching_profile,
    profile_description,
    profile_ids,
    profile_label,
)


_WIDGET_KEYS = {
    "yield_more": "market_profile_yield_more",
    "yield_less": "market_profile_yield_less",
    "price_more": "market_profile_price_more",
    "price_less": "market_profile_price_less",
    "duration_more": "market_profile_duration_more",
    "duration_less": "market_profile_duration_less",
    "volume_more": "market_profile_volume_more",
    "bond_volume_more": "market_profile_bond_volume_more",
    "require_known_coupons": "market_profile_known_coupons",
}


def _put_profile_into_session(settings: dict[str, Any]) -> None:
    for field in PROFILE_FIELDS:
        st.session_state[_WIDGET_KEYS[field]] = settings[field]


def _number_input(label: str, field: str, default: float, step: float, min_value: float | None = None) -> float:
    key = _WIDGET_KEYS[field]
    kwargs: dict[str, Any] = {"step": step, "key": key}
    if min_value is not None:
        kwargs["min_value"] = min_value
    if key not in st.session_state:
        kwargs["value"] = float(default)
    return float(st.number_input(label, **kwargs))


def _checkbox(label: str, field: str, default: bool) -> bool:
    key = _WIDGET_KEYS[field]
    kwargs: dict[str, Any] = {"key": key}
    if key not in st.session_state:
        kwargs["value"] = bool(default)
    return bool(st.checkbox(label, **kwargs))


def search_criteria_editor(settings: dict[str, Any]) -> None:
    st.markdown("**Профиль предварительного отбора**")
    st.caption(
        "Профиль задаёт только первый фильтр рынка. Новости, кредитный риск, рейтинг, ликвидность, "
        "спред к ОФЗ и финальное решение считаются дальше отдельными модулями."
    )

    ids = profile_ids()
    stored = str(settings.get("selection_profile") or "")
    default_id = stored if stored in ids else (matching_profile(settings) or "strict_current")
    selected = st.selectbox(
        "Готовый профиль",
        ids,
        index=ids.index(default_id),
        format_func=profile_label,
        key="market_selection_profile_picker",
    )
    st.caption(profile_description(selected))

    if st.button("Применить профиль отбора", key="market_apply_selection_profile"):
        updated = apply_selection_profile(settings, selected)
        settings.clear()
        settings.update(updated)
        _put_profile_into_session(settings)
        st.success(f"Применён профиль «{profile_label(selected)}». Ниже параметры можно изменить вручную.")

    st.markdown("**Общие критерии поиска для V1 и V2**")
    left, right = st.columns(2)
    with left:
        settings["yield_more"] = _number_input(
            "Доходность ОТ, %", "yield_more", float(settings.get("yield_more", 15)), 1.0
        )
        settings["price_more"] = _number_input(
            "Цена ОТ, % от номинала", "price_more", float(settings.get("price_more", 70)), 1.0
        )
        settings["duration_more"] = _number_input(
            "Дюрация ОТ, месяцев", "duration_more", float(settings.get("duration_more", 3)), 1.0, 0.0
        )
        settings["volume_more"] = _number_input(
            "Минимальный объём каждого из 15 дней, шт.", "volume_more", float(settings.get("volume_more", 2000)), 100.0, 0.0
        )
    with right:
        settings["yield_less"] = _number_input(
            "Доходность ДО, %", "yield_less", float(settings.get("yield_less", 40)), 1.0
        )
        settings["price_less"] = _number_input(
            "Цена ДО, % от номинала", "price_less", float(settings.get("price_less", 120)), 1.0
        )
        settings["duration_less"] = _number_input(
            "Дюрация ДО, месяцев", "duration_less", float(settings.get("duration_less", 18)), 1.0, 0.0
        )
        settings["bond_volume_more"] = _number_input(
            "Совокупный объём за 15 дней, шт.", "bond_volume_more", float(settings.get("bond_volume_more", 60000)), 1000.0, 0.0
        )
    settings["require_known_coupons"] = _checkbox(
        "Только облигации с известными купонами до погашения",
        "require_known_coupons",
        bool(settings.get("require_known_coupons", True)),
    )

    errors: list[str] = []
    if settings["yield_more"] > settings["yield_less"]:
        errors.append("Доходность ОТ больше доходности ДО")
    if settings["price_more"] > settings["price_less"]:
        errors.append("Цена ОТ больше цены ДО")
    if settings["duration_more"] > settings["duration_less"]:
        errors.append("Дюрация ОТ больше дюрации ДО")
    if errors:
        st.error("; ".join(errors))

    current_profile = matching_profile(settings)
    settings["selection_profile"] = current_profile or "custom"
    if current_profile:
        st.info(f"Текущие параметры совпадают с профилем: **{profile_label(current_profile)}**")
    else:
        st.info("Текущие параметры: **Пользовательский профиль** — один или несколько параметров изменены вручную.")

    if current_profile in {"short", "medium", "long"}:
        st.caption(
            "Профиль по сроку — это фильтр кандидатов, а не характеристика качества. "
            "Свои или уже купленные бумаги мониторятся независимо от этого профиля."
        )
    elif current_profile == "wide":
        st.warning("Широкий рынок передаст больше выпусков в полный pipeline, поэтому месячный анализ займёт больше времени.")
