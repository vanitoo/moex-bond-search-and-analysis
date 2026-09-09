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

    matched_before = matching_profile(settings)
    if matched_before:
        st.info(f"Текущие параметры совпадают с профилем: **{profile_label(matched_before)}**")
    else:
        st.info("Текущие параметры: **Пользовательский профиль** — один или несколько параметров изменены вручную.")

    st.markdown("**Общие критерии поиска для V1 и V2**")
    left, right = st.columns(2)
    with left:
        settings["yield_more"] = st.number_input(
            "Доходность ОТ, %", value=float(settings.get("yield_more", 15)), step=1.0,
            key=_WIDGET_KEYS["yield_more"],
        )
        settings["price_more"] = st.number_input(
            "Цена ОТ, % от номинала", value=float(settings.get("price_more", 70)), step=1.0,
            key=_WIDGET_KEYS["price_more"],
        )
        settings["duration_more"] = st.number_input(
            "Дюрация ОТ, месяцев", min_value=0.0, value=float(settings.get("duration_more", 3)), step=1.0,
            key=_WIDGET_KEYS["duration_more"],
        )
        settings["volume_more"] = st.number_input(
            "Минимальный объём каждого из 15 дней, шт.", min_value=0.0,
            value=float(settings.get("volume_more", 2000)), step=100.0,
            key=_WIDGET_KEYS["volume_more"],
        )
    with right:
        settings["yield_less"] = st.number_input(
            "Доходность ДО, %", value=float(settings.get("yield_less", 40)), step=1.0,
            key=_WIDGET_KEYS["yield_less"],
        )
        settings["price_less"] = st.number_input(
            "Цена ДО, % от номинала", value=float(settings.get("price_less", 120)), step=1.0,
            key=_WIDGET_KEYS["price_less"],
        )
        settings["duration_less"] = st.number_input(
            "Дюрация ДО, месяцев", min_value=0.0, value=float(settings.get("duration_less", 18)), step=1.0,
            key=_WIDGET_KEYS["duration_less"],
        )
        settings["bond_volume_more"] = st.number_input(
            "Совокупный объём за 15 дней, шт.", min_value=0.0,
            value=float(settings.get("bond_volume_more", 60000)), step=1000.0,
            key=_WIDGET_KEYS["bond_volume_more"],
        )
    settings["require_known_coupons"] = st.checkbox(
        "Только облигации с известными купонами до погашения",
        value=bool(settings.get("require_known_coupons", True)),
        key=_WIDGET_KEYS["require_known_coupons"],
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
    if current_profile in {"short", "medium", "long"}:
        st.caption(
            "Профиль по сроку — это фильтр кандидатов, а не характеристика качества. "
            "Свои или уже купленные бумаги мониторятся независимо от этого профиля."
        )
    elif current_profile == "wide":
        st.warning("Широкий рынок передаст больше выпусков в полный pipeline, поэтому месячный анализ займёт больше времени.")
