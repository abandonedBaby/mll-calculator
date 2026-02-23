import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Invalid MLL Violation Checker", layout="wide")

# --- Admin Access (Hidden in Sidebar) ---
with st.sidebar:
    st.header("🔐 Admin Access")
    admin_password = st.text_input("Password", type="password")
    
    expected_password = st.secrets.get("admin_password", "admin123")
    is_admin = (admin_password == expected_password)
    
    if is_admin:
        st.success("Admin unlocked!")

# --- Connect to Google Sheets ---
default_instruments = [
    {"Instrument": "NQ", "Value per point": 20.0, "Tick Size": 0.25},
    {"Instrument": "ES", "Value per point": 50.0, "Tick Size": 0.25},
]

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    instruments_df = conn.read(worksheet="Instruments", ttl="0m") 
    instruments_df = instruments_df.dropna(how="all") 
    
    if instruments_df.empty:
        instruments_df = pd.DataFrame(default_instruments)
except Exception as e:
    instruments_df = pd.DataFrame(default_instruments)
    st.sidebar.error(f"⚠️ Google Sheets Error: {e}") 

if "instruments_df" not in st.session_state or getattr(st.session_state, 'force_refresh', True):
    st.session_state.instruments_df = instruments_df
    st.session_state.force_refresh = False

# --- Widget Session State Initialization ---
if "qty" not in st.session_state: st.session_state.qty = 2
if "fill_price" not in st.session_state: st.session_state.fill_price = 24798.25
if "close_price" not in st.session_state: st.session_state.close_price = 24845.75
if "high_low" not in st.session_state: st.session_state.high_low = 24848.00
if "balance_before" not in st.session_state: st.session_state.balance_before = 0.00
if "mll" not in st.session_state: st.session_state.mll = -2000.00
if "violation_time" not in st.session_state: st.session_state.violation_time = ""
if "fill_data" not in st.session_state: 
    st.session_state.fill_data = pd.DataFrame([{"Qty": 1, "Price": 24798.25}, {"Qty": 1, "Price": 24800.00}])

# --- Build Instrument Dictionary dynamically ---
INSTRUMENTS = {}
for _, row in st.session_state.instruments_df.iterrows():
    name = str(row["Instrument"]).strip()
    if name == "nan" or name == "": continue
    
    val_per_pt = float(row["Value per point"])
    tick_size = float(row["Tick Size"])
    
    ticks_per_pt = 1 / tick_size if tick_size != 0 else 0
    tick_val = val_per_pt * tick_size
    INSTRUMENTS[name] = {"Tick Value": tick_val, "Ticks per Pt": ticks_per_pt}

# --- Actions & Dialogs ---
def clear_all():
    """Resets all input fields to 0 or blank"""
    st.session_state.qty = 0
    st.session_state.fill_price = 0.00
    st.session_state.close_price = 0.00
    st.session_state.high_low = 0.00
    st.session_state.balance_before = 0.00
    st.session_state.mll = 0.00
    st.session_state.violation_time = ""
    st.session_state.fill_data = pd.DataFrame([{"Qty": 0, "Price": 0.00}])

@st.dialog("⚙️ Manage Instruments")
def manage_instruments_dialog():
    st.markdown("Add, edit, or delete instruments. Changes will sync permanently to Google Sheets.")
    edited_df = st.data_editor(st.session_state.instruments_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    
    if st.button("Save to Cloud", type="primary"):
        cleaned_df = edited_df.dropna(subset=["Instrument"])
        cleaned_df = cleaned_df[cleaned_df["Instrument"].astype(str).str.strip() != ""]
        
        try:
            conn.update(worksheet="Instruments", data=cleaned_df)
            st.session_state.force_refresh = True 
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save to Google Sheets. Check your setup.")

@st.dialog("Calculate Weighted Average Fill")
def weighted_average_dialog():
    st.markdown("Enter multiple fills manually, or **paste raw tab-delimited data** directly from your platform.")
    
    # --- Paste Feature (Now with Auto-Apply) ---
    pasted_text = st.text_area("📋 Quick Paste", placeholder="Paste rows here... (Extracts Col H & Col K)", height=100)
    
    if st.button("🚀 Extract & Apply", type="primary"):
        parsed_rows = []
        for line in pasted_text.strip().split('\n'):
            if not line.strip(): continue 
            cols = line.split('\t')
            if len(cols) >= 11:
                try:
                    qty_str = cols[7].replace(',', '').strip()
                    price_str = cols[10].replace(',', '').strip()
                    if qty_str and price_str: 
                        q = float(qty_str)
                        p = float(price_str)
                        if q != 0:
                            parsed_rows.append({"Qty": q, "Price": p})
                except ValueError:
                    pass 
        
        if parsed_rows:
            # Turn into dataframe and calculate math immediately
            df = pd.DataFrame(parsed_rows)
            total_q = int(df["Qty"].sum())
            
            if total_q != 0:
                weighted_p = float((df["Qty"] * df["Price"]).sum() / total_q)
                
                # Apply instantly to session state
                st.session_state.qty = total_q
                st.session_state.fill_price = weighted_p
                st.session_state.fill_data = df 
                st.rerun() # This closes the dialog and refreshes the main page!
            else:
                st.error("Total quantity equals 0. Cannot calculate average price.")
        else:
            st.error("Could not find valid numbers in Column H (Qty) and Column K (Price).")
            
    st.divider()

    # --- Existing Manual Editor ---
    st.caption("Or edit rows manually:")
    edited_df = st.data_editor(st.session_state.fill_data, num_rows="dynamic", use_container_width=True, hide_index=True)
    
    # Changed button text so it's not confusing
    if st.button("Calculate & Apply Manual Edits"):
        valid_fills = edited_df[(edited_df["Qty"] != 0) & (edited_df["Price"] > 0)]
        if not valid_fills.empty:
            total_q = int(valid_fills["Qty"].sum())
            weighted_p = float((valid_fills["Qty"] * valid_fills["Price"]).sum() / total_q)
            
            st.session_state.qty = total_q
            st.session_state.fill_price = weighted_p
            st.session_state.fill_data = edited_df 
            st.rerun() 
        else:
            st.error("Please enter at least one valid Qty and Price.")

# --- App Header & Responsive CSS ---
st.title("📊 Invalid MLL Violation Checker")

st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 1rem; }
        h1 { font-size: clamp(1.5rem, 4vw, 2.5rem) !important; padding-top: 0 !important; }
        div[data-testid="stMetricValue"] { font-size: 1.5rem; }
        hr { margin-top: 0.5rem; margin-bottom: 0.5rem; }
        @media (min-width: 800px) {
            h1 { margin-bottom: -1.5rem; }
            h2 { margin-bottom: -1rem; padding-top: 0rem; }
        }
    </style>
