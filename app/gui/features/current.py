from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.gui.features import base
from app.gui.features import bond_journey_view
from app.gui.features import buy_plan_view
from app.gui.features import portfolio_charts_view
from app.gui.features import portfolio_view
from app.gui.features import portfolio_workspace
from app.gui.features import recommendations_view
from app.gui.features import tabs
from app.gui.features import today_view


def render_new_analysis_tabs(config: dict) -> None:
    views = st.tabs(tabs.TAB_NAMES)
    with views[0]:
        today_view.render_today(base.TODAY_RUN)
    with views[1]:
        st.info("Полный обзор рынка появится после запуска нового анализа. Портфелем можно пользоваться уже сейчас.")
    with views[2]:
        st.info("Рыночный список облигаций появится после полного скана.")
    with views[3]:
        st.info("Кандидаты модели появятся после полного скана. Свои уже купленные бумаги добавляйте во вкладке «Портфель».")
    with views[4]:
        portfolio_view.render_portfolio(base.TODAY_RUN)
        portfolio_workspace.render_manual_holding()
        portfolio_workspace.render_income_analytics()
    with views[5]:
        st.info("Рекомендации по новым покупкам появятся после полного анализа рынка.")
    with views[6]:
        st.info("Журнал модулей появится после запуска анализа.")
    with views[7]:
        base.render_start_today(config)


def render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    views = st.tabs(tabs.TAB_NAMES)
    with views[0]:
        today_view.render_today(run_dir)
    with views[1]:
        base.render_overview(run_dir)
    with views[2]:
        base.render_bonds(run_dir)
        bond_journey_view.render_bond_journey(run_dir)
    with views[3]:
        portfolio_workspace.render_model_shortlist(run_dir)
        st.markdown("---")
        recommendations_view.render_candidates(run_dir)
    with views[4]:
        portfolio_view.render_portfolio(run_dir)
        portfolio_workspace.render_manual_holding()
        portfolio_workspace.render_income_analytics()
        portfolio_charts_view.render_portfolio_charts(run_dir)
    with views[5]:
        recommendations_view.render_recommendations(run_dir)
        buy_plan_view.render_buy_plan(run_dir)
    with views[6]:
        trace = base.trace_table(run_dir)
        if trace.empty:
            st.info("Журнал пока отсутствует")
        else:
            st.dataframe(trace, width="stretch", hide_index=True)
    with views[7]:
        if is_today:
            recommendations_view.render_run_update(run_dir, config)
        else:
            st.info("Архив доступен только для просмотра")


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Сканер → анализ → shortlist → план покупки → портфель → мониторинг.")

    config = base.config_editor()
    dirs = base.run_dirs()
    choices = ["➕ Новый анализ на сегодня"] + [path.name for path in dirs]
    default = choices.index(base.TODAY_RUN.name) if base.TODAY_RUN.name in choices else 0
    selected = st.sidebar.selectbox("Анализ", choices, index=default)

    if selected == "➕ Новый анализ на сегодня":
        st.sidebar.info("Сегодняшний анализ ещё не создан")
        render_new_analysis_tabs(config)
        return

    run_dir = base.resolve_run_dir(selected)
    is_today = run_dir.name == base.TODAY_RUN.name
    if is_today:
        st.sidebar.success("Текущий день: модули можно обновлять")
    else:
        st.sidebar.info("Архив: только просмотр")
    render_existing_tabs(run_dir, config, is_today)


if __name__ == "__main__":
    main()
