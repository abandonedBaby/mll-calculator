import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from streamlit_gsheets import GSheetsConnection
import urllib.request
import xml.etree.ElementTree as ET
import datetime
import requests

st.set_page_config(
    page_title="Trade Violation Checker", 
    page_icon="🚨", 
    layout="wide"
)

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

def send_telegram_alert(error_message, pasted_data):
    """Sends a silent error log to your Telegram account."""
    bot_token = st.secrets.get("telegram_token")
    chat_id = st.secrets.get("telegram_chat_id")
    
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        # Truncate pasted data so it doesn't send a massive text wall
        truncated_data = pasted_data[:300] + "..." if len(pasted_data) > 300 else pasted_data
        
        message = f"🚨 **App Error Alert**\n{error_message}\n\n**Raw Pasted Text:**\n`{truncated_data}`"
        
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass # Fails silently so it doesn't interrupt the user's workflow!

# --- 3. Optimized Google Sheets Connection ---
# Define connection globally so we can use it for both tabs
conn = st.connection("gsheets", type=GSheetsConnection)

if "instruments_df" not in st.session_state or getattr(st.session_state, 'force_refresh', True):
    try:
        df = conn.read(worksheet="Instruments", ttl="0m").dropna(how="all")
        st.session_state.instruments_df = df if not df.empty else pd.DataFrame(DEFAULT_INSTRUMENTS)
    except Exception as e:
        st.session_state.instruments_df = pd.DataFrame(DEFAULT_INSTRUMENTS)
        st.sidebar.error(f"⚠️ Instruments Sheets Error: {e}")
    st.session_state.force_refresh = False

INSTRUMENTS = {}
for _, row in st.session_state.instruments_df.dropna(subset=["Instrument"]).iterrows():
    name = str(row["Instrument"]).strip()
    if not name: continue
    val_per_pt, tick_size = float(row.get("Value per point", 0)), float(row.get("Tick Size", 0))
    INSTRUMENTS[name] = {"Tick Value": val_per_pt * tick_size, "Ticks per Pt": 1 / tick_size if tick_size else 0}

if not INSTRUMENTS: INSTRUMENTS["None"] = {"Tick Value": 0.0, "Ticks per Pt": 0.0}

# --- 4. Helper Functions (News Fetcher & Auto-Archive) ---
@st.cache_data(ttl="1h")
def fetch_live_news():
    """Fetches the current WEEK of Forex Factory high impact USD events."""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
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
                        dt_obj = pd.to_datetime(dt_str).tz_localize('US/Eastern')
                        events.append({'title': title, 'Event_Time': dt_obj})
                    except Exception:
                        pass
        return pd.DataFrame(events)
    except Exception:
        return pd.DataFrame() 

