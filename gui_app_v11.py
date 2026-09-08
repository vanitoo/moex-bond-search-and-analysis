from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import gui_app_v2 as base
import gui_app_v4 as v4
import gui_app_v6 as v6
import gui_app_v7 as v7
import gui_app_v8 as v8
import gui_app_v9 as v9
import gui_app_v10 as v10
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
    portfolio_name = left.selectbox("Портфель для распределения", list(portfolios), key="allocator_portfolio_v11")
    budget = mid.number_input("Новые деньги, ₽", min_value=1_000.0, value=50_000.0, step=5_000.0, key="allocator_budget_v11")
    scope = right.selectbox("Кандидаты", ["Мой shortlist", "Все подходящие из master"], key="allocator_scope_v11")

    if scope == "Мой shortlist":
        candidates = shortlist
        if not candidates:
            st.info("Shortlist пуст. Добавьте кандидатов во вкладке «Кандидаты» или выберите все подходящие из master.")
            return
    else:
        candidates = list(by_secid)

    c1, c2 = st.columns(2)
    max_position = c1.slider("Максимум одного выпуска после покупки, %", 5, 30, 20, 1, key="allocator_position_limit_v11")
    max_issuer = c2.slider("Максимум одного эмитента после покупки, %", 10, 40, 25, 1, key="allocator_issuer_limit_v11")

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


def _render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    tabs = st.tabs(v10.TAB_NAMES)
    with tabs[0]:
        v9.render_today(run_dir)
    with tabs[1]:
        base.render_overview(run_dir)
    with tabs[2]:
        base.render_bonds(run_dir)
    with tabs[3]:
        v6.render_candidates(run_dir)
    with tabs[4]:
        v4.render_portfolio(run_dir)
    with tabs[5]:
        v6.render_recommendations(run_dir)
        render_allocator(run_dir)
    with tabs[6]:
        trace = base.trace_table(run_dir)
        st.dataframe(trace, width="stretch", hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[7]:
        v6.render_run_update(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


def main() -> None:
    base.module_state = v7.module_state
    base.run_with_ui = v8.run_with_ui
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Сканер → анализ → кандидаты → портфель → рекомендации → распределение бюджета → мониторинг → автопилот.")
    config = base.config_editor()
    dirs = base.run_dirs()
    choices = ["➕ Новый анализ на сегодня"] + [path.name for path in dirs]
    default = choices.index(base.TODAY_RUN.name) if base.TODAY_RUN.name in choices else 0
    selected = st.sidebar.selectbox("Анализ", choices, index=default)

    if selected == "➕ Новый анализ на сегодня":
        st.sidebar.info("Сегодняшний анализ ещё не создан")
        v10._render_new_analysis_tabs(config)
        return

    run_dir = base.PROJECT_ROOT / selected
    is_today = run_dir.name == base.TODAY_RUN.name
    st.sidebar.success("Текущий день: модули можно обновлять") if is_today else st.sidebar.info("Архив: только просмотр")
    _render_existing_tabs(run_dir, config, is_today)


if __name__ == "__main__":
    main()
