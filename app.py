import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import urllib.request
import xml.etree.ElementTree as ET
import datetime

st.set_page_config(page_title="Trade Violation Checker", layout="wide")

# --- 1. Constants & Defaults ---
DEFAULT_INSTRUMENTS = [
    {"Instrument": "NQ", "Value per point": 20.0, "Tick Size": 0.25},
    {"Instrument": "ES", "Value per point": 50.0, "Tick Size": 0.25},
]

STATE_DEFAULTS = {
    "qty": 2, "fill_price": 24798.25, "close_price": 24845.75,
    "high_low": 24848.00, "balance_before": 0.00, "mll": -2000.00,
    "violation_time": ""
}

# --- 2. Session State Management ---
for key, val in STATE_DEFAULTS.items():
    if key not in st.session_state: st.session_state[key] = val

if "fill_data" not in st.session_state:
    st.session_state.fill_data = pd.DataFrame([{"Qty": 1, "Price": 24798.25}, {"Qty": 1, "Price": 24800.00}])

def clear_all():
    for key in STATE_DEFAULTS.keys():
        st.session_state[key] = "" if key == "violation_time" else 0.00
    st.session_state.qty = 0
    st.session_state.fill_data = pd.DataFrame([{"Qty": 0, "Price": 0.00}])

# --- 3. Optimized Google Sheets Connection ---
if "instruments_df" not in st.session_state or getattr(st.session_state, 'force_refresh', True):
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(worksheet="Instruments", ttl="0m").dropna(how="all")
        st.session_state.instruments_df = df if not df.empty else pd.DataFrame(DEFAULT_INSTRUMENTS)
    except Exception as e:
        st.session_state.instruments_df = pd.DataFrame(DEFAULT_INSTRUMENTS)
        st.sidebar.error(f"⚠️ Sheets Error: {e}")
    st.session_state.force_refresh = False

INSTRUMENTS = {}
for _, row in st.session_state.instruments_df.dropna(subset=["Instrument"]).iterrows():
    name = str(row["Instrument"]).strip()
    if not name: continue
    val_per_pt, tick_size = float(row.get("Value per point", 0)), float(row.get("Tick Size", 0))
    INSTRUMENTS[name] = {"Tick Value": val_per_pt * tick_size, "Ticks per Pt": 1 / tick_size if tick_size else 0}

if not INSTRUMENTS: INSTRUMENTS["None"] = {"Tick Value": 0.0, "Ticks per Pt": 0.0}

# --- 4. Helper Functions (News Fetcher & Data Parser) ---
@st.cache_data(ttl="1h")
def fetch_usd_high_impact_news():
    """Fetches Forex Factory calendar, filters for High Impact USD, and makes it US/Eastern timezone aware."""
    url = "https://nfs.faireconomy.media/ff_calendar_thismonth.xml"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    events = []
    
    try:
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        for event in root.findall('event'):
            country = event.find('country').text if event.find('country') is not None else ""
            impact = event.find('impact').text if event.find('impact') is not None else ""
            
            if country == 'USD' and impact == 'High':
                title = event.find('title').text
                date_str = event.find('date').text
                time_str = event.find('time').text
                
                if time_str and 'All Day' not in time_str and 'Tentative' not in time_str:
                    try:
                        dt_str = f"{date_str} {time_str}"
                        # Removed the strict format parameter so pandas can automatically handle missing leading zeros!
                        dt_obj = pd.to_datetime(dt_str).tz_localize('US/Eastern')
                        events.append({'title': title, 'Event_Time': dt_obj})
                    except Exception as e:
                        print(f"Failed to parse date: {dt_str} - {e}")
        return pd.DataFrame(events)
    except Exception as e:
        return pd.DataFrame() 

def parse_pasted_data(text):
    rows = []
    for line in text.strip().split('\n'):
        cols = line.split('\t')
        if len(cols) >= 11:
            try:
                q, p = float(cols[7].replace(',', '')), float(cols[10].replace(',', ''))
                if q != 0: rows.append({"Qty": q, "Price": p})
            except ValueError: pass
    return rows

