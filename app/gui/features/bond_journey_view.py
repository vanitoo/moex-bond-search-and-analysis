from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from app.gui.features import base
from app.core.bond_journey import journey_rows, route_text


def render_bond_journey(run_dir: Path) -> None:
    st.markdown("---")
    st.subheader("Маршрут облигации по анализу")
    master = base.load_master(run_dir)
    bonds = master.get("bonds", [])
    if not bonds:
        st.info("Нет данных для показа маршрута облигации.")
        return

    by_secid = {
        str(item.get("secid")): item
        for item in bonds
        if item.get("secid")
    }
    selected = st.selectbox(
        "Облигация",
        sorted(by_secid, key=lambda secid: base.bond_label(by_secid[secid]).lower()),
        format_func=lambda secid: base.bond_label(by_secid[secid]),
        key="bond_journey",
    )
    bond = by_secid[selected]

    price = base.deep_get(bond, "market.price")
    ytm = base.deep_get(bond, "market.yield")
    spread = base.deep_get(bond, "ofz_spread.spread_bp")

    a, b, c, d, e = st.columns(5)
    a.metric("Цена, %", price if price is not None else "—")
    b.metric("YTM, %", ytm if ytm is not None else "—")
    c.metric("Рейтинг", base.deep_get(bond, "credit.rating") or "—")
    d.metric("Спред к ОФЗ, б.п.", spread if spread is not None else "—")
    e.metric("Решение", base.deep_get(bond, "decision.status") or "—")

    route = route_text(bond)
    if route:
        st.caption(route)

    st.dataframe(pd.DataFrame(journey_rows(bond)), width="stretch", hide_index=True)
