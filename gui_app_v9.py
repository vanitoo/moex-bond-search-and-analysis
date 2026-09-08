from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import gui_app_v2 as base
import gui_app_v4 as v4
import gui_app_v6 as v6
import gui_app_v7 as v7
import gui_app_v8 as v8
from portfolio_store import list_portfolios


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"
REPORT_DIR = base.PROJECT_ROOT / "reports"
ACTION_ORDER = {
    "ПРОДАТЬ": 0,
    "СОКРАТИТЬ НА 50%": 1,
    "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ": 2,
    "ДЕРЖАТЬ": 3,
    "ДОКУПИТЬ": 4,
    "КУПИТЬ": 5,
    "ЗАМЕНИТЬ": 6,
    "НЕ ПОКУПАТЬ": 7,
    "ОЖИДАЕТ ДАННЫХ": 8,
}


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip()) or "portfolio"


def _load_today(portfolio_name: str) -> dict:
    path = REPORT_DIR / f"daily_actions_{_safe_name(portfolio_name)}_latest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def render_today(run_dir: Path) -> None:
    st.subheader("Сегодня")
    st.caption("Единая оперативная сводка: купить / докупить / держать / проверить / сократить / продать и изменения с прошлого снимка.")
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте виртуальный портфель.")
        return
    name = st.selectbox("Портфель", list(portfolios), key="today_portfolio_v9")
    payload = _load_today(name)
    if not payload:
        st.info("Для этого портфеля ещё нет daily_actions. Запустите daily_runner.py full или monitor.")
        return

    st.caption(f"Сформировано: {payload.get('created_at', '—')} · run: {payload.get('run_dir', '—')}")
    counts = payload.get("counts", {})
    cols = st.columns(6)
    for col, action in zip(cols, ["КУПИТЬ", "ДОКУПИТЬ", "ДЕРЖАТЬ", "НЕ ДОКУПАТЬ / ПРОВЕРИТЬ", "СОКРАТИТЬ НА 50%", "ПРОДАТЬ"]):
        col.metric(action, counts.get(action, 0))

    actions = list(payload.get("actions", []))
    actions.sort(key=lambda item: (ACTION_ORDER.get(str(item.get("action")), 99), -(item.get("score") or -999)))
    if actions:
        rows = [{
            "Действие": item.get("action"),
            "SECID": item.get("secid"),
            "Название": item.get("name"),
            "Баллы": item.get("score"),
            "Рейтинг": item.get("rating"),
            "Рейтинговое действие": item.get("rating_action"),
            "Прогноз": item.get("rating_forecast"),
            "Спред к ОФЗ, б.п.": item.get("ofz_spread_bp"),
            "Причина": item.get("reason"),
        } for item in actions]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    changes = payload.get("changes", [])
    st.markdown("### Изменения с прошлого снимка")
    if not changes:
        st.success("Изменений действий с прошлого снимка нет.")
    else:
        st.dataframe(pd.DataFrame([{
            "SECID": item.get("secid"),
            "Название": item.get("name"),
            "Было": item.get("from"),
            "Стало": item.get("to"),
            "Причина": item.get("reason"),
        } for item in changes]), width="stretch", hide_index=True)


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
        base.render_start_today(config)
        return

    run_dir = base.PROJECT_ROOT / selected
    is_today = run_dir.name == base.TODAY_RUN.name
    st.sidebar.success("Текущий день: модули можно обновлять") if is_today else st.sidebar.info("Архив: только просмотр")
    tabs = st.tabs(["Сегодня", "Обзор", "Облигации", "Кандидаты", "Портфель", "Рекомендации", "Модули и причины", "Запуск / обновление"])
    with tabs[0]:
        render_today(run_dir)
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


if __name__ == "__main__":
    main()
