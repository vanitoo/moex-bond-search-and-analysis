from __future__ import annotations

import streamlit as st

import tabs as tabs_view
import buy_plan_view as buy_plan_view
import portfolio_workspace as portfolio_workspace
import base
import portfolio_view as portfolio_view
import today_view as today_view
import selection_profiles_ui


def _render_new_analysis_tabs(config: dict) -> None:
    tabs = st.tabs(tabs_view.TAB_NAMES)
    with tabs[0]:
        today_view.render_today(base.TODAY_RUN)
    with tabs[1]:
        st.info("Полный обзор рынка появится после запуска нового анализа. Портфелем можно пользоваться уже сейчас.")
    with tabs[2]:
        st.info("Рыночный список облигаций появится после полного скана.")
    with tabs[3]:
        st.info("Кандидаты модели появятся после полного скана. Свои уже купленные бумаги добавляйте во вкладке «Портфель».")
    with tabs[4]:
        portfolio_view.render_portfolio(base.TODAY_RUN)
        portfolio_workspace.render_manual_holding()
        portfolio_workspace.render_income_analytics()
    with tabs[5]:
        st.info("Рекомендации по новым покупкам появятся после полного анализа рынка.")
    with tabs[6]:
        st.info("Журнал модулей появится после запуска анализа.")
    with tabs[7]:
        base.render_start_today(config)


def main() -> None:
    base.search_criteria_editor = selection_profiles_ui.search_criteria_editor
    buy_plan_view._render_existing_tabs = portfolio_workspace._render_existing_tabs
    tabs_view._render_new_analysis_tabs = _render_new_analysis_tabs
    buy_plan_view.main()


if __name__ == "__main__":
    main()
