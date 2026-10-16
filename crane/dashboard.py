"""Live fleet dashboard.

    streamlit run crane/dashboard.py
"""
import os

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
ATTENTION = 40  # health below this needs attention
REFRESH_SECONDS = 180

st.set_page_config(page_title="Crane Fleet Health", layout="wide")
st.title("Crane fleet health")


@st.fragment(run_every=REFRESH_SECONDS)
def live():
    try:
        fleet = httpx.get(f"{API}/fleet", timeout=5).json()
        alerts = httpx.get(f"{API}/alerts", params={"active": True}, timeout=5).json()
    except httpx.HTTPError as e:
        st.error(f"Cannot reach the API at {API}: {e}")
        return
    if not fleet:
        st.info("No readings yet. Start the simulator: python -m crane.client")
        return

    df = pd.DataFrame(fleet)
    c1, c2, c3 = st.columns(3)
    c1.metric("Machines", len(df))
    c2.metric("Need attention", int((df.health < ATTENTION).sum()))
    c3.metric("Active alerts", len(alerts))

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Machines by risk")
        st.dataframe(
            df[["rank", "machine_id", "health", "rul_days", "anomaly", "alerts", "ts"]],
            hide_index=True, width="stretch",
            column_config={
                "health": st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%.0f"),
                "rul_days": st.column_config.NumberColumn("Service needed in (days)", format="%.1f"),
                "ts": st.column_config.DatetimeColumn("Last reading"),
            },
        )
    with right:
        st.subheader("Active alerts")
        if alerts:
            st.dataframe(pd.DataFrame(alerts)[["machine_id", "kind", "message", "raised_at"]],
                         hide_index=True, width="stretch")
        else:
            st.success("No active alerts")

    machine = st.selectbox("Machine detail", sorted(df.machine_id), key="machine")
    hist = pd.DataFrame(httpx.get(f"{API}/machines/{machine}/readings", params={"limit": 300}, timeout=5).json())
    a, b = st.columns(2)
    a.plotly_chart(px.line(hist, x="ts", y=["motor_temp", "vibration", "hoist_load"], title="Signals"),
                   width="stretch")
    b.plotly_chart(px.line(hist, x="ts", y=["health", "rul_days"], title="Health and service forecast"),
                   width="stretch")


live()
