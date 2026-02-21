import streamlit as st
import pandas as pd

st.set_page_config(page_title="Invalid MLL Violation Checker", layout="wide")

# --- Session State Initialization ---
if "instruments_df" not in st.session_state:
    default_instruments = [
        {"Instrument": "NQ", "Value per point": 20.0, "Tick Size": 0.25},
        {"Instrument": "MNQ", "Value per point": 2.0, "Tick Size": 0.25},
        {"Instrument": "ES", "Value per point": 50.0, "Tick Size": 0.25},
        {"Instrument": "MES", "Value per point": 5.0, "Tick Size": 0.25},
        {"Instrument": "GC", "Value per point": 100.0, "Tick Size": 0.10},
        {"Instrument": "MGC", "Value per point": 10.0, "Tick Size": 0.10},
        {"Instrument": "RTY", "Value per point": 50.0, "Tick Size": 0.10},
        {"Instrument": "YM", "Value per point": 5.0, "Tick Size": 1.00},
        {"Instrument": "MBT", "Value per point": 0.1, "Tick Size": 5.00},
        {"Instrument": "MYM", "Value per point": 0.5, "Tick Size": 0.50},
    ]
    st.session_state.instruments_df = pd.DataFrame(default_instruments)

if "avg_fill_price" not in st.session_state:
    st.session_state.avg_fill_price = 24798.25
if "total_qty" not in st.session_state:
    st.session_state.total_qty = 2
if "fill_data" not in st.session_state:
    st.session_state.fill_data = pd.DataFrame([{"Qty": 1, "Price": 24798.25}, {"Qty": 1, "Price": 24800.00}])

# --- Build Instrument Dictionary dynamically ---
INSTRUMENTS = {}
for _, row in st.session_state.instruments_df.iterrows():
    name = row["Instrument"]
    val_per_pt = row["Value per point"]
    tick_size = row["Tick Size"]
    
    ticks_per_pt = 1 / tick_size if tick_size != 0 else 0
    tick_val = val_per_pt * tick_size
    INSTRUMENTS[name] = {"Tick Value": tick_val, "Ticks per Pt": ticks_per_pt}

# --- Pop-up Dialogs ---
@st.dialog("⚙️ Manage Instruments")
def manage_instruments_dialog():
    st.markdown("Add, edit, or delete instruments. **Tick Value** and **Ticks per Pt** will be calculated automatically.")
    edited_df = st.data_editor(st.session_state.instruments_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Save Instruments", type="primary"):
        cleaned_df = edited_df.dropna(subset=["Instrument"])
        cleaned_df = cleaned_df[cleaned_df["Instrument"].astype(str).str.strip() != ""]
        st.session_state.instruments_df = cleaned_df
        st.rerun()

@st.dialog("Calculate Weighted Average Fill")
def weighted_average_dialog():
    st.markdown("Enter your multiple fills below. You can add or delete rows at the bottom.")
    edited_df = st.data_editor(st.session_state.fill_data, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Calculate & Apply", type="primary"):
        valid_fills = edited_df[(edited_df["Qty"] > 0) & (edited_df["Price"] > 0)]
        if not valid_fills.empty:
            total_q = int(valid_fills["Qty"].sum())
            weighted_p = float((valid_fills["Qty"] * valid_fills["Price"]).sum() / total_q)
            st.session_state.total_qty = total_q
            st.session_state.avg_fill_price = weighted_p
            st.session_state.fill_data = edited_df 
            st.rerun() 
        else:
            st.error("Please enter at least one valid Qty and Price.")

# --- App Header & Responsive CSS ---
st.title("📊 Invalid MLL Violation Checker")

# Inject Responsive CSS for Compact Mode
st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 1rem; }
        /* Clamp font size: minimum 1.5rem, scales with view width, max 2.5rem */
        h1 { font-size: clamp(1.5rem, 4vw, 2.5rem) !important; padding-top: 0 !important; }
        div[data-testid="stMetricValue"] { font-size: 1.5rem; }
        hr { margin-top: 0.5rem; margin-bottom: 0.5rem; }
        
        /* Only apply negative margins on larger screens to prevent overlap when stacked on mobile */
        @media (min-width: 800px) {
            h1 { margin-bottom: -1.5rem; }
            h2 { margin-bottom: -1rem; padding-top: 0rem; }
        }
    </style>
""", unsafe_allow_html=True)

# Action Buttons
btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    if st.button("🧮 Add Multiple Entries (Average)"):
        weighted_average_dialog()
with btn_col2:
    if st.button("⚙️ Manage Instruments"):
        manage_instruments_dialog()

# --- Inputs Section (Permanent Compact Layout) ---
instrument_list = list(INSTRUMENTS.keys())
if not instrument_list:
    instrument_list = ["None"]
    INSTRUMENTS["None"] = {"Tick Value": 0.0, "Ticks per Pt": 0.0}

st.subheader("Trade Details")
c1, c2, c3, c4 = st.columns(4)
with c1:
    instrument = st.selectbox("Instrument", options=instrument_list, index=0)
    close_price = st.number_input("Close Price", value=24845.75, format="%.2f")
with c2:
    qty = st.number_input("Quantity (Qty)", min_value=1, value=st.session_state.total_qty, step=1)
    high_low = st.number_input("High/Low", value=24848.00, format="%.2f")
with c3:
    fill_price = st.number_input("Fill Price (Avg)", value=st.session_state.avg_fill_price, format="%.2f")
    balance_before = st.number_input("Balance Before", value=0.00, format="%.2f")
with c4:
    mll = st.number_input("MLL", value=-2000.00, format="%.2f")

# --- Calculations Section ---
tick_value = INSTRUMENTS[instrument]["Tick Value"]
ticks_per_pt = INSTRUMENTS[instrument]["Ticks per Pt"]

price_diff = abs(high_low - fill_price)
mae = - (price_diff * tick_value * ticks_per_pt * qty)

dist_2_mll = balance_before - mll
difference = dist_2_mll + mae  

is_invalid_violation = abs(mae) <= dist_2_mll
status = "Invalid" if is_invalid_violation else "Valid Violation"

# --- Output Section ---
st.subheader("Calculation Results")

# Display Lookup values
st.write(f"**Calculated Tick Value:** {tick_value:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Calculated Ticks per Pt:** {ticks_per_pt:,.2f}")

# Metrics Display
metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("MAE", f"${mae:,.2f}")
metric_col2.metric("Distance to MLL", f"${dist_2_mll:,.2f}")
metric_col3.metric("Difference", f"${difference:,.2f}")

if is_invalid_violation:
    st.success(f"**Status:** {status} - The loss did not exceed the MLL distance.")
else:
    st.error(f"**Status:** {status} - The MLL limit was breached!")
