from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import gui_app_v2 as base
import gui_app_v4 as v4
from portfolio_recommendation import recommend_candidate
from portfolio_store import list_portfolios, load_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"
ACTION_ORDER = {"КУПИТЬ": 0, "ДОКУПИТЬ": 1, "ЗАМЕНИТЬ": 2, "НЕ ПОКУПАТЬ": 3}


def _fmt(value: Any, digits: int = 1) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):,.{digits}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _action_message(item: dict[str, Any]) -> str:
    action = item["action"]
    name = item["name"]
    if action == "ЗАМЕНИТЬ" and item.get("replacement"):
        old = item["replacement"]["name"]
        return f"{action}: {old} → {name}"
    return f"{action}: {name}"


def render_recommendations(run_dir) -> None:
    st.subheader("Купить / Докупить / Заменить / Не покупать")
    st.caption(
        "Автоматический блок поддержки решения. Он ничего не покупает и не продаёт: действие формируется "
        "по текущему bonds_master.json, выбранному виртуальному портфелю и прозрачным правилам концентрации, риска и качества данных."
    )

    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет bonds_master.json для расчёта рекомендаций.")
        return
    by_secid = {str(bond.get("secid")): bond for bond in bonds if bond.get("secid")}

    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте виртуальный портфель во вкладке «Портфель».")
        return

    col1, col2 = st.columns([2, 1])
    portfolio_name = col1.selectbox("Портфель", list(portfolios), key="rec_portfolio")
    amount = col2.number_input(
        "Сумма одной покупки, ₽",
        min_value=1_000.0,
        value=50_000.0,
        step=5_000.0,
        key="rec_amount",
    )
    portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)

    saved = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    scope = st.radio(
        "Что анализировать",
        ["Мой список кандидатов", "Все бумаги текущего master"],
        horizontal=True,
        key="rec_scope",
    )
    secids = saved if scope == "Мой список кандидатов" else list(by_secid)
    if scope == "Мой список кандидатов" and not secids:
        st.info("Список кандидатов пуст. Добавьте бумаги во вкладке «Кандидаты» или выберите анализ всего master.")
        return

    results = [recommend_candidate(portfolio, by_secid[secid], float(amount), by_secid) for secid in secids]
    results.sort(key=lambda item: (ACTION_ORDER.get(item["action"], 9), -(item.get("score") or -999)))

    counts = {action: sum(item["action"] == action for item in results) for action in ACTION_ORDER}
    a, b, c, d = st.columns(4)
    a.metric("Купить", counts["КУПИТЬ"])
    b.metric("Докупить", counts["ДОКУПИТЬ"])
    c.metric("Заменить", counts["ЗАМЕНИТЬ"])
    d.metric("Не покупать", counts["НЕ ПОКУПАТЬ"])

    table_rows = []
    for item in results:
        scenario = item["scenario"]
        replacement = item.get("replacement") or {}
        table_rows.append({
            "Действие": item["action"],
            "SECID": item["secid"],
            "Название": item["name"],
            "Баллы": item.get("score"),
            "Риск": item.get("risk") or "нет данных",
            "Уверенность": item["confidence"],
            "Доля после, %": scenario.get("candidate_share_percent"),
            "Доля эмитента, %": scenario.get("issuer_share_after_percent"),
            "YTM после, %": scenario.get("weighted_yield_after"),
            "Ликвидность": "OK" if scenario.get("liquidity_ok") is True else ("Выше лимита" if scenario.get("liquidity_ok") is False else "Нет данных"),
            "Заменить позицию": replacement.get("name"),
        })
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    options = [item["secid"] for item in results]
    selected = st.selectbox(
        "Подробное объяснение",
        options,
        format_func=lambda secid: next(_action_message(item) for item in results if item["secid"] == secid),
        key="rec_detail",
    )
    item = next(item for item in results if item["secid"] == selected)
    scenario = item["scenario"]

    with st.container(border=True):
        st.markdown(f"## {_action_message(item)}")
        st.write(
            f"Уверенность: **{item['confidence']}** · данных: **{item['data_present']}/{item['data_total']}** · "
            f"расчётная сумма: **{_fmt(item['amount'], 0)} ₽**"
        )

        if item["positives"]:
            st.success("Почему за: " + "; ".join(item["positives"]) + ".")
        if item["negatives"]:
            st.error("Почему против: " + "; ".join(item["negatives"]) + ".")
        if item["warnings"]:
            st.warning("Ограничения: " + "; ".join(item["warnings"]) + ".")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Доля выпуска после", f"{_fmt(scenario.get('candidate_share_percent'), 1)}%")
        m2.metric("Доля эмитента после", f"{_fmt(scenario.get('issuer_share_after_percent'), 1)}%")
        m3.metric("Средняя YTM после*", f"{_fmt(scenario.get('weighted_yield_after'), 2)}%")
        m4.metric("Эфф. позиций после", _fmt(scenario.get("effective_positions_after"), 2))

        replacement = item.get("replacement")
        if replacement:
            st.info(
                f"Для замены выбрана самая слабая подтверждённая позиция: **{replacement['name']}** "
                f"({replacement['secid']}), её скоринг {replacement['score']:.0f}; преимущество кандидата около "
                f"{replacement['improvement']:.0f} баллов."
            )

    st.caption(
        "* YTM портфеля считается только по позициям, для которых она известна. «Не покупать» при низкой полноте данных означает "
        "«не принимать положительное решение пока», а не обязательно отрицательную оценку эмитента."
    )


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Сканер → анализ → кандидаты → портфель → автоматическое решение → мониторинг.")
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
    tabs = st.tabs([
        "Обзор",
        "Облигации",
        "Кандидаты",
        "Портфель",
        "Рекомендации",
        "Модули и причины",
        "Запуск / обновление",
    ])
    with tabs[0]:
        base.render_overview(run_dir)
    with tabs[1]:
        base.render_bonds(run_dir)
    with tabs[2]:
        v4.render_candidates(run_dir)
    with tabs[3]:
        v4.render_portfolio(run_dir)
    with tabs[4]:
        render_recommendations(run_dir)
    with tabs[5]:
        trace = base.trace_table(run_dir)
        st.dataframe(trace, width="stretch", hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[6]:
        base.render_rerun(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


if __name__ == "__main__":
    main()