""", unsafe_allow_html=True)

# Action Buttons
btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    if st.button("🧮 Add Multiple Entries"):
        weighted_average_dialog()
with btn_col2:
    if is_admin:
        if st.button("⚙️ Manage Instruments"):
            manage_instruments_dialog()
with btn_col3:
    if st.button("🗑️ Clear All"):
        clear_all()

# --- Inputs Section ---
instrument_list = list(INSTRUMENTS.keys())
if not instrument_list:
    instrument_list = ["None"]
    INSTRUMENTS["None"] = {"Tick Value": 0.0, "Ticks per Pt": 0.0}

st.subheader("Trade Details")

# Determine Dynamic High/Low Label and Tooltip based on Quantity
current_qty = st.session_state.qty
if current_qty > 0:
    hl_label = "📉 Low"
    hl_help = "Long Adverse Excursion: Enter the lowest price reached during the trade."
    clean_label = "Low"
elif current_qty < 0:
    hl_label = "📈 High"
    hl_help = "Short Adverse Excursion: Enter the highest price reached during the trade."
    clean_label = "High"
else:
    hl_label = "High/Low"
    hl_help = "Enter the adverse excursion price (Lowest price for Longs, Highest price for Shorts)."
    clean_label = "High/Low"

c1, c2, c3, c4 = st.columns(4)
with c1:
    instrument = st.selectbox("Instrument", options=instrument_list, index=0)
    close_price = st.number_input("Close Price", format="%.2f", key="close_price")
with c2:
    qty = st.number_input("Quantity (Qty)", step=1, key="qty")
    high_low = st.number_input(hl_label, format="%.2f", key="high_low", help=hl_help)
with c3:
    fill_price = st.number_input("Fill Price (Avg)", format="%.2f", key="fill_price")
    balance_before = st.number_input("Balance Before", format="%.2f", key="balance_before")
with c4:
    mll = st.number_input("MLL", format="%.2f", key="mll", help="Maximum Loss Limit or Personal Daily Loss Limit")
    violation_time = st.text_input("Violation Time", placeholder="YYYY-MM-DD HH:MM:SS", key="violation_time")

# --- Calculations Section ---
tick_value = INSTRUMENTS[instrument]["Tick Value"]
ticks_per_pt = INSTRUMENTS[instrument]["Ticks per Pt"]

if qty > 0:
    direction = "Long"
elif qty < 0:
    direction = "Short"
else:
    direction = "Flat"

price_diff = abs(high_low - fill_price)
mae = - (price_diff * tick_value * ticks_per_pt * abs(qty))

dist_2_mll = balance_before - mll
difference = dist_2_mll + mae  

is_invalid_violation = abs(mae) <= dist_2_mll
status = "Invalid" if is_invalid_violation else "Valid Violation"

# --- Output Section ---
st.subheader("Calculation Results")

st.write(f"**Calculated Tick Value:** {tick_value:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Calculated Ticks per Pt:** {ticks_per_pt:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Direction:** {direction}")

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("MAE", f"${mae:,.2f}", help="Maximum Adverse Excursion")
metric_col2.metric("Distance to MLL", f"${dist_2_mll:,.2f}")
metric_col3.metric("Difference", f"${difference:,.2f}")

if is_invalid_violation:
    st.error(f"**Status:** {status} - The loss did not exceed the MLL distance.")
else:
    st.success(f"**Status:** {status} - The MLL limit was breached!")

# --- Copy to Clipboard Summary ---
st.divider()

summary_text = f"""--- MLL Checker Summary ---
Instrument: {instrument} ({direction})
Quantity: {qty}
Fill Price: {fill_price:.2f}
Close Price: {close_price:.2f}
{clean_label}: {high_low:.2f}
Balance Before: {balance_before:.2f}
MLL: {mll:.2f}
Violation Time: {violation_time}

--- Results ---
MAE: ${mae:.2f}
Distance to MLL: ${dist_2_mll:.2f}
Difference: ${difference:.2f}
Status: {status}
"""

with st.expander("📄 View / Copy Text Summary"):
    st.caption("Hover over the top right corner of the box below and click the 'Copy' icon to copy this data.")
    st.code(summary_text, language="text")