# --- 5. Dialogs ---
@st.dialog("⚙️ Manage Instruments")
def manage_instruments_dialog():
    st.markdown("Add, edit, or delete instruments. Changes sync to Google Sheets.")
    edited_df = st.data_editor(st.session_state.instruments_df, num_rows="dynamic", use_container_width=True, hide_index=True)
    if st.button("Save to Cloud", type="primary"):
        cleaned_df = edited_df.dropna(subset=["Instrument"])
        cleaned_df = cleaned_df[cleaned_df["Instrument"].astype(str).str.strip() != ""]
        try:
            conn = st.connection("gsheets", type=GSheetsConnection)
            conn.update(worksheet="Instruments", data=cleaned_df)
            st.session_state.force_refresh = True 
            st.rerun()
        except Exception:
            st.error("Failed to save to Google Sheets.")

@st.dialog("Calculate Weighted Average Fill")
def weighted_average_dialog():
    st.markdown("Enter multiple fills manually, or **paste raw tab-delimited data**.")
    pasted_text = st.text_area("📋 Quick Paste", placeholder="Paste rows here...", height=100)
    
    if st.button("🚀 Extract & Apply", type="primary"):
        parsed_rows = parse_pasted_data(pasted_text)
        if parsed_rows:
            df = pd.DataFrame(parsed_rows)
            total_q = int(df["Qty"].sum())
            if total_q != 0:
                st.session_state.qty = total_q
                st.session_state.fill_price = float((df["Qty"] * df["Price"]).sum() / total_q)
                st.session_state.fill_data = df 
                st.rerun()
            else: st.error("Total quantity is 0.")
        else: st.error("No valid data found in Columns H and K.")
            
    st.divider()
    st.caption("Or edit rows manually:")
    edited_df = st.data_editor(st.session_state.fill_data, num_rows="dynamic", use_container_width=True, hide_index=True)
    
    if st.button("Calculate & Apply Manual Edits"):
        valid = edited_df[(edited_df["Qty"] != 0) & (edited_df["Price"] > 0)]
        if not valid.empty:
            total_q = int(valid["Qty"].sum())
            st.session_state.qty = total_q
            st.session_state.fill_price = float((valid["Qty"] * valid["Price"]).sum() / total_q)
            st.session_state.fill_data = edited_df 
            st.rerun() 
        else: st.error("Please enter valid data.")

# --- 6. Sidebar & Header UI ---
with st.sidebar:
    st.header("🔐 Admin Access")
    is_admin = (st.text_input("Password", type="password") == st.secrets.get("admin_password", "admin123"))
    if is_admin: 
        st.success("Admin unlocked!")
        if st.button("🧹 Clear News Cache"):
            st.cache_data.clear()
            st.success("Cache cleared! The app will pull fresh news data.")

# Renamed the Title!
st.title("📊 Trade Violation Checker")

# Renamed the Title!
st.title("📊 Trade Violation Checker")
st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 1rem; }
        h1 { font-size: clamp(1.5rem, 4vw, 2.5rem) !important; padding-top: 0 !important; margin-bottom: -1.5rem;}
        div[data-testid="stMetricValue"] { font-size: 1.5rem; }
        hr { margin-top: 0.5rem; margin-bottom: 0.5rem; }
    </style>
