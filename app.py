"""
IPS Review Assistant -- Streamlit app

Upload (or use the sample) IPS parameters and portfolio holdings, and run a
deterministic consistency check between them.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

import json

import pandas as pd
import streamlit as st

from ips_checker import compute_allocation, run_all_checks
from ips_docx import parse_ips_docx, IpsDocxParseError

st.set_page_config(page_title="IPS Review Assistant", page_icon="\U0001F4CB", layout="wide")

REQUIRED_PORTFOLIO_COLS = ["name", "ticker", "asset_class", "security_type", "market_value", "restricted_flags"]


def load_default_ips() -> dict:
    with open("sample_data/sample_ips.json") as f:
        return json.load(f)


def load_default_portfolio() -> pd.DataFrame:
    df = pd.read_csv("sample_data/sample_portfolio.csv")
    df["restricted_flags"] = df["restricted_flags"].fillna("")
    return df


if "ips" not in st.session_state:
    st.session_state.ips = load_default_ips()
if "portfolio_df" not in st.session_state:
    st.session_state.portfolio_df = load_default_portfolio()
if "allocation_df" not in st.session_state:
    targets = st.session_state.ips["allocation_targets"]
    st.session_state.allocation_df = pd.DataFrame(
        [{"Asset Class": k, "Min %": v["min"], "Max %": v["max"]} for k, v in targets.items()]
    )

st.title("IPS Review Assistant")
st.caption(
    "Checks a client portfolio against its Investment Policy Statement. All figures below "
    "are computed with plain arithmetic."
)

# ---------------------------------------------------------------- sidebar --
with st.sidebar:
    st.header("Data")

    ips_file = st.file_uploader("IPS parameters (JSON or Word)", type=["json", "docx"])
    if ips_file is not None:
        try:
            if ips_file.name.lower().endswith(".docx"):
                new_ips = parse_ips_docx(ips_file)
            else:
                new_ips = json.load(ips_file)
        except IpsDocxParseError as e:
            st.error(str(e))
            new_ips = None
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            new_ips = None

        if new_ips is not None:
            st.session_state.ips = new_ips
            targets = st.session_state.ips["allocation_targets"]
            st.session_state.allocation_df = pd.DataFrame(
                [{"Asset Class": k, "Min %": v["min"], "Max %": v["max"]} for k, v in targets.items()]
            )

    portfolio_file = st.file_uploader("Portfolio holdings (CSV or Excel)", type=["csv", "xlsx"])
    if portfolio_file is not None:
        try:
            if portfolio_file.name.lower().endswith(".xlsx"):
                df = pd.read_excel(portfolio_file)
            else:
                df = pd.read_csv(portfolio_file)
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            df = None

        if df is not None:
            missing = set(REQUIRED_PORTFOLIO_COLS) - set(df.columns)
            if missing:
                st.error(f"File is missing required columns: {sorted(missing)}")
            else:
                df["restricted_flags"] = df["restricted_flags"].fillna("")
                st.session_state.portfolio_df = df

# ------------------------------------------------------------ IPS editor --
st.subheader("1. Investment Policy Statement")
col1, col2 = st.columns(2)

with col1:
    st.session_state.ips["client_name"] = st.text_input("Client", st.session_state.ips.get("client_name", ""))
    st.session_state.ips["risk_tolerance"] = st.selectbox(
        "Risk tolerance",
        ["Conservative", "Moderate", "Moderate Growth", "Growth", "Aggressive"],
        index=["Conservative", "Moderate", "Moderate Growth", "Growth", "Aggressive"].index(
            st.session_state.ips.get("risk_tolerance", "Moderate")
        ) if st.session_state.ips.get("risk_tolerance") in
        ["Conservative", "Moderate", "Moderate Growth", "Growth", "Aggressive"] else 1,
    )
    st.session_state.ips["time_horizon_years"] = st.number_input(
        "Time horizon (years)", min_value=1, max_value=50,
        value=int(st.session_state.ips.get("time_horizon_years", 10)),
    )

with col2:
    st.session_state.ips["liquidity_reserve_pct"] = st.number_input(
        "Liquidity reserve requirement (%)", min_value=0.0, max_value=100.0,
        value=float(st.session_state.ips.get("liquidity_reserve_pct", 5.0)),
    )
    st.session_state.ips["single_position_limit_pct"] = st.number_input(
        "Single-position limit (%, individual securities only)", min_value=0.0, max_value=100.0,
        value=float(st.session_state.ips.get("single_position_limit_pct", 10.0)),
    )
    constraints_text = st.text_area(
        "Constraints (one per line)",
        "\n".join(st.session_state.ips.get("constraints", [])),
        height=80,
    )
    st.session_state.ips["constraints"] = [c.strip() for c in constraints_text.splitlines() if c.strip()]

st.markdown("**Target asset allocation bands**")
edited_alloc = st.data_editor(
    st.session_state.allocation_df,
    num_rows="dynamic",
    use_container_width=True,
    key="alloc_editor",
)
st.session_state.allocation_df = edited_alloc
st.session_state.ips["allocation_targets"] = {
    row["Asset Class"]: {"min": row["Min %"], "max": row["Max %"]}
    for _, row in edited_alloc.iterrows() if row["Asset Class"]
}

# ------------------------------------------------------------- portfolio --
st.subheader("2. Portfolio holdings")
edited_portfolio = st.data_editor(
    st.session_state.portfolio_df,
    num_rows="dynamic",
    use_container_width=True,
    key="portfolio_editor",
)
st.session_state.portfolio_df = edited_portfolio

# ---------------------------------------------------------------- review --
st.subheader("3. Run review")

if st.button("Run review", type="primary"):
    portfolio_df = st.session_state.portfolio_df.copy()
    portfolio_df["restricted_flags"] = portfolio_df["restricted_flags"].fillna("")
    portfolio_df["market_value"] = portfolio_df["market_value"].astype(float)

    result = run_all_checks(st.session_state.ips, portfolio_df)

    m1, m2, m3 = st.columns(3)
    m1.metric("Portfolio value", f"${result['total_market_value']:,.0f}")
    m2.metric("Flags", result["flag_count"])
    m3.metric("Passed checks", result["ok_count"])

    st.markdown("**Actual allocation**")
    alloc_actual = compute_allocation(portfolio_df)
    st.bar_chart(alloc_actual)

    st.markdown("**Findings**")
    findings_df = pd.DataFrame(result["findings"])

    def _highlight(row):
        color = "background-color: #ffe3e3" if row["status"] == "FLAG" else "background-color: #e6f7e9"
        return [color] * len(row)

    st.dataframe(findings_df.style.apply(_highlight, axis=1), use_container_width=True)
