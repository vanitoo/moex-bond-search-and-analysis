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
import gui_app_v11 as v11
from bond_journey import journey_rows, route_text
from portfolio_impact import infer_issuer, risk_level, safe_float
from portfolio_store import list_portfolios, load_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def render_bond_journey(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("Маршрут облигации по анализу")
    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет данных для показа маршрута облигации.")
        return

    by_secid = {str(item.get("secid")): item for item in bonds if item.get("secid")}
    selected = st.selectbox(
        "Облигация",
        sorted(by_secid, key=lambda secid: base.bond_label(by_secid[secid]).lower()),
        format_func=lambda secid: base.bond_label(by_secid[secid]),
        key="bond_journey_v12",
    )
    bond = by_secid[selected]

    a, b, c, d, e = st.columns(5)
    a.metric("Цена, %", deep := (base.deep_get(bond, "market.price") if base.deep_get(bond, "market.price") is not None else "—"))
    b.metric("YTM, %", base.deep_get(bond, "market.yield") if base.deep_get(bond, "market.yield") is not None else "—")
    c.metric("Рейтинг", base.deep_get(bond, "credit.rating") or "—")
    d.metric("Спред к ОФЗ, б.п.", base.deep_get(bond, "ofz_spread.spread_bp") if base.deep_get(bond, "ofz_spread.spread_bp") is not None else "—")
    e.metric("Решение", base.deep_get(bond, "decision.status") or "—")

    route = route_text(bond)
    if route:
        st.caption(route)

    rows = journey_rows(bond)
    frame = pd.DataFrame(rows)
    st.dataframe(frame, width="stretch", hide_index=True)


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

    name = st.selectbox("Портфель для графиков", list(portfolios), key="portfolio_charts_name_v12")
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
        rows.append({
            "SECID": secid,
            "Название": position.get("name") or bond.get("name") or secid,
            "Эмитент": position.get("issuer") or infer_issuer(bond, position) or "Не определён",
            "Риск": risk_level(bond, position) or "unknown",
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
        by_bond = frame.groupby("Название", as_index=False)["Стоимость"].sum().sort_values("Стоимость", ascending=False)
        st.bar_chart(by_bond.set_index("Название"))
    with col2:
        st.markdown("**По эмитентам**")
        by_issuer = frame.groupby("Эмитент", as_index=False)["Стоимость"].sum().sort_values("Стоимость", ascending=False)
        st.bar_chart(by_issuer.set_index("Эмитент"))

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**По уровню риска**")
        by_risk = frame.groupby("Риск", as_index=False)["Стоимость"].sum().sort_values("Стоимость", ascending=False)
        st.bar_chart(by_risk.set_index("Риск"))
    with col4:
        st.markdown("**Доли позиций, %**")
        shares = frame[["Название", "Доля, %"]].sort_values("Доля, %", ascending=False)
        st.bar_chart(shares.set_index("Название"))

    with st.expander("Таблица структуры портфеля"):
        st.dataframe(frame.sort_values("Стоимость", ascending=False), width="stretch", hide_index=True)


def _render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    tabs = st.tabs(v10.TAB_NAMES)
    with tabs[0]:
        v9.render_today(run_dir)
    with tabs[1]:
        base.render_overview(run_dir)
    with tabs[2]:
        base.render_bonds(run_dir)
        render_bond_journey(run_dir)
    with tabs[3]:
        v6.render_candidates(run_dir)
    with tabs[4]:
        v4.render_portfolio(run_dir)
        render_portfolio_charts(run_dir)
    with tabs[5]:
        v6.render_recommendations(run_dir)
        v11.render_allocator(run_dir)
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
    st.caption("Сканер → анализ → маршрут каждой бумаги → портфель → распределение → мониторинг → автопилот.")
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
