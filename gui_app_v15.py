from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import gui_app_v14 as v14
import gui_app_v4 as v4
import gui_app_v6 as v6
import gui_app_v9 as v9
import gui_app_v10 as v10
import gui_app_v12 as v12
import gui_app_v13 as v13
import gui_app_v2 as base
from portfolio_income import analyze_portfolio_income, write_report
from portfolio_manual import lookup_bond, make_position
from portfolio_store import list_portfolios, load_portfolio, save_portfolio, upsert_position

PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"
REPORT_DIR = base.PROJECT_ROOT / "reports"


def _money(value) -> str:
    try:
        return f"{float(value):,.0f} ₽".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def render_manual_holding() -> None:
    st.markdown("---")
    st.subheader("Мои бумаги вне отбора")
    st.caption(
        "Добавьте любую облигацию MOEX по SECID — в том числе уже купленную раньше и отсутствующую "
        "в текущем полном скане. Указывайте суммарное текущее количество и фактически вложенную сумму."
    )
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Сначала создайте портфель выше.")
        return

    name = st.selectbox("Портфель для ручной позиции", list(portfolios), key="manual_portfolio_v15")
    secid = st.text_input("SECID", placeholder="RU000A10....", key="manual_secid_v15").strip().upper()
    if st.button("Проверить SECID на MOEX", disabled=not bool(secid), key="manual_lookup_v15"):
        try:
            with st.spinner("Получаю карточку бумаги с MOEX..."):
                st.session_state["manual_bond_v15"] = lookup_bond(secid)
            st.session_state["manual_bond_portfolio_v15"] = name
        except Exception as exc:
            st.session_state.pop("manual_bond_v15", None)
            st.error(str(exc))

    bond = st.session_state.get("manual_bond_v15")
    if not bond:
        return
    if str(bond.get("secid")) != secid and secid:
        st.info("Нажмите «Проверить SECID», чтобы обновить карточку для введённой бумаги.")

    a, b, c, d = st.columns(4)
    a.metric("SECID", bond.get("secid") or "—")
    b.metric("Цена рынка", f"{bond.get('market_price_percent'):.2f}%" if bond.get("market_price_percent") is not None else "—")
    c.metric("Доходность", f"{bond.get('yield'):.2f}%" if bond.get("yield") is not None else "—")
    d.metric("Погашение", bond.get("maturity_date") or "—")
    st.caption(f"{bond.get('name') or bond.get('secid')} · эмитент: {bond.get('issuer') or 'не определён'}")

    portfolio = load_portfolio(PORTFOLIO_DIR, name)
    existing = next((item for item in portfolio.get("positions", []) if str(item.get("secid")) == str(bond.get("secid"))), {})
    q1, q2, q3 = st.columns(3)
    quantity = q1.number_input(
        "Количество, шт.", min_value=1, value=max(1, int(existing.get("quantity") or 1)), step=1, key="manual_qty_v15"
    )
    default_price = float(existing.get("purchase_price_percent") or bond.get("market_price_percent") or 100.0)
    purchase_price = q2.number_input(
        "Средняя цена покупки, %", min_value=0.01, value=default_price, step=0.01, key="manual_price_v15"
    )
    existing_date = str(existing.get("purchase_date") or "")[:10]
    try:
        default_date = date.fromisoformat(existing_date) if existing_date else date.today()
    except ValueError:
        default_date = date.today()
    purchase_date = q3.date_input("Дата / дата последней покупки", value=default_date, key="manual_date_v15")

    face = float(bond.get("face_value") or 1000.0)
    nkd = float(bond.get("accrued_interest") or 0.0)
    calculated = int(quantity) * (face * float(purchase_price) / 100.0 + nkd)
    invested = st.number_input(
        "Фактически вложено, ₽",
        min_value=0.01,
        value=float(existing.get("invested") or calculated),
        step=100.0,
        key="manual_invested_v15",
        help="Для уже существующего портфеля лучше указать фактическую сумму из брокера. НКД в расчётной подсказке учитывается.",
    )
    st.caption(
        f"Номинал {face:,.2f} ₽ · текущий НКД {nkd:,.2f} ₽ · ориентир по введённой цене {_money(calculated)}".replace(",", " ")
    )

    if st.button("Сохранить как мою позицию", type="primary", key="manual_save_v15"):
        try:
            position = make_position(
                bond,
                quantity=int(quantity),
                purchase_price_percent=float(purchase_price),
                invested=float(invested),
                purchase_date=purchase_date,
            )
            updated = upsert_position(portfolio, position)
            save_portfolio(PORTFOLIO_DIR, updated)
            st.success(f"{bond['secid']} сохранена в портфель «{name}».")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def render_income_analytics() -> None:
    st.markdown("---")
    st.subheader("Доход и календарь портфеля")
    st.caption(
        "Купоны и погашения берутся по текущему bondization MOEX и умножаются на сохранённое количество. "
        "Это денежный календарь, а не обещанная доходность к погашению."
    )
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        return
    name = st.selectbox("Портфель для доходной аналитики", list(portfolios), key="income_portfolio_v15")

    left, right = st.columns(2)
    if left.button("Обновить доходный календарь", type="primary", key="income_refresh_v15"):
        try:
            with st.spinner("Загружаю купоны, амортизации и оферты MOEX..."):
                portfolio = load_portfolio(PORTFOLIO_DIR, name)
                payload = analyze_portfolio_income(portfolio)
                write_report(payload, REPORT_DIR)
                st.session_state["income_payload_v15"] = payload
                st.session_state["income_payload_name_v15"] = name
        except Exception as exc:
            st.error(str(exc))

    if right.button("Обновить риск-мониторинг моих бумаг", key="manual_monitor_v15"):
        command = [sys.executable, str(base.PROJECT_ROOT / "daily_runner.py"), "monitor", "--portfolio", name]
        try:
            with st.spinner("Обновляю MOEX, новости, рейтинги, ОФЗ и действия..."):
                result = subprocess.run(
                    command,
                    cwd=base.PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            if result.returncode == 0:
                st.success("Риск-мониторинг обновлён. Результат доступен во вкладке «Сегодня».")
            else:
                st.error(f"Мониторинг завершился с кодом {result.returncode}")
            with st.expander("Лог мониторинга", expanded=result.returncode != 0):
                st.code((result.stdout or "") + ("\n" + result.stderr if result.stderr else ""))
        except Exception as exc:
            st.error(str(exc))

    payload = st.session_state.get("income_payload_v15")
    if not payload or st.session_state.get("income_payload_name_v15") != name:
        path = REPORT_DIR / f"portfolio_income_{name}_latest.json"
        if path.exists():
            try:
                import json
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
    if not payload:
        st.info("Нажмите «Обновить доходный календарь».")
        return

    summary = payload.get("summary", {})
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Купоны 12 мес.", _money(summary.get("coupons_12m")))
    m2.metric("Номинал/амортизация", _money(summary.get("principal_12m")))
    cash_yield = summary.get("coupon_cash_yield_percent")
    m3.metric("Купоны / вложено", f"{cash_yield:.2f}%" if cash_yield is not None else "—")
    m4.metric("Месяцев с купонами", f"{summary.get('income_months', 0)}/12")
    m5.metric("Ближайшее поступление", summary.get("next_payment_date") or "—")

    monthly = pd.DataFrame(summary.get("monthly", []))
    if not monthly.empty:
        chart = monthly.rename(columns={"month": "Месяц", "coupons": "Купоны", "principal": "Погашение"}).set_index("Месяц")
        st.markdown("### Денежный поток по месяцам")
        st.bar_chart(chart[["Купоны", "Погашение"]])
        st.dataframe(monthly.rename(columns={
            "month": "Месяц", "coupons": "Купоны, ₽", "principal": "Погашение, ₽", "total": "Всего, ₽"
        }), width="stretch", hide_index=True)

    st.markdown("### Когда подумать о ребалансировке")
    reasons = summary.get("rebalance_reasons", [])
    if reasons:
        for reason in reasons:
            st.warning(reason)
    else:
        st.success("По текущим простым правилам концентрации, погашений и регулярности купонов явного триггера ребалансировки нет.")

    events = pd.DataFrame(payload.get("events", []))
    if not events.empty:
        st.markdown("### Ближайшие события")
        shown = events.head(40).rename(columns={
            "date": "Дата", "type": "Событие", "secid": "SECID", "name": "Название",
            "quantity": "Количество", "per_bond": "На 1 бумагу, ₽", "amount": "Сумма, ₽", "known": "Сумма известна",
        })
        st.dataframe(shown, width="stretch", hide_index=True)
    if payload.get("errors"):
        st.warning("Не удалось обновить часть бумаг: " + "; ".join(payload["errors"]))


def _render_existing_tabs(run_dir: Path, config: dict, is_today: bool) -> None:
    tabs = st.tabs(v10.TAB_NAMES)
    with tabs[0]:
        v9.render_today(run_dir)
    with tabs[1]:
        base.render_overview(run_dir)
    with tabs[2]:
        base.render_bonds(run_dir)
        v12.render_bond_journey(run_dir)
    with tabs[3]:
        v6.render_candidates(run_dir)
    with tabs[4]:
        v4.render_portfolio(run_dir)
        render_manual_holding()
        render_income_analytics()
        v13.render_portfolio_charts(run_dir)
    with tabs[5]:
        v6.render_recommendations(run_dir)
        v14.render_buy_plan(run_dir)
    with tabs[6]:
        trace = base.trace_table(run_dir)
        st.dataframe(trace, width="stretch", hide_index=True) if not trace.empty else st.info("Журнал пока отсутствует")
    with tabs[7]:
        v6.render_run_update(run_dir, config) if is_today else st.info("Архив доступен только для просмотра")


def main() -> None:
    v14._render_existing_tabs = _render_existing_tabs
    v14.main()


if __name__ == "__main__":
    main()
