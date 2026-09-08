from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import gui_app_v2 as base
from portfolio_impact import load_portfolios, simulate_purchase


_original_render_candidates = base.render_candidates


def _fmt(value: Any, digits: int = 1) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):,.{digits}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def render_portfolio_impact(run_dir) -> None:
    st.markdown("---")
    st.subheader("Что будет с портфелем после покупки")
    st.caption(
        "Сценарий не совершает сделок. Он показывает влияние покупки кандидата на доходность, "
        "концентрацию, подтверждённую долю высокого риска и диверсификацию."
    )

    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет bonds_master.json для расчёта сценария.")
        return
    by_secid = {str(bond.get("secid")): bond for bond in bonds}

    portfolio_dir = base.PROJECT_ROOT / "data" / "virtual_portfolios"
    portfolios = load_portfolios(portfolio_dir)
    if not portfolios:
        st.info(
            "В data/virtual_portfolios пока нет виртуального портфеля. "
            "Сценарий станет доступен после создания портфеля с positions[]."
        )
        return

    portfolio_name = st.selectbox("Портфель для сценария", list(portfolios), key="impact_portfolio")
    saved = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    options = saved or list(by_secid)
    candidate_secid = st.selectbox(
        "Кандидат",
        options,
        format_func=lambda secid: base.bond_label(by_secid[secid]),
        key="impact_candidate",
    )

    preset = st.radio(
        "Сумма покупки",
        [30_000, 50_000, 100_000, "Другая"],
        horizontal=True,
        key="impact_amount_preset",
        format_func=lambda value: f"{value:,.0f} ₽".replace(",", " ") if isinstance(value, int) else value,
    )
    amount = float(preset) if isinstance(preset, int) else st.number_input(
        "Своя сумма, ₽", min_value=1_000.0, value=50_000.0, step=5_000.0, key="impact_custom_amount"
    )

    scenario = simulate_purchase(portfolios[portfolio_name], by_secid[candidate_secid], amount, by_secid)

    a, b, c, d = st.columns(4)
    a.metric("Размер портфеля после", f"{_fmt(scenario['total_after'], 0)} ₽")
    a.caption(f"До покупки: {_fmt(scenario['total_before'], 0)} ₽")

    before_yield = scenario.get("weighted_yield_before")
    after_yield = scenario.get("weighted_yield_after")
    delta_yield = None if before_yield is None or after_yield is None else after_yield - before_yield
    b.metric(
        "Средняя доходность*",
        f"{_fmt(after_yield, 2)}%",
        None if delta_yield is None else f"{delta_yield:+.2f} п.п.",
    )
    b.caption(f"Покрытие доходностью: {_fmt(scenario['yield_coverage_after_percent'], 0)}% портфеля")

    c.metric(
        "Доля кандидата",
        f"{_fmt(scenario['candidate_share_percent'], 1)}%",
    )
    issuer_share = scenario.get("issuer_share_after_percent")
    c.caption(
        f"Доля эмитента: {_fmt(issuer_share, 1)}%" if issuer_share is not None
        else "Доля эмитента: нет надёжного имени эмитента"
    )

    before_eff = scenario.get("effective_positions_before") or 0.0
    after_eff = scenario.get("effective_positions_after") or 0.0
    d.metric("Эффективное число позиций", _fmt(after_eff, 2), f"{after_eff - before_eff:+.2f}")
    d.caption("1 / сумма квадратов весов; выше = равномернее")

    st.markdown("#### Риск и концентрация")
    rows = [
        {
            "Показатель": "Максимальная доля одного выпуска, %",
            "До": scenario.get("max_position_share_before_percent"),
            "После": scenario.get("max_position_share_after_percent"),
        },
        {
            "Показатель": "Подтверждённая доля высокого риска, %",
            "До": scenario.get("high_risk_share_before_percent"),
            "После": scenario.get("high_risk_share_after_percent"),
        },
        {
            "Показатель": "Покрытие оценкой риска, %",
            "До": scenario.get("risk_coverage_before_percent"),
            "После": scenario.get("risk_coverage_after_percent"),
        },
        {
            "Показатель": "Эффективное число позиций",
            "До": scenario.get("effective_positions_before"),
            "После": scenario.get("effective_positions_after"),
        },
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    max_purchase = scenario.get("max_purchase_rub")
    if max_purchase is not None:
        if scenario.get("liquidity_ok"):
            st.success(f"Ликвидность: сумма {_fmt(amount, 0)} ₽ не превышает расчётный лимит {_fmt(max_purchase, 0)} ₽.")
        else:
            st.error(f"Ликвидность: сумма {_fmt(amount, 0)} ₽ выше расчётного лимита {_fmt(max_purchase, 0)} ₽.")
    else:
        st.warning("Лимит покупки по ликвидности пока неизвестен.")

    notes = scenario.get("notes") or []
    if notes:
        st.markdown("**Что изменится:** " + "; ".join(notes) + ".")
    else:
        st.info("По доступным данным явного ухудшения концентрации или риска сценарий не показывает.")

    st.caption(
        "* Средняя доходность считается только по позициям, для которых в текущем master/портфеле известна YTM. "
        "Покрытие показано рядом, чтобы неполные данные не выглядели как точная оценка всего портфеля."
    )

    st.markdown("#### Быстрое сравнение 30 / 50 / 100 тыс. ₽")
    quick_rows = []
    for quick_amount in (30_000, 50_000, 100_000):
        item = simulate_purchase(portfolios[portfolio_name], by_secid[candidate_secid], quick_amount, by_secid)
        quick_rows.append({
            "Покупка, ₽": quick_amount,
            "Доля выпуска, %": item.get("candidate_share_percent"),
            "Доля эмитента, %": item.get("issuer_share_after_percent"),
            "Средняя YTM, %": item.get("weighted_yield_after"),
            "Высокий риск, %": item.get("high_risk_share_after_percent"),
            "Эфф. позиций": item.get("effective_positions_after"),
            "Ликвидность": "OK" if item.get("liquidity_ok") is True else ("Выше лимита" if item.get("liquidity_ok") is False else "Нет данных"),
        })
    st.dataframe(pd.DataFrame(quick_rows), use_container_width=True, hide_index=True)


def render_candidates(run_dir) -> None:
    _original_render_candidates(run_dir)
    render_portfolio_impact(run_dir)


def main() -> None:
    base.render_candidates = render_candidates
    base.main()


if __name__ == "__main__":
    main()
