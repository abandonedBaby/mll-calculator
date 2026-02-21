import streamlit as st
import pandas as pd

# 1. Setup Instrument Dictionary (Extracted from Instruments.csv)
# Format: "Instrument": {"Tick Value": tick_val, "Ticks per Pt": ticks_per_pt}
INSTRUMENTS = {
    "NQ": {"Tick Value": 5.0, "Ticks per Pt": 4},
    "MNQ": {"Tick Value": 0.5, "Ticks per Pt": 4},
    "ES": {"Tick Value": 12.5, "Ticks per Pt": 4},
    "MES": {"Tick Value": 1.25, "Ticks per Pt": 4},
    "GC": {"Tick Value": 10.0, "Ticks per Pt": 10},
    "MGC": {"Tick Value": 1.0, "Ticks per Pt": 10},
    "RTY": {"Tick Value": 5.0, "Ticks per Pt": 10},
    "YM": {"Tick Value": 5.0, "Ticks per Pt": 1},
    "MBT": {"Tick Value": 0.5, "Ticks per Pt": 0.2},
    "MYM": {"Tick Value": 0.25, "Ticks per Pt": 2},
}

st.set_page_config(page_title="Invalid MLL Violation Checker", layout="centered")

st.title("📊 Invalid MLL Violation Checker")
st.markdown("Recreation of the MLL Calculation Spreadsheet")

# --- Inputs Section ---
st.header("Trade Details")
col1, col2 = st.columns(2)

with col1:
    instrument = st.selectbox("Instrument", options=list(INSTRUMENTS.keys()), index=0)
    qty = st.number_input("Quantity (Qty)", min_value=1, value=2, step=1)
    fill_price = st.number_input("Fill Price (Avg)", value=24798.25, format="%.2f")
    close_price = st.number_input("Close Price", value=24845.75, format="%.2f")

with col2:
    high_low = st.number_input("High/Low", value=24848.00, format="%.2f")
    balance_before = st.number_input("Balance Before", value=0.00, format="%.2f")
    mll = st.number_input("MLL", value=-2000.00, format="%.2f")

# --- Calculations Section ---
# 1. Lookups
tick_value = INSTRUMENTS[instrument]["Tick Value"]
ticks_per_pt = INSTRUMENTS[instrument]["Ticks per Pt"]

# 2. MAE Calculation
# MAE is adverse, so it will be strictly negative based on maximum adverse excursion
price_diff = abs(high_low - fill_price)
mae = - (price_diff * tick_value * ticks_per_pt * qty)

# 3. MLL Calculations
dist_2_mll = balance_before - mll

# Mathematical difference (Amount of breathing room left)
difference = dist_2_mll + mae  

# Violation Logic: If the MAE exceeds the distance to MLL, it's a valid violation.
# Otherwise, the system flagging it was "Invalid"
is_invalid_violation = abs(mae) <= dist_2_mll
status = "Invalid" if is_invalid_violation else "Valid Violation"

# --- Output Section ---
st.header("Calculation Results")

# Display Lookup values
st.write(f"**Tick Value:** {tick_value}")
st.write(f"**Ticks per Pt:** {ticks_per_pt}")

st.divider()

# Metrics Display
metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("MAE", f"${mae:,.2f}")
metric_col2.metric("Distance to MLL", f"${dist_2_mll:,.2f}")
metric_col3.metric("Difference", f"${difference:,.2f}")

st.divider()

if is_invalid_violation:
    st.success(f"**Status:** {status} - The loss did not exceed the MLL distance.")
else:
    st.error(f"**Status:** {status} - The MLL limit was breached!")