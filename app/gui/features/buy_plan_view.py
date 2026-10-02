from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import base
from portfolio_allocator import allocate_budget
from portfolio_plan import apply_allocation_plan, recalculate_allocation_plan
from portfolio_shortlist import load_shortlist_secids
from portfolio_store import list_portfolios, load_portfolio, save_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def render_buy_plan(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("План покупки")
    st.caption(
        "Отметьте бумаги, выполните автораспределение, при необходимости вручную измените количество, "
        "проверьте итоговую сумму и добавьте покупки в виртуальный портфель."
    )

    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет master-данных для расчёта.")
        return
    by_secid = {str(item.get("secid")): item for item in bonds if item.get("secid")}

    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте виртуальный портфель.")
        return

    manual_shortlist = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    model_shortlist = [secid for secid in load_shortlist_secids(run_dir) if secid in by_secid]
    shortlist = manual_shortlist or model_shortlist
    candidates = shortlist or list(by_secid)

    if manual_shortlist:
        st.info(f"Источник списка: ваш сохранённый набор кандидатов · {len(manual_shortlist)} бумаг.")
    elif model_shortlist:
        st.info(
            f"Источник списка: финальный shortlist модели · {len(model_shortlist)} бумаг, "
            "по одному сильнейшему выпуску на эмитента. Можно включить «Все кандидаты» и выбрать любые бумаги вручную."
        )
    else:
        st.caption("Финальный shortlist ещё не сформирован — показаны бумаги из текущего master.")

    c1, c2, c3 = st.columns([2, 1, 1])
    portfolio_name = c1.selectbox("Портфель", list(portfolios), key="buy_plan_portfolio")
    budget = c2.number_input("Сумма, ₽", min_value=1000.0, value=50000.0, step=5000.0, key="buy_plan_budget")
    use_all = c3.checkbox("Все кандидаты", value=not bool(shortlist), key="buy_plan_all")
    if use_all:
        candidates = list(by_secid)

    rows = []
    for secid in candidates:
        bond = by_secid[secid]
        decision = str(base.deep_get(bond, "decision.status") or "")
        score = base.deep_get(bond, "decision.score")
        tier = str(base.deep_get(bond, "decision.tier") or "")
        confidence = str(base.deep_get(bond, "decision.confidence") or "")
        issuer = str(base.deep_get(bond, "credit.issuer") or "")
        issuer_type = str(base.deep_get(bond, "credit.issuer_type") or "")
        negative = str(base.deep_get(bond, "decision.negative_factors") or "")
        shortlist_reason = str(base.deep_get(bond, "decision.shortlist_reason") or "")
        default_selected = secid in shortlist if shortlist else decision.lower() not in {"не покупать", "ожидает данных"}
        rows.append({
            "Выбрать": default_selected,
            "SECID": secid,
            "Название": bond.get("name") or secid,
            "Эмитент": issuer or "—",
            "Тип эмитента": issuer_type or "—",
            "Уровень": tier or "—",
            "Уверенность": confidence or "—",
            "Решение": decision or "—",
            "Баллы": score,
            "YTM, %": base.deep_get(bond, "market.yield"),
            "Рейтинг": base.deep_get(bond, "credit.rating") or "—",
            "Факторы снижения": negative or "—",
            "Почему не shortlist": shortlist_reason or "—",
        })

    edited = st.data_editor(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        disabled=["SECID", "Название", "Эмитент", "Тип эмитента", "Уровень", "Уверенность", "Решение", "Баллы", "YTM, %", "Рейтинг", "Факторы снижения", "Почему не shortlist"],
        key="buy_plan_selector",
    )
    selected = edited.loc[edited["Выбрать"] == True, "SECID"].astype(str).tolist() if not edited.empty else []

    l1, l2 = st.columns(2)
    max_position = l1.slider("Максимум одного выпуска после покупки, %", 5, 30, 20, 1, key="buy_plan_pos_limit")
    max_issuer = l2.slider("Максимум одного эмитента после покупки, %", 10, 40, 25, 1, key="buy_plan_issuer_limit")

    if st.button("Автораспределение", type="primary", key="buy_plan_allocate"):
        portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)
        result = allocate_budget(
            portfolio,
            by_secid,
            selected,
            float(budget),
            max_position_percent=float(max_position),
            max_issuer_percent=float(max_issuer),
        )
        st.session_state["buy_plan_result"] = result
        st.session_state["buy_plan_portfolio_name"] = portfolio_name
        st.session_state.pop("buy_plan_editor", None)

    result = st.session_state.get("buy_plan_result")
    if not result:
        return
    if not result.get("lines"):
        st.warning("Нет бумаг, прошедших ограничения.")
        return

    source_lines = result["lines"]
    editor_df = pd.DataFrame([{
        "SECID": line["secid"],
        "Название": line["name"],
        "Купить, шт.": int(line["quantity"]),
        "Цена 1 шт., ₽": float(line["unit_cost"]),
        "Сумма, ₽": float(line["amount"]),
        "Доля новых денег, %": float(line["share_percent"]),
        "Почему": line["reason"],
    } for line in source_lines])

    st.markdown("**Проверьте и при необходимости измените количество**")
    edited_plan = st.data_editor(
        editor_df,
        width="stretch",
        hide_index=True,
        disabled=["SECID", "Название", "Цена 1 шт., ₽", "Сумма, ₽", "Доля новых денег, %", "Почему"],
        column_config={
            "Купить, шт.": st.column_config.NumberColumn("Купить, шт.", min_value=0, step=1, format="%d"),
        },
        key="buy_plan_editor",
    )

    quantities = {
        str(row["SECID"]): max(0, int(row["Купить, шт."] or 0))
        for _, row in edited_plan.iterrows()
    }
    manual = recalculate_allocation_plan(source_lines, quantities, float(budget))

    m1, m2, m3 = st.columns(3)
    m1.metric("Бюджет", f"{manual['budget']:,.0f} ₽".replace(",", " "))
    m2.metric("К покупке", f"{manual['invested']:,.0f} ₽".replace(",", " "))
    m3.metric("Резерв", f"{manual['reserve']:,.0f} ₽".replace(",", " "))

    if manual["over_budget"]:
        st.error("Ручной план превышает заданный бюджет. Уменьшите количество хотя бы одной облигации.")
    elif not manual["lines"]:
        st.warning("В ручном плане количество всех бумаг равно нулю.")
    else:
        preview = pd.DataFrame([{
            "SECID": line["secid"],
            "Название": line["name"],
            "Купить, шт.": line["quantity"],
            "Цена 1 шт., ₽": line["unit_cost"],
            "Итого, ₽": line["amount"],
            "Доля бюджета, %": line["share_percent"],
        } for line in manual["lines"]])
        st.caption("Итог после ручной корректировки")
        st.dataframe(preview, width="stretch", hide_index=True)
        st.caption("Ручное изменение количества может отойти от автоматических лимитов концентрации; бюджет контролируется жёстко.")

    target_portfolio = st.session_state.get("buy_plan_portfolio_name", portfolio_name)
    can_apply = bool(manual["lines"]) and not manual["over_budget"]
    if st.button(
        f"Добавить план в портфель «{target_portfolio}»",
        key="buy_plan_apply",
        disabled=not can_apply,
    ):
        portfolio = load_portfolio(PORTFOLIO_DIR, target_portfolio)
        updated = apply_allocation_plan(portfolio, manual["lines"], by_secid)
        save_portfolio(PORTFOLIO_DIR, updated)
        st.success(f"Покупки добавлены в виртуальный портфель «{target_portfolio}».")
        st.session_state.pop("buy_plan_result", None)
        st.session_state.pop("buy_plan_editor", None)
        st.rerun()
