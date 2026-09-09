from __future__ import annotations

import streamlit as st

import gui_app_v10 as v10
import gui_app_v14 as v14
import gui_app_v15 as v15
import gui_app_v2 as base
import gui_app_v4 as v4
import gui_app_v9 as v9
import selection_profiles_ui


def _render_new_analysis_tabs(config: dict) -> None:
    tabs = st.tabs(v10.TAB_NAMES)
    with tabs[0]:
        v9.render_today(base.TODAY_RUN)
    with tabs[1]:
        st.info("Полный обзор рынка появится после запуска нового анализа. Портфелем можно пользоваться уже сейчас.")
    with tabs[2]:
        st.info("Рыночный список облигаций появится после полного скана.")
    with tabs[3]:
        st.info("Кандидаты модели появятся после полного скана. Свои уже купленные бумаги добавляйте во вкладке «Портфель».")
    with tabs[4]:
        v4.render_portfolio(base.TODAY_RUN)
        v15.render_manual_holding()
        v15.render_income_analytics()
    with tabs[5]:
        st.info("Рекомендации по новым покупкам появятся после полного анализа рынка.")
    with tabs[6]:
        st.info("Журнал модулей появится после запуска анализа.")
    with tabs[7]:
        base.render_start_today(config)


def main() -> None:
    base.search_criteria_editor = selection_profiles_ui.search_criteria_editor
    v14._render_existing_tabs = v15._render_existing_tabs
    v10._render_new_analysis_tabs = _render_new_analysis_tabs
    v14.main()


if __name__ == "__main__":
    main()
