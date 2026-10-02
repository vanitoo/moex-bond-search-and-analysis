from __future__ import annotations

from pathlib import Path

import streamlit as st

import gui_app_v2 as base
import gui_app_v4 as v4
import gui_app_v6 as v6
import gui_app_v7 as v7
import gui_app_v8 as v8
import gui_app_v9 as v9


TAB_NAMES = ["Сегодня", "Обзор", "Облигации", "Кандидаты", "Портфель", "Рекомендации", "Модули и причины", "Запуск / обновление"]


def _empty_today() -> None:
    st.subheader("Сегодня")
    st.info("Анализ на сегодня ещё не запускался. Перейдите во вкладку «Запуск / обновление», чтобы создать его.")
    st.caption("Архивные анализы остаются доступны в списке «Анализ» слева.")


def _not_ready(title: str) -> None:
    st.subheader(title)
    st.info("Для этой вкладки нужен анализ. Запустите сегодняшний pipeline во вкладке «Запуск / обновление» или выберите архивный анализ слева.")


def _render_new_analysis_tabs(config: dict) -> None:
    tabs = st.tabs(TAB_NAMES)
    with tabs[0]:
        _empty_today()
    for index, title in enumerate(TAB_NAMES[1:7], start=1):
        with tabs[index]:
            _not_ready(title)
    with tabs[7]:
        st.subheader("Запуск / обновление")
        st.caption("Создаст папку сегодняшнего дня и запустит включённые модули. После завершения все вкладки заполнятся результатами.")
        base.render_start_today(config)


def _render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    tabs = st.tabs(TAB_NAMES)
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
    st.caption("Сканер → анализ → кандидаты → портфель → рекомендации → мониторинг → автопилот.")
    config = base.config_editor()
    dirs = base.run_dirs()
    choices = ["➕ Новый анализ на сегодня"] + [path.name for path in dirs]
    default = choices.index(base.TODAY_RUN.name) if base.TODAY_RUN.name in choices else 0
    selected = st.sidebar.selectbox("Анализ", choices, index=default)

    if selected == "➕ Новый анализ на сегодня":
        st.sidebar.info("Сегодняшний анализ ещё не создан")
        _render_new_analysis_tabs(config)
        return

    run_dir = base.PROJECT_ROOT / selected
    is_today = run_dir.name == base.TODAY_RUN.name
    st.sidebar.success("Текущий день: модули можно обновлять") if is_today else st.sidebar.info("Архив: только просмотр")
    _render_existing_tabs(run_dir, config, is_today)


if __name__ == "__main__":
    main()