""", unsafe_allow_html=True)

btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    if st.button("🧮 Add Multiple Entries"): weighted_average_dialog()
with btn_col2:
    if is_admin and st.button("⚙️ Manage Instruments"): manage_instruments_dialog()
with btn_col3:
    if st.button("🗑️ Clear All"): clear_all()

# --- 7. Main Inputs ---
st.subheader("Trade Details")
curr_qty = st.session_state.qty

hl_label, hl_help, clean_label = ("High/Low", "Enter adverse excursion price.", "High/Low")
if curr_qty > 0: hl_label, hl_help, clean_label = ("📉 Low", "Long Adverse Excursion: Lowest price.", "Low")
elif curr_qty < 0: hl_label, hl_help, clean_label = ("📈 High", "Short Adverse Excursion: Highest price.", "High")

c1, c2, c3, c4 = st.columns(4)
with c1:
    instrument = st.selectbox("Instrument", options=list(INSTRUMENTS.keys()))
    close_price = st.number_input("Close Price", format="%.2f", key="close_price")
with c2:
    qty = st.number_input("Quantity (Qty)", step=1, key="qty")
    high_low = st.number_input(hl_label, format="%.2f", key="high_low", help=hl_help)
with c3:
    fill_price = st.number_input("Fill Price (Avg)", format="%.2f", key="fill_price")
    balance_before = st.number_input("Balance Before", format="%.2f", key="balance_before")
with c4:
    # Changed Label to "Min Balance - MLL"
    mll = st.number_input("Min Balance - MLL", format="%.2f", key="mll", help="Maximum Loss Limit")
    violation_time = st.text_input("Violation Time", placeholder="YYYY-MM-DD HH:MM:SS", key="violation_time")

# --- 8. Math & Output ---
t_val, t_pt = INSTRUMENTS[instrument]["Tick Value"], INSTRUMENTS[instrument]["Ticks per Pt"]
direction = "Flat" if qty == 0 else ("Long" if qty > 0 else "Short")

mae = - (abs(high_low - fill_price) * t_val * t_pt * abs(qty))
dist_2_mll = balance_before - mll
difference = dist_2_mll + mae  
is_invalid = abs(mae) <= dist_2_mll

st.subheader("Calculation Results")
st.write(f"**Tick Value:** {t_val:,.2f} &nbsp;|&nbsp; **Ticks per Pt:** {t_pt:,.2f} &nbsp;|&nbsp; **Direction:** {direction}")

mc1, mc2, mc3 = st.columns(3)
mc1.metric("MAE", f"${mae:,.2f}", help="Maximum Adverse Excursion")
mc2.metric("Distance to MLL", f"${dist_2_mll:,.2f}")
mc3.metric("Difference", f"${difference:,.2f}")

if is_invalid: st.error("**Status:** Invalid - The loss did not exceed the MLL distance.")
else: st.success("**Status:** Valid Violation - The MLL limit was breached!")

# --- 9. Economic Event Checking (Timezone Aware!) ---
news_warning = ""
news_df = fetch_usd_high_impact_news()

if violation_time.strip():
    try:
        # Parse the user's input and immediately lock it to US/Central
        vt_dt = pd.to_datetime(violation_time.strip()).tz_localize('US/Central')
        
        # Check against the fetched news data
        if not news_df.empty:
            for _, row in news_df.iterrows():
                event_time = row['Event_Time']
                
                # Check if violation time is within 60 seconds of the event time
                time_diff = abs((vt_dt - event_time).total_seconds())
                if time_diff <= 60:
                    # Convert the event time to Central Time just so the display matches the user's local input
                    event_time_cst = event_time.tz_convert('US/Central')
                    news_warning = f"⚠️ **News Violation Warning!** This trade occurred within 1 minute of a major economic event: **{row['title']}** ({event_time_cst.strftime('%I:%M %p CST')})"
                    st.warning(news_warning, icon="🚨")
                    break
    except Exception:
        # Fails silently if the user is typing an incomplete date
        pass

# Debug/Viewing tool for the News Feed
with st.expander("📅 View Current Week's USD High Impact News"):
    if not news_df.empty:
        # Create a display copy converted to CST for easy reading
        display_df = news_df.copy()
        display_df['Event_Time_CST'] = display_df['Event_Time'].dt.tz_convert('US/Central').dt.strftime('%Y-%m-%d %I:%M %p CST')
        st.dataframe(display_df[['title', 'Event_Time_CST']], hide_index=True, use_container_width=True)
    else:
        st.write("No High Impact USD events found for this week, or feed is currently unavailable.")

# --- 10. Clipboard Summary ---
st.divider()

# Updated label in the summary text
summary_text = f"""--- MLL Checker Summary ---
Instrument: {instrument} ({direction})
Quantity: {qty}
Fill Price: {fill_price:.2f}
Close Price: {close_price:.2f}
{clean_label}: {high_low:.2f}
Balance Before: {balance_before:.2f}
Min Balance - MLL: {mll:.2f}
Violation Time: {violation_time}

--- Results ---
MAE: ${mae:.2f}
Distance to MLL: ${dist_2_mll:.2f}
Difference: ${difference:.2f}
Status: {"Invalid" if is_invalid else "Valid Violation"}
"""

if news_warning:
    summary_text += f"\n--- Flags ---\n{news_warning}"

with st.expander("📄 View / Copy Text Summary"):
    st.caption("Hover over the top right corner to copy this data.")
    st.code(summary_text, language="text")



