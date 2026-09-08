from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

import gui_app_v2 as base
from gui_app_v3 import render_portfolio_impact
from portfolio_impact import infer_issuer, safe_float
from portfolio_store import (
    create_portfolio,
    delete_portfolio,
    list_portfolios,
    load_portfolio,
    remove_position,
    save_portfolio,
    upsert_position,
)


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _bond_by_secid(run_dir) -> dict[str, dict[str, Any]]:
    master = base.load_master(run_dir)
    return {str(item.get("secid")): item for item in master.get("bonds", []) if item.get("secid")}


def _position_current_value(position: dict[str, Any], bond: dict[str, Any]) -> float | None:
    quantity = safe_float(position.get("quantity"))
    price = safe_float(base.deep_get(bond, "market.price"))
    face = safe_float(base.deep_get(bond, "market.face_value")) or 1000.0
    if quantity is None or price is None:
        return None
    return quantity * face * price / 100.0


def render_portfolio(run_dir) -> None:
    st.subheader("Портфель")
    st.caption("Создание и редактирование виртуального портфеля. Сделки не совершаются: данные сохраняются локально в data/virtual_portfolios/*.json.")
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    portfolios = list_portfolios(PORTFOLIO_DIR)

    with st.expander("Создать новый портфель", expanded=not bool(portfolios)):
        name = st.text_input("Название портфеля", placeholder="Например: Основной", key="portfolio_new_name")
        if st.button("Создать портфель", type="primary", disabled=not bool(name.strip()), key="portfolio_create"):
            try:
                create_portfolio(PORTFOLIO_DIR, name)
                st.success("Портфель создан.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Создайте первый портфель. После этого сценарии 30/50/100 тыс. ₽ во вкладке «Кандидаты» станут доступны.")
        return

    names = list(portfolios)
    selected_name = st.selectbox("Портфель", names, key="portfolio_selected")
    portfolio = load_portfolio(PORTFOLIO_DIR, selected_name)
    by_secid = _bond_by_secid(run_dir)

    positions = portfolio.get("positions", [])
    invested_total = sum(safe_float(item.get("invested")) or 0.0 for item in positions)
    current_values = [_position_current_value(item, by_secid.get(str(item.get("secid") or ""), {})) for item in positions]
    known_current = sum(value for value in current_values if value is not None)
    known_count = sum(value is not None for value in current_values)

    a, b, c = st.columns(3)
    a.metric("Позиций", len(positions))
    b.metric("Вложено", _money(invested_total))
    c.metric("Текущая оценка*", _money(known_current) if known_count else "—")
    c.caption(f"По текущему master: {known_count}/{len(positions)} позиций" if positions else "Портфель пуст")

    if positions:
        rows = []
        for item in positions:
            secid = str(item.get("secid") or "")
            bond = by_secid.get(secid, {})
            current_value = _position_current_value(item, bond)
            invested = safe_float(item.get("invested")) or 0.0
            rows.append({
                "SECID": secid,
                "Название": item.get("name") or bond.get("name") or secid,
                "Количество": item.get("quantity"),
                "Цена покупки, %": item.get("purchase_price_percent"),
                "Дата покупки": item.get("purchase_date"),
                "Вложено, ₽": invested,
                "Текущая оценка, ₽": current_value,
                "Результат, ₽": None if current_value is None else current_value - invested,
                "Эмитент": item.get("issuer") or infer_issuer(bond, item),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("### Добавить или изменить позицию")
    if not by_secid:
        st.warning("В выбранном анализе нет bonds_master.json. Можно управлять только уже сохранёнными позициями.")
    else:
        options = sorted(by_secid, key=lambda secid: base.bond_label(by_secid[secid]).lower())
        edit_secid = st.selectbox(
            "Облигация",
            options,
            format_func=lambda secid: base.bond_label(by_secid[secid]),
            key="portfolio_position_bond",
        )
        existing = next((item for item in positions if str(item.get("secid")) == edit_secid), {})
        bond = by_secid[edit_secid]
        face = safe_float(base.deep_get(bond, "market.face_value")) or 1000.0
        market_price = safe_float(base.deep_get(bond, "market.price")) or 100.0

        col1, col2, col3 = st.columns(3)
        quantity = col1.number_input(
            "Количество, шт.", min_value=1, value=max(1, int(existing.get("quantity") or 1)), step=1, key="portfolio_qty"
        )
        purchase_price = col2.number_input(
            "Цена покупки, % от номинала",
            min_value=0.01,
            value=float(existing.get("purchase_price_percent") or market_price),
            step=0.01,
            key="portfolio_purchase_price",
        )
        existing_date = existing.get("purchase_date")
        try:
            parsed_date = date.fromisoformat(str(existing_date)[:10]) if existing_date else date.today()
        except ValueError:
            parsed_date = date.today()
        purchase_date = col3.date_input("Дата покупки", value=parsed_date, key="portfolio_purchase_date")

        calculated = quantity * face * purchase_price / 100.0
        invested = st.number_input(
            "Вложено, ₽",
            min_value=0.01,
            value=float(existing.get("invested") or calculated),
            step=100.0,
            help="По умолчанию считается как количество × номинал × цена/100. Можно скорректировать вручную.",
            key="portfolio_invested",
        )
        st.caption(f"Номинал из master: {face:,.2f} ₽ · текущая цена: {market_price:.2f}%".replace(",", " "))

        left, right = st.columns(2)
        if left.button("Сохранить позицию", type="primary", use_container_width=True, key="portfolio_save_position"):
            position = {
                "secid": edit_secid,
                "name": bond.get("name") or edit_secid,
                "issuer": infer_issuer(bond),
                "quantity": int(quantity),
                "purchase_price_percent": float(purchase_price),
                "purchase_date": purchase_date.isoformat(),
                "invested": float(invested),
                "yield": base.deep_get(bond, "market.yield"),
                "rating": base.deep_get(bond, "credit.rating"),
            }
            try:
                updated = upsert_position(portfolio, position)
                save_portfolio(PORTFOLIO_DIR, updated)
                st.success("Позиция сохранена.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if existing and right.button("Удалить позицию", use_container_width=True, key="portfolio_remove_position"):
            updated = remove_position(portfolio, edit_secid)
            save_portfolio(PORTFOLIO_DIR, updated)
            st.rerun()

    st.markdown("### Управление портфелем")
    confirm_delete = st.checkbox("Подтверждаю удаление всего портфеля", key="portfolio_delete_confirm")
    if st.button("Удалить портфель", disabled=not confirm_delete, key="portfolio_delete"):
        delete_portfolio(PORTFOLIO_DIR, selected_name)
        st.rerun()

    st.caption("* Текущая оценка приблизительная: количество × номинал × текущая цена из выбранного bonds_master.json. НКД пока отдельно не учитывается.")


def _candidate_selection(run_dir, by_secid: dict[str, dict[str, Any]]) -> list[str]:
    current = [secid for secid in base.saved_candidates(run_dir) if secid in by_secid]
    st.markdown("### Мой короткий список")
    if current:
        display = pd.DataFrame([
            {
                "SECID": secid,
                "Название": by_secid[secid].get("name") or secid,
                "Доходность, %": base.deep_get(by_secid[secid], "market.yield"),
                "Цена, %": base.deep_get(by_secid[secid], "market.price"),
                "Финальный балл": base.deep_get(by_secid[secid], "decision.score"),
            }
            for secid in current
        ])
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("Список пока пуст. Добавляйте бумаги по одной — максимум 10.")

    remaining = [secid for secid in by_secid if secid not in current]
    left, right = st.columns([4, 1])
    add_secid = None
    if remaining:
        add_secid = left.selectbox(
            "Добавить кандидата",
            sorted(remaining, key=lambda secid: base.bond_label(by_secid[secid]).lower()),
            format_func=lambda secid: base.bond_label(by_secid[secid]),
            key="candidate_add_one",
        )
    if right.button("Добавить", disabled=add_secid is None or len(current) >= 10, use_container_width=True, key="candidate_add_button"):
        base.save_candidates(run_dir, current + [str(add_secid)])
        st.rerun()

    if len(current) >= 10:
        st.caption("Достигнут лимит 10 кандидатов. Удалите одну бумагу, чтобы добавить другую.")

    if current:
        remove_secid = st.selectbox(
            "Удалить из списка",
            current,
            format_func=lambda secid: base.bond_label(by_secid[secid]),
            key="candidate_remove_one",
        )
        if st.button("Удалить выбранного кандидата", key="candidate_remove_button"):
            base.save_candidates(run_dir, [secid for secid in current if secid != remove_secid])
            st.rerun()
    return current


def render_candidates(run_dir) -> None:
    st.subheader("Кандидаты к покупке")
    st.caption("Короткий список 2–10 бумаг, сравнение параметров и влияние покупки на портфель.")
    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет данных для сравнения. Сначала выполните хотя бы поиск облигаций.")
        return
    by_secid = {str(bond.get("secid")): bond for bond in bonds}
    selected = _candidate_selection(run_dir, by_secid)

    if len(selected) >= 2:
        chosen = [by_secid[secid] for secid in selected]
        available_metrics = [
            name for name, path in base.COMPARE_METRICS.items()
            if any(base.deep_get(bond, path) is not None for bond in chosen)
        ]
        default_metrics = [name for name in base.DEFAULT_COMPARE_METRICS if name in available_metrics]
        metrics = st.multiselect("Параметры сравнения", available_metrics, default=default_metrics or available_metrics[:5], key="candidate_metrics_v4")

        labels = {bond["secid"]: (bond.get("name") or bond["secid"]) for bond in chosen}
        compare_rows = []
        for metric in metrics:
            row = {"Параметр": metric}
            for bond in chosen:
                row[labels[bond["secid"]]] = base.deep_get(bond, base.COMPARE_METRICS[metric])
            compare_rows.append(row)
        st.dataframe(pd.DataFrame(compare_rows), use_container_width=True, hide_index=True)

        scored = [(bond, base.score_for_leader(bond)) for bond in chosen]
        scored = [(bond, score) for bond, score in scored if score is not None]
        if scored:
            leader, leader_score = max(scored, key=lambda pair: pair[1])
            st.info(f"По текущему скорингу лидирует **{base.bond_label(leader)}** — {leader_score:.0f} баллов.")

        chart_metrics = st.multiselect("Графики", metrics, default=metrics[: min(3, len(metrics))], key="candidate_charts_v4")
        for metric in chart_metrics:
            values = []
            for bond in chosen:
                value = base.deep_get(bond, base.COMPARE_METRICS[metric])
                try:
                    numeric = float(value) if value is not None else None
                except (TypeError, ValueError):
                    numeric = None
                if numeric is not None:
                    values.append({"Облигация": labels[bond["secid"]], metric: numeric})
            if values:
                st.markdown(f"**{metric}**")
                st.bar_chart(pd.DataFrame(values).set_index("Облигация"))

        st.markdown("### Почему такие оценки")
        for bond in chosen:
            with st.container(border=True):
                base.render_bond_explanation(bond)
    else:
        st.info("Добавьте минимум две бумаги для сравнительной таблицы.")

    render_portfolio_impact(run_dir)


def main() -> None:
    st.set_page_config(page_title="MOEX Bond Lab", page_icon="📊", layout="wide")
    st.title("📊 MOEX Bond Lab")
    st.caption("Сканер → анализ → кандидаты → портфель → мониторинг.")
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
    tabs = st.tabs(["Обзор", "Облигации", "Кандидаты", "Портфель", "Модули и причины", "Запуск / обновление"])
    with tabs[0]:
        base.render_overview(run_dir)
    with tabs[1]:
        base.render_bonds(run_dir)
    with tabs[2]:
        render_candidates(run_dir)
    with tabs[3]:
        render_portfolio(run_dir)
    with tabs[4]:
        trace = base.trace_table(run_dir)
        st.dataframe(trace, use_container_width=True, hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[5]:
        base.render_rerun(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


if __name__ == "__main__":
    main()