def sync_news_archive():
    """Reads GSheets Archive, fetches new events, appends if missing, and returns the unified list."""
    live_df = fetch_live_news()
    
    try:
        archive_df = conn.read(worksheet="News_Archive", ttl="0m").dropna(how="all")
    except Exception:
        archive_df = pd.DataFrame(columns=["title", "Event_Time"])

    if not live_df.empty:
        # 1. Clean Live Data (Strip invisible spaces & standardize time format)
        live_df['title'] = live_df['title'].astype(str).str.strip()
        live_df['Event_Time'] = pd.to_datetime(live_df['Event_Time'], errors='coerce')
        live_df['Event_Time'] = live_df['Event_Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 2. Clean Archive Data
        if not archive_df.empty and 'Event_Time' in archive_df.columns:
            archive_df['title'] = archive_df['title'].astype(str).str.strip()
            archive_df['Event_Time'] = pd.to_datetime(archive_df['Event_Time'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 3. Combine Everything into one list
        combined_df = pd.concat([archive_df, live_df], ignore_index=True)
        combined_df = combined_df.dropna(subset=['Event_Time', 'title'])
        
        # 4. SLEDGEHAMMER DEDUPLICATION
        # Extract just the YYYY-MM-DD. If Title + Date matches an existing entry, delete it!
        combined_df['Date_Only'] = pd.to_datetime(combined_df['Event_Time']).dt.date
        combined_df = combined_df.drop_duplicates(subset=['title', 'Date_Only'], keep='first')
        combined_df = combined_df.drop(columns=['Date_Only'])
        
        # 5. Save the perfectly clean list back to Google Sheets
        upload_df = combined_df.copy()
        upload_df['title'] = upload_df['title'].astype(str)
        upload_df['Event_Time'] = upload_df['Event_Time'].astype(str)
        
        try:
            conn.update(worksheet="News_Archive", data=upload_df)
        except Exception:
            pass
            
        archive_df = combined_df

    # Rehydrate the data into usable Timezones for the Violation Checker
    if not archive_df.empty and 'Event_Time' in archive_df.columns:
        archive_df['Event_Time'] = pd.to_datetime(archive_df['Event_Time'])
        if archive_df['Event_Time'].dt.tz is None:
            archive_df['Event_Time'] = archive_df['Event_Time'].dt.tz_localize('US/Eastern')
        return archive_df.sort_values(by='Event_Time', ascending=False).reset_index(drop=True)
        
    return pd.DataFrame()

# Load News into Session State to prevent lag!
if "news_archive_df" not in st.session_state or getattr(st.session_state, 'force_news_refresh', True):
    st.session_state.news_archive_df = sync_news_archive()
    st.session_state.force_news_refresh = False

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
            else: 
                err_msg = "Total quantity calculated as 0."
                st.error(err_msg)
                send_telegram_alert(err_msg, pasted_text)
        else: 
            err_msg = "No valid data found in Columns H and K."
            st.error(err_msg)
            send_telegram_alert(err_msg, pasted_text)
            
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
        else: 
            st.error("Please enter valid data.")

# --- 6. Sidebar & Header UI ---
with st.sidebar:
    st.header("🔐 Admin Access")
    is_admin = (st.text_input("Password", type="password") == st.secrets.get("admin_password", "admin123"))
    if is_admin: 
        st.success("Admin unlocked!")
        if st.button("🧹 Force Sync News Archive"):
            st.cache_data.clear()
            st.session_state.force_news_refresh = True
            st.rerun()

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

# --- ROW 1: Account & Timing Data ---
r1c1, r1c2, r1c3, r1c4 = st.columns(4)
with r1c1:
    violation_time = st.text_input("Violation Time", placeholder="YYYY-MM-DD HH:MM:SS", key="violation_time")
with r1c2:
    mll = st.number_input("Min Balance - MLL", format="%.2f", key="mll", help="Maximum Loss Limit")
with r1c3:
    balance_before = st.number_input("Balance Before", format="%.2f", key="balance_before")
with r1c4:
    instrument = st.selectbox("Instrument", options=list(INSTRUMENTS.keys()))

# --- ROW 2: Execution Data ---
r2c1, r2c2, r2c3, r2c4 = st.columns(4)
with r2c1:
    qty = st.number_input("Quantity (Qty)", step=1, key="qty")
with r2c2:
    fill_price = st.number_input("Fill Price (Avg)", format="%.2f", key="fill_price")
with r2c3:
    close_price = st.number_input("Close Price", format="%.2f", key="close_price")
with r2c4:
    high_low = st.number_input(hl_label, format="%.2f", key="high_low", help=hl_help)

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

# --- 8.1 STATUS NOTIFICATION ---
if is_invalid: st.error("**Status:** Invalid - The loss did not exceed the MLL distance.")
else: st.success("**Status:** Valid Violation - The MLL limit was breached!")

# --- 8.2 ECONOMIC EVENT CHECKING (Moved up above the chart!) ---
news_warning = ""
news_df = st.session_state.news_archive_df

if violation_time.strip():
    try:
        vt_dt = pd.to_datetime(violation_time.strip()).tz_localize('US/Central')
        
        if not news_df.empty:
            for _, row in news_df.iterrows():
                event_time = row['Event_Time']
                time_diff = abs((vt_dt - event_time).total_seconds())
                if time_diff <= 60:
                    event_time_cst = event_time.tz_convert('US/Central')
                    news_warning = f"⚠️ **News Violation Warning!** This trade occurred within 1 minute of a major economic event: **{row['title']}** ({event_time_cst.strftime('%I:%M %p CST')})"
                    st.warning(news_warning, icon="🚨")
                    break
    except Exception:
        pass

# --- 8.5 VISUAL REPRESENTATION (Chart shifted to the bottom) ---
if qty != 0:
    st.divider()
    
    # Calculate how much $1 moves the price, to find the exact MLL Price Level
    dollar_per_point = t_val * t_pt * abs(qty)
    points_to_mll = dist_2_mll / dollar_per_point if dollar_per_point != 0 else 0
    
    # Set dynamic colors AND smart text label positioning
    if direction == "Long":
        mll_price = fill_price - points_to_mll
        path_color = "#00d26a" # Greenish
        label_positions = ["top center", "bottom center", "top center"]
    else:
        mll_price = fill_price + points_to_mll
        path_color = "#f94144" # Reddish
        label_positions = ["bottom center", "top center", "bottom center"]
        
    # Build the Chart
    fig = go.Figure()
    
    # The Simulated Trade Path (V-shape)
    fig.add_trace(go.Scatter(
        x=["1. Entry", "2. Max Excursion (MAE)", "3. Exit"],
        y=[fill_price, high_low, close_price],
        mode='lines+markers+text',
        text=[f"Entry: {fill_price:.2f}", f"MAE: {high_low:.2f}", f"Exit: {close_price:.2f}"], 
        textposition=label_positions,
        textfont=dict(size=14, color="white"),
        name='Trade Path',
        marker=dict(size=14, color=['#4361ee', '#f94144' if is_invalid else '#f9c74f', '#4361ee']),
        line=dict(width=4, color=path_color),
        hovertemplate="<b>%{x}</b><br>Price: %{y:.2f}<extra></extra>"
    ))
    
    # The MLL Limit Line (Dashed Red Line)
    fig.add_hline(
        y=mll_price, 
        line_dash="dash", 
        line_color="#f94144", 
        line_width=2,
        annotation_text=f"🚨 MLL Level: {mll_price:.2f}", 
        annotation_position="bottom right" if direction=="Long" else "top right",
        annotation_font_color="#f94144"
    )
    
    # Chart Layout & Styling
    fig.update_layout(
        title="Trade Excursion vs. MLL Boundary",
        yaxis=dict(side="right", title="Price Level", tickformat=".2f"),
        xaxis=dict(title="Simulated Timeline"),
        height=400,
        margin=dict(l=20, r=40, t=50, b=20),
        showlegend=False,
        hovermode="x unified"
    )
    
    # Render the chart in Streamlit
    st.plotly_chart(fig, use_container_width=True)

# --- 10. Clipboard Summary ---
st.divider()
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

























