from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import base
from portfolio_allocator import allocate_budget
from portfolio_store import list_portfolios, load_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def _money(value) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def render_allocator(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("Инвестировать в этом месяце")
    st.caption(
        "Распределяет заданную сумму между кандидатами целыми облигациями. "
        "Учитывает скоринг, риск, ликвидность, текущие позиции и концентрацию эмитента. Сделки не совершаются."
    )

    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет bonds_master.json для расчёта распределения.")
        return
    by_secid = {str(item.get("secid")): item for item in bonds if item.get("secid")}

    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте виртуальный портфель.")
        return

    shortlist = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    left, mid, right = st.columns([2, 1, 1])
    portfolio_name = left.selectbox("Портфель для распределения", list(portfolios), key="allocator_portfolio")
    budget = mid.number_input("Новые деньги, ₽", min_value=1_000.0, value=50_000.0, step=5_000.0, key="allocator_budget")
    scope = right.selectbox("Кандидаты", ["Мой shortlist", "Все подходящие из master"], key="allocator_scope")

    if scope == "Мой shortlist":
        candidates = shortlist
        if not candidates:
            st.info("Shortlist пуст. Добавьте кандидатов во вкладке «Кандидаты» или выберите все подходящие из master.")
            return
    else:
        candidates = list(by_secid)

    c1, c2 = st.columns(2)
    max_position = c1.slider("Максимум одного выпуска после покупки, %", 5, 30, 20, 1, key="allocator_position_limit")
    max_issuer = c2.slider("Максимум одного эмитента после покупки, %", 10, 40, 25, 1, key="allocator_issuer_limit")

    portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)
    try:
        result = allocate_budget(
            portfolio,
            by_secid,
            candidates,
            float(budget),
            max_position_percent=float(max_position),
            max_issuer_percent=float(max_issuer),
        )
    except Exception as exc:
        st.error(f"Не удалось рассчитать распределение: {exc}")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Бюджет", _money(result["budget"]))
    m2.metric("Предлагается вложить", _money(result["invested"]))
    m3.metric("Остаток", _money(result["reserve"]))
    m4.metric("Выпусков к покупке", len(result["lines"]))

    if result["lines"]:
        table = pd.DataFrame([{
            "Действие": line["action"],
            "SECID": line["secid"],
            "Название": line["name"],
            "Эмитент": line["issuer"],
            "Купить, шт.": line["quantity"],
            "Цена 1 шт., ₽*": line["unit_cost"],
            "Сумма, ₽": line["amount"],
            "Доля новых денег, %": line["share_percent"],
            "Баллы": line["score"],
            "Риск": line["risk"],
            "Почему": line["reason"],
        } for line in result["lines"]])
        st.dataframe(table, width="stretch", hide_index=True)
        st.caption("* Приблизительная стоимость: номинал × текущая цена/100. НКД в этом плановом распределении пока не прибавляется.")
    else:
        st.warning("Ни одна бумага не прошла ограничения для распределения этой суммы.")

    excluded = result.get("excluded", [])
    if excluded:
        with st.expander(f"Почему не куплены остальные ({len(excluded)})"):
            st.dataframe(pd.DataFrame([{
                "SECID": item.get("secid"),
                "Название": item.get("name"),
                "Причина": item.get("reason"),
            } for item in excluded]), width="stretch", hide_index=True)
