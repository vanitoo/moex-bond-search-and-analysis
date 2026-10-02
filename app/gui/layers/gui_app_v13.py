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
from portfolio_allocator import allocate_budget
from portfolio_impact import infer_issuer, risk_level, safe_float
from portfolio_plan import apply_allocation_plan
from portfolio_store import list_portfolios, load_portfolio, save_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def _position_value(position: dict, bond: dict) -> float:
    quantity = safe_float(position.get("quantity"))
    face = safe_float(base.deep_get(bond, "market.face_value")) or 1000.0
    price = safe_float(base.deep_get(bond, "market.price"))
    if quantity and price:
        return quantity * face * price / 100.0
    return safe_float(position.get("invested")) or 0.0


def render_portfolio_charts(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("Структура портфеля")
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Нет виртуальных портфелей для построения графиков.")
        return

    name = st.selectbox("Портфель для графиков", list(portfolios), key="portfolio_charts_name_v13")
    portfolio = load_portfolio(PORTFOLIO_DIR, name)
    master = base.load_master(run_dir)
    by_secid = {str(item.get("secid")): item for item in master.get("bonds", []) if item.get("secid")}

    rows = []
    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or "")
        if not secid:
            continue
        bond = by_secid.get(secid, {})
        value = _position_value(position, bond)
        if value <= 0:
            continue
        rating = position.get("rating") or base.deep_get(bond, "credit.rating") or "Нет рейтинга"
        maturity = base.deep_get(bond, "market.maturity_date") or position.get("maturity_date")
        year = "Неизвестно"
        if maturity:
            text = str(maturity)
            if len(text) >= 4 and text[:4].isdigit():
                year = text[:4]
        rows.append({
            "SECID": secid,
            "Название": position.get("name") or bond.get("name") or secid,
            "Эмитент": position.get("issuer") or infer_issuer(bond, position) or "Не определён",
            "Риск": risk_level(bond, position) or "unknown",
            "Рейтинг": str(rating),
            "Год погашения": year,
            "Стоимость": value,
        })

    if not rows:
        st.info("В портфеле пока нет позиций с оценимой стоимостью.")
        return

    frame = pd.DataFrame(rows)
    total = float(frame["Стоимость"].sum())
    frame["Доля, %"] = frame["Стоимость"] / total * 100.0 if total else 0.0

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**По выпускам**")
        st.bar_chart(frame.groupby("Название")["Стоимость"].sum().sort_values(ascending=False))
    with col2:
        st.markdown("**По эмитентам**")
        st.bar_chart(frame.groupby("Эмитент")["Стоимость"].sum().sort_values(ascending=False))

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**По уровню риска**")
        st.bar_chart(frame.groupby("Риск")["Стоимость"].sum().sort_values(ascending=False))
    with col4:
        st.markdown("**Доли позиций, %**")
        st.bar_chart(frame.groupby("Название")["Доля, %"].sum().sort_values(ascending=False))

    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**По кредитным рейтингам**")
        st.bar_chart(frame.groupby("Рейтинг")["Стоимость"].sum().sort_values(ascending=False))
    with col6:
        st.markdown("**Лестница погашений по годам**")
        maturity = frame.groupby("Год погашения")["Стоимость"].sum()
        known = maturity.drop(labels=["Неизвестно"], errors="ignore")
        unknown = maturity.get("Неизвестно", 0.0)
        try:
            known = known.sort_index(key=lambda idx: idx.astype(int))
        except Exception:
            known = known.sort_index()
        if unknown:
            known.loc["Неизвестно"] = unknown
        st.bar_chart(known)

    with st.expander("Таблица структуры портфеля"):
        st.dataframe(frame.sort_values("Стоимость", ascending=False), width="stretch", hide_index=True)


def render_buy_plan(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("План покупки")
    st.caption("Отметьте бумаги, нажмите «Автораспределение», проверьте количества и затем добавьте покупки в виртуальный портфель.")

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
    portfolio_name = c1.selectbox("Портфель", list(portfolios), key="buy_plan_portfolio_v13")
    budget = c2.number_input("Сумма, ₽", min_value=1000.0, value=50000.0, step=5000.0, key="buy_plan_budget_v13")
    use_all = c3.checkbox("Все кандидаты", value=not bool(shortlist), key="buy_plan_all_v13")
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
        key="buy_plan_selector_v13",
    )
    selected = edited.loc[edited["Выбрать"] == True, "SECID"].astype(str).tolist() if not edited.empty else []

    l1, l2 = st.columns(2)
    max_position = l1.slider("Максимум одного выпуска после покупки, %", 5, 30, 20, 1, key="buy_plan_pos_limit_v13")
    max_issuer = l2.slider("Максимум одного эмитента после покупки, %", 10, 40, 25, 1, key="buy_plan_issuer_limit_v13")

    if st.button("Автораспределение", type="primary", key="buy_plan_allocate_v13"):
        portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)
        result = allocate_budget(
            portfolio,
            by_secid,
            selected,
            float(budget),
            max_position_percent=float(max_position),
            max_issuer_percent=float(max_issuer),
        )
        st.session_state["buy_plan_result_v13"] = result
        st.session_state["buy_plan_portfolio_name_v13"] = portfolio_name

    result = st.session_state.get("buy_plan_result_v13")
    if not result:
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Бюджет", f"{result['budget']:,.0f} ₽".replace(",", " "))
    m2.metric("К покупке", f"{result['invested']:,.0f} ₽".replace(",", " "))
    m3.metric("Резерв", f"{result['reserve']:,.0f} ₽".replace(",", " "))

    if not result.get("lines"):
        st.warning("Нет бумаг, прошедших ограничения.")
        return

    plan_df = pd.DataFrame([{
        "SECID": line["secid"],
        "Название": line["name"],
        "Купить, шт.": line["quantity"],
        "Цена 1 шт., ₽": line["unit_cost"],
        "Сумма, ₽": line["amount"],
        "Доля новых денег, %": line["share_percent"],
        "Почему": line["reason"],
    } for line in result["lines"]])
    st.dataframe(plan_df, width="stretch", hide_index=True)

    target_portfolio = st.session_state.get("buy_plan_portfolio_name_v13", portfolio_name)
    if st.button(f"Добавить план в портфель «{target_portfolio}»", key="buy_plan_apply_v13"):
        portfolio = load_portfolio(PORTFOLIO_DIR, target_portfolio)
        updated = apply_allocation_plan(portfolio, result["lines"], by_secid)
        save_portfolio(PORTFOLIO_DIR, updated)
        st.success(f"Покупки добавлены в виртуальный портфель «{target_portfolio}».")
        st.session_state.pop("buy_plan_result_v13", None)
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
        render_portfolio_charts(run_dir)
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
    st.caption("Сканер → анализ → рекомендации → план покупки → портфель → мониторинг → автопилот.")
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
