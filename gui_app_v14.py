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
import gui_app_v12 as v12
import gui_app_v13 as v13
from portfolio_allocator import allocate_budget
from portfolio_plan import apply_allocation_plan, recalculate_allocation_plan
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

    shortlist = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    candidates = shortlist or list(by_secid)

    c1, c2, c3 = st.columns([2, 1, 1])
    portfolio_name = c1.selectbox("Портфель", list(portfolios), key="buy_plan_portfolio_v14")
    budget = c2.number_input("Сумма, ₽", min_value=1000.0, value=50000.0, step=5000.0, key="buy_plan_budget_v14")
    use_all = c3.checkbox("Все кандидаты", value=not bool(shortlist), key="buy_plan_all_v14")
    if use_all:
        candidates = list(by_secid)

    rows = []
    for secid in candidates:
        bond = by_secid[secid]
        decision = str(base.deep_get(bond, "decision.status") or "")
        score = base.deep_get(bond, "decision.score")
        rows.append({
            "Выбрать": decision.lower() not in {"не покупать", "ожидает данных"},
            "SECID": secid,
            "Название": bond.get("name") or secid,
            "Решение": decision or "—",
            "Баллы": score,
            "YTM, %": base.deep_get(bond, "market.yield"),
            "Рейтинг": base.deep_get(bond, "credit.rating") or "—",
        })

    edited = st.data_editor(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        disabled=["SECID", "Название", "Решение", "Баллы", "YTM, %", "Рейтинг"],
        key="buy_plan_selector_v14",
    )
    selected = edited.loc[edited["Выбрать"] == True, "SECID"].astype(str).tolist() if not edited.empty else []

    l1, l2 = st.columns(2)
    max_position = l1.slider("Максимум одного выпуска после покупки, %", 5, 30, 20, 1, key="buy_plan_pos_limit_v14")
    max_issuer = l2.slider("Максимум одного эмитента после покупки, %", 10, 40, 25, 1, key="buy_plan_issuer_limit_v14")

    if st.button("Автораспределение", type="primary", key="buy_plan_allocate_v14"):
        portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)
        result = allocate_budget(
            portfolio,
            by_secid,
            selected,
            float(budget),
            max_position_percent=float(max_position),
            max_issuer_percent=float(max_issuer),
        )
        st.session_state["buy_plan_result_v14"] = result
        st.session_state["buy_plan_portfolio_name_v14"] = portfolio_name
        st.session_state.pop("buy_plan_editor_v14", None)

    result = st.session_state.get("buy_plan_result_v14")
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
        key="buy_plan_editor_v14",
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

    target_portfolio = st.session_state.get("buy_plan_portfolio_name_v14", portfolio_name)
    can_apply = bool(manual["lines"]) and not manual["over_budget"]
    if st.button(
        f"Добавить план в портфель «{target_portfolio}»",
        key="buy_plan_apply_v14",
        disabled=not can_apply,
    ):
        portfolio = load_portfolio(PORTFOLIO_DIR, target_portfolio)
        updated = apply_allocation_plan(portfolio, manual["lines"], by_secid)
        save_portfolio(PORTFOLIO_DIR, updated)
        st.success(f"Покупки добавлены в виртуальный портфель «{target_portfolio}».")
        st.session_state.pop("buy_plan_result_v14", None)
        st.session_state.pop("buy_plan_editor_v14", None)
        st.rerun()


def _render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    tabs = st.tabs(v10.TAB_NAMES)
    with tabs[0]:
        v9.render_today(run_dir)
    with tabs[1]:
        base.render_overview(run_dir)
    with tabs[2]:
        base.render_bonds(run_dir)
        v12.render_bond_journey(run_dir)
    with tabs[3]:
        v6.render_candidates(run_dir)
    with tabs[4]:
        v4.render_portfolio(run_dir)
        v13.render_portfolio_charts(run_dir)
    with tabs[5]:
        v6.render_recommendations(run_dir)
        render_buy_plan(run_dir)
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
    st.caption("Сканер → анализ → рекомендации → авто/ручной план покупки → портфель → мониторинг → автопилот.")
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
