from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import base
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
    st.caption("Единая оперативная сводка: купить / докупить / держать / проверить / сократить / продать, длительность сигнала и изменения с прошлого снимка.")
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте виртуальный портфель.")
        return
    name = st.selectbox("Портфель", list(portfolios), key="today_portfolio")
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
            "Сигнал впервые": item.get("signal_first_seen") or "—",
            "Сигнал, дней": item.get("signal_days") or 0,
            "Динамика": item.get("signal_trend") or "—",
            "Причина": item.get("reason"),
        } for item in actions]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    changes = payload.get("changes", [])
    st.markdown("### Изменения с прошлого снимка")
    if not changes:
        st.success("Изменений действий и значимых изменений тренда с прошлого снимка нет.")
    else:
        st.dataframe(pd.DataFrame([{
            "SECID": item.get("secid"),
            "Название": item.get("name"),
            "Было": item.get("from"),
            "Стало": item.get("to"),
            "Динамика": item.get("signal_trend") or "—",
            "Сигнал, дней": item.get("signal_days") or 0,
            "Причина": item.get("reason"),
        } for item in changes]), width="stretch", hide_index=True)
