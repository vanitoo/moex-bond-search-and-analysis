from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import gui_app_v2 as base
import gui_app_v4 as v4
from portfolio_recommendation import recommend_candidate
from portfolio_store import list_portfolios, load_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"
ACTION_ORDER = {"КУПИТЬ": 0, "ДОКУПИТЬ": 1, "ЗАМЕНИТЬ": 2, "НЕ ПОКУПАТЬ": 3, "ОЖИДАЕТ ДАННЫХ": 4}


def _fmt(value: Any, digits: int = 1) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):,.{digits}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _module_progress(run_dir) -> tuple[int, int, list[str]]:
    ready = []
    missing = []
    for key, title, _ in base.MODULES:
        if base.module_state(run_dir, key)["file"] is not None:
            ready.append(key)
        else:
            missing.append(title)
    return len(ready), len(base.MODULES), missing


def _action_message(item: dict[str, Any]) -> str:
    action = item["action"]
    name = item["name"]
    if action == "ЗАМЕНИТЬ" and item.get("replacement"):
        return f"{action}: {item['replacement']['name']} → {name}"
    return f"{action}: {name}"


def render_bond_explanation(bond: dict[str, Any], run_dir) -> None:
    score = base.score_for_leader(bond)
    decision = bond.get("decision", {}).get("status") or "Решение не сформировано"
    st.markdown(f"**{base.bond_label(bond)}**")
    st.write(f"Решение: **{decision}**" + (f" · балл **{score:.0f}**" if score is not None else ""))

    ready, total, missing_modules = _module_progress(run_dir)
    events = bond.get("modules", {})
    risks: list[str] = []
    good: list[str] = []
    for module, event in events.items():
        if not isinstance(event, dict):
            continue
        status = str(event.get("status") or "")
        reason = str(event.get("reason") or "")
        if status in {"FAIL", "WARNING", "NO_DATA", "ERROR"}:
            risks.append(f"{base.LABELS.get(module, module)}: {reason}")
        elif status == "PASS" and reason and reason != "Проверка пройдена":
            good.append(f"{base.LABELS.get(module, module)}: {reason}")

    if ready < total:
        st.info(
            f"Анализ ещё не завершён: готово {ready}/{total} модулей. "
            f"Не выполнены: {', '.join(missing_modules)}."
        )
    if good:
        st.success("Сильные стороны по выполненным модулям: " + " | ".join(good[:3]))
    if risks:
        st.warning("Что проверить: " + " | ".join(risks[:4]))
    elif events:
        st.success("В выполненных для этой бумаги модулях предупреждений пока нет.")
    else:
        st.info("Для этой бумаги журнал модулей пока пуст.")


def render_candidates(run_dir) -> None:
    original = base.render_bond_explanation
    try:
        base.render_bond_explanation = lambda bond: render_bond_explanation(bond, run_dir)
        v4.render_candidates(run_dir)
    finally:
        base.render_bond_explanation = original


def render_recommendations(run_dir) -> None:
    st.subheader("Купить / Докупить / Заменить / Не покупать")
    st.caption(
        "Поддержка решения по текущему master и виртуальному портфелю. Пока аналитические модули не завершены, "
        "бумага получает статус «ОЖИДАЕТ ДАННЫХ», а не искусственное «Не покупать»."
    )

    ready, total, missing_modules = _module_progress(run_dir)
    if ready < total:
        st.warning(
            f"Сейчас готово только {ready}/{total} модулей. Полноценные рекомендации заблокированы до завершения анализа. "
            f"Осталось: {', '.join(missing_modules)}."
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
    portfolio_name = col1.selectbox("Портфель", list(portfolios), key="rec_portfolio_v6")
    amount = col2.number_input("Сумма одной покупки, ₽", min_value=1_000.0, value=50_000.0, step=5_000.0, key="rec_amount_v6")
    portfolio = load_portfolio(PORTFOLIO_DIR, portfolio_name)

    saved = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    scope = st.radio(
        "Что анализировать",
        ["Мой список кандидатов", "Все бумаги текущего master"],
        horizontal=True,
        key="rec_scope_v6",
    )
    secids = saved if scope == "Мой список кандидатов" else list(by_secid)
    if scope == "Мой список кандидатов" and not secids:
        st.info("Список кандидатов пуст. Добавьте бумаги во вкладке «Кандидаты» или выберите весь master.")
        return

    results = [recommend_candidate(portfolio, by_secid[secid], float(amount), by_secid) for secid in secids]
    results.sort(key=lambda item: (ACTION_ORDER.get(item["action"], 9), -(item.get("score") or -999)))

    counts = {action: sum(item["action"] == action for item in results) for action in ACTION_ORDER}
    cols = st.columns(5)
    cols[0].metric("Купить", counts["КУПИТЬ"])
    cols[1].metric("Докупить", counts["ДОКУПИТЬ"])
    cols[2].metric("Заменить", counts["ЗАМЕНИТЬ"])
    cols[3].metric("Не покупать", counts["НЕ ПОКУПАТЬ"])
    cols[4].metric("Ожидает данных", counts["ОЖИДАЕТ ДАННЫХ"])

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
            "Данные": f"{item['data_present']}/{item['data_total']}",
            "Уверенность": item["confidence"],
            "Доля после, %": scenario.get("candidate_share_percent"),
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
        key="rec_detail_v6",
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
            st.warning("Чего не хватает / ограничения: " + "; ".join(item["warnings"]) + ".")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Доля выпуска после", f"{_fmt(scenario.get('candidate_share_percent'), 1)}%")
        m2.metric("Доля эмитента после", f"{_fmt(scenario.get('issuer_share_after_percent'), 1)}%")
        m3.metric("Средняя YTM после*", f"{_fmt(scenario.get('weighted_yield_after'), 2)}%")
        m4.metric("Эфф. позиций после", _fmt(scenario.get("effective_positions_after"), 2))

    st.caption("* YTM портфеля считается только по позициям, для которых она известна.")


def render_run_update(run_dir, config: dict[str, Any]) -> None:
    st.subheader("Запуск / обновление")
    enabled = [key for key in base.MODULE_KEYS if config.get("modules", {}).get(key, {}).get("enabled", True)]
    remaining = [key for key in enabled if base.module_state(run_dir, key)["file"] is None]

    if remaining:
        st.warning("Не выполнены: " + " → ".join(base.LABELS[key] for key in remaining))
        refresh = st.checkbox("Принудительно обновить рейтинги при запуске", value=False, key="run_remaining_refresh")
        if st.button("▶ Запустить все оставшиеся модули", type="primary", width="stretch", key="run_remaining_all"):
            base.run_with_ui(run_dir, remaining, config, refresh)
    else:
        st.success("Все включённые модули для этого дня уже имеют результат.")

    st.markdown("### Точечный перезапуск")
    base.render_rerun(run_dir, config)


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Сканер → анализ → кандидаты → портфель → рекомендации → мониторинг.")
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
    tabs = st.tabs(["Обзор", "Облигации", "Кандидаты", "Портфель", "Рекомендации", "Модули и причины", "Запуск / обновление"])
    with tabs[0]:
        base.render_overview(run_dir)
    with tabs[1]:
        base.render_bonds(run_dir)
    with tabs[2]:
        render_candidates(run_dir)
    with tabs[3]:
        v4.render_portfolio(run_dir)
    with tabs[4]:
        render_recommendations(run_dir)
    with tabs[5]:
        trace = base.trace_table(run_dir)
        st.dataframe(trace, width="stretch", hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[6]:
        render_run_update(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


if __name__ == "__main__":
    main()
