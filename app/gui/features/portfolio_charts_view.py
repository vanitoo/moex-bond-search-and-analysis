from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app.gui.features import base
from app.portfolio.portfolio_impact import infer_issuer, risk_level, safe_float
from app.portfolio.portfolio_store import list_portfolios, load_portfolio


PORTFOLIO_DIR = base.PROJECT_ROOT / "data" / "virtual_portfolios"


def _position_value(position: dict, bond: dict) -> float:
    quantity = safe_float(position.get("quantity"))
    face = safe_float(base.deep_get(bond, "market.face_value")) or 1000.0
    price = safe_float(base.deep_get(bond, "market.price"))
    if quantity and price:
        return quantity * face * price / 100.0
    return safe_float(position.get("invested")) or 0.0


def render_portfolio_charts(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("Структура портфеля")
    portfolios = list_portfolios(PORTFOLIO_DIR)
    if not portfolios:
        st.info("Нет виртуальных портфелей для построения графиков.")
        return

    name = st.selectbox("Портфель для графиков", list(portfolios), key="portfolio_charts_name")
    portfolio = load_portfolio(PORTFOLIO_DIR, name)
    master = base.load_master(run_dir)
    by_secid = {
        str(item.get("secid")): item
        for item in master.get("bonds", [])
        if item.get("secid")
    }

    rows = []
    for position in portfolio.get("positions", []):
        secid = str(position.get("secid") or "")
        if not secid:
            continue
        bond = by_secid.get(secid, {})
        value = _position_value(position, bond)
        if value <= 0:
            continue

        rating = position.get("rating") or base.deep_get(bond, "credit.rating") or "Нет рейтинга"
        maturity = base.deep_get(bond, "market.maturity_date") or position.get("maturity_date")
        year = "Неизвестно"
        if maturity:
            text = str(maturity)
            if len(text) >= 4 and text[:4].isdigit():
                year = text[:4]

        rows.append({
            "SECID": secid,
            "Название": position.get("name") or bond.get("name") or secid,
            "Эмитент": position.get("issuer") or infer_issuer(bond, position) or "Не определён",
            "Риск": risk_level(bond, position) or "unknown",
            "Рейтинг": str(rating),
            "Год погашения": year,
            "Стоимость": value,
        })

    if not rows:
        st.info("В портфеле пока нет позиций с оценимой стоимостью.")
        return

    frame = pd.DataFrame(rows)
    total = float(frame["Стоимость"].sum())
    frame["Доля, %"] = frame["Стоимость"] / total * 100.0 if total else 0.0

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**По выпускам**")
        st.bar_chart(frame.groupby("Название")["Стоимость"].sum().sort_values(ascending=False))
    with col2:
        st.markdown("**По эмитентам**")
        st.bar_chart(frame.groupby("Эмитент")["Стоимость"].sum().sort_values(ascending=False))

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**По уровню риска**")
        st.bar_chart(frame.groupby("Риск")["Стоимость"].sum().sort_values(ascending=False))
    with col4:
        st.markdown("**Доли позиций, %**")
        st.bar_chart(frame.groupby("Название")["Доля, %"].sum().sort_values(ascending=False))

    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**По кредитным рейтингам**")
        st.bar_chart(frame.groupby("Рейтинг")["Стоимость"].sum().sort_values(ascending=False))
    with col6:
        st.markdown("**Лестница погашений по годам**")
        maturity = frame.groupby("Год погашения")["Стоимость"].sum()
        known = maturity.drop(labels=["Неизвестно"], errors="ignore")
        unknown = maturity.get("Неизвестно", 0.0)
        try:
            known = known.sort_index(key=lambda idx: idx.astype(int))
        except Exception:
            known = known.sort_index()
        if unknown:
            known.loc["Неизвестно"] = unknown
        st.bar_chart(known)

    with st.expander("Таблица структуры портфеля"):
        st.dataframe(frame.sort_values("Стоимость", ascending=False), width="stretch", hide_index=True)
