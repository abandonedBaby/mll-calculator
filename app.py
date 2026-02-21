import streamlit as st
import pandas as pd

# 1. Setup Instrument Dictionary (Extracted from Instruments.csv)
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

# --- Session State Initialization ---
# We use this to remember the values between button clicks and pop-ups
if "avg_fill_price" not in st.session_state:
    st.session_state.avg_fill_price = 24798.25
if "total_qty" not in st.session_state:
    st.session_state.total_qty = 2
if "fill_data" not in st.session_state:
    # Default table data for the pop-up
    st.session_state.fill_data = pd.DataFrame([{"Qty": 1, "Price": 24798.25}, {"Qty": 1, "Price": 24800.00}])

# --- Pop-up Dialog for Weighted Average ---
@st.dialog("Calculate Weighted Average Fill")
def weighted_average_dialog():
    st.markdown("Enter your multiple fills below. You can add or delete rows at the bottom.")
    
    # Display an editable spreadsheet-like table
    edited_df = st.data_editor(
        st.session_state.fill_data, 
        num_rows="dynamic", # Allows user to add new rows
        use_container_width=True,
        hide_index=True
    )
    
    if st.button("Calculate & Apply", type="primary"):
        # Filter out empty or zero rows to avoid math errors
        valid_fills = edited_df[(edited_df["Qty"] > 0) & (edited_df["Price"] > 0)]
        
        if not valid_fills.empty:
            # Weighted Average Math: Sum of (Qty * Price) / Total Qty
            total_q = int(valid_fills["Qty"].sum())
            weighted_p = float((valid_fills["Qty"] * valid_fills["Price"]).sum() / total_q)
            
            # Save the new values to memory
            st.session_state.total_qty = total_q
            st.session_state.avg_fill_price = weighted_p
            st.session_state.fill_data = edited_df # Save the table state so it's there next time
            
            st.rerun() # Refresh the app to instantly apply the new values
        else:
            st.error("Please enter at least one valid Qty and Price.")

# --- App Header ---
st.title("📊 Invalid MLL Violation Checker")
st.markdown("Recreation of the MLL Calculation Spreadsheet")

# --- Inputs Section ---
st.header("Trade Details")

# Button to trigger the pop-up
if st.button("🧮 Add Multiple Entries (Weighted Average)"):
    weighted_average_dialog()

col1, col2 = st.columns(2)

with col1:
    instrument = st.selectbox("Instrument", options=list(INSTRUMENTS.keys()), index=0)
    # Notice the "value" fields are now pulling from st.session_state
    qty = st.number_input("Quantity (Qty)", min_value=1, value=st.session_state.total_qty, step=1)
    fill_price = st.number_input("Fill Price (Avg)", value=st.session_state.avg_fill_price, format="%.2f")
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
price_diff = abs(high_low - fill_price)
mae = - (price_diff * tick_value * ticks_per_pt * qty)

# 3. MLL Calculations
dist_2_mll = balance_before - mll
difference = dist_2_mll + mae  

# Violation Logic
is_invalid_violation = abs(mae) <= dist_2_mll
status = "Invalid" if is_invalid_violation else "Valid Violation"

# --- Output Section ---
st.header("Calculation Results")

# Display Lookup values
st.write(f"**Tick Value:** {tick_value} | **Ticks per Pt:** {ticks_per_pt}")

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
