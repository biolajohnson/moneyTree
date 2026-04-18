import streamlit as st
import plotly.graph_objects as go
from datetime import date, datetime
from collections import defaultdict
import pytz

from backend.database import (
    init_db, list_stocks, get_stock,
    insert_stock, delete_stock, get_history,
    upsert_snapshot, get_all_tickers,
)
from backend.fetcher import fetch_metadata, fetch_live_pe, backfill_history

ET = pytz.timezone("US/Eastern")

init_db()

st.set_page_config(
    page_title="MoneyTree",
    page_icon="🌳",
    layout="wide",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_t  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= now <= close_t


def pe_color(pe) -> str:
    if pe is None:
        return "#7a7f9a"
    if pe < 15:
        return "#22c55e"
    if pe <= 30:
        return "#eab308"
    return "#ef4444"


def fmt(val, decimals=2) -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}"


@st.cache_data(ttl=3600, show_spinner=False)
def cached_history(ticker: str) -> dict:
    rows = get_history(ticker, days=90)
    if not rows:
        return {"history": [], "avg_pe": None, "spike_threshold": None}
    pes = [r["trailing_pe"] for r in rows if r["trailing_pe"] is not None]
    avg_pe = round(sum(pes) / len(pes), 2) if pes else None
    spike_threshold = round(avg_pe * 1.2, 2) if avg_pe else None
    for r in rows:
        r["is_spike"] = (
            r["trailing_pe"] is not None
            and spike_threshold is not None
            and r["trailing_pe"] > spike_threshold
        )
    return {"history": rows, "avg_pe": avg_pe, "spike_threshold": spike_threshold}


def build_pe_chart(ticker: str, history_data: dict) -> go.Figure:
    rows = history_data["history"]
    spike_threshold = history_data["spike_threshold"]

    dates  = [r["date"] for r in rows]
    pes    = [r["trailing_pe"] for r in rows]
    spikes = [r.get("is_spike", False) for r in rows]

    normal_x = [d for d, s in zip(dates, spikes) if not s]
    normal_y = [p for p, s in zip(pes,   spikes) if not s]
    spike_x  = [d for d, s in zip(dates, spikes) if s]
    spike_y  = [p for p, s in zip(pes,   spikes) if s]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates, y=pes,
        mode="lines",
        line=dict(color="#6366f1", width=1.5),
        hovertemplate="%{x}<br>P/E: %{y:.1f}<extra></extra>",
        showlegend=False,
    ))

    if normal_x:
        fig.add_trace(go.Scatter(
            x=normal_x, y=normal_y,
            mode="markers",
            marker=dict(color="#6366f1", size=4),
            hovertemplate="%{x}<br>P/E: %{y:.1f}<extra></extra>",
            showlegend=False,
        ))

    if spike_x:
        fig.add_trace(go.Scatter(
            x=spike_x, y=spike_y,
            mode="markers",
            marker=dict(color="#ef4444", size=7, symbol="circle"),
            name="Spike",
            hovertemplate="%{x}<br>P/E: %{y:.1f} ⚠️ spike<extra></extra>",
        ))

    if spike_threshold:
        fig.add_hline(
            y=spike_threshold,
            line_dash="dot",
            line_color="rgba(239,68,68,0.4)",
            annotation_text=f"spike >{spike_threshold:.1f}",
            annotation_position="bottom right",
            annotation_font_size=10,
            annotation_font_color="#ef4444",
        )

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=160,
        xaxis=dict(showgrid=False, showticklabels=True, tickfont=dict(size=9, color="#7a7f9a")),
        yaxis=dict(gridcolor="rgba(46,51,80,.4)", tickfont=dict(size=9, color="#7a7f9a")),
        legend=dict(font=dict(size=10, color="#7a7f9a"), bgcolor="rgba(0,0,0,0)"),
        showlegend=bool(spike_x),
    )
    return fig


# ── CSS overrides ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #0f1117; }
  [data-testid="stHeader"] { background: #1a1d27; border-bottom: 1px solid #2e3350; }
  section.main > div { padding-top: 1rem; }
  .metric-box {
    background: #1a1d27;
    border: 1px solid #2e3350;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 4px;
  }
  .metric-label { font-size: 10px; color: #7a7f9a; text-transform: uppercase; letter-spacing: .6px; }
  .metric-value { font-size: 22px; font-weight: 700; margin-top: 2px; }
  .card-container {
    background: #1a1d27;
    border: 1px solid #2e3350;
    border-radius: 10px;
    padding: 16px 18px 10px;
    margin-bottom: 14px;
  }
  .ticker-label { font-size: 17px; font-weight: 700; color: #e8eaf0; }
  .company-label { font-size: 12px; color: #7a7f9a; }
  .sector-heading {
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .8px; color: #7a7f9a;
    border-bottom: 1px solid #2e3350;
    padding-bottom: 6px; margin: 24px 0 14px;
  }
  div[data-testid="stExpander"] { border: none !important; }
</style>
""", unsafe_allow_html=True)


# ── Header ────────────────────────────────────────────────────────────────────

col_title, col_right = st.columns([7, 3])
with col_title:
    st.markdown("## 🌳 MoneyTree")
with col_right:
    col_status, col_refresh = st.columns([2, 1])
    with col_status:
        if is_market_open():
            st.success("Market Open", icon="🟢")
        else:
            st.warning("Market Closed", icon="🔴")
    with col_refresh:
        st.markdown("<div style='padding-top:6px'>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            tickers = get_all_tickers()
            with st.spinner("Refreshing…"):
                today = date.today().isoformat()
                for t in tickers:
                    try:
                        data = fetch_live_pe(t)
                        upsert_snapshot(t, today,
                            data.get("price"), data.get("trailing_eps"),
                            data.get("trailing_pe"), data.get("forward_pe"))
                    except Exception:
                        pass
            st.cache_data.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()

# ── Sidebar: Add / Remove ──────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ➕ Add Stock")
    new_ticker = st.text_input("Ticker symbol", placeholder="e.g. AAPL", max_chars=10).strip().upper()
    if st.button("Add to Watchlist", use_container_width=True):
        if not new_ticker:
            st.error("Enter a ticker first.")
        elif get_stock(new_ticker):
            st.warning(f"{new_ticker} is already in your watchlist.")
        else:
            with st.spinner(f"Fetching {new_ticker}…"):
                try:
                    meta = fetch_metadata(new_ticker)
                    raw_info = meta.pop("_info")  # reuse so we don't call Yahoo again
                    insert_stock(
                        ticker=meta["ticker"],
                        company=meta["company"],
                        sector=meta["sector"],
                        added_at=date.today().isoformat(),
                    )
                    backfill_history(new_ticker, info=raw_info)
                    st.cache_data.clear()
                    st.success(f"Added {new_ticker}!")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    st.divider()
    st.markdown("### 🗑️ Remove Stock")
    stocks_list = list_stocks()
    if stocks_list:
        remove_choice = st.selectbox(
            "Select stock to remove",
            options=[s["ticker"] for s in stocks_list],
            format_func=lambda t: f"{t} — {next((s['company'] for s in stocks_list if s['ticker']==t), '')}",
        )
        if st.button("Remove", use_container_width=True, type="secondary"):
            delete_stock(remove_choice)
            st.cache_data.clear()
            st.rerun()
    else:
        st.caption("No stocks yet.")


# ── Dashboard ─────────────────────────────────────────────────────────────────

stocks = list_stocks()

if not stocks:
    st.info("No stocks in your watchlist. Use the sidebar to add one.", icon="🌱")
    st.stop()

grouped = defaultdict(list)
for s in stocks:
    grouped[s["sector"]].append(s)

for sector in sorted(grouped.keys()):
    st.markdown(f'<div class="sector-heading">{sector}</div>', unsafe_allow_html=True)

    sector_stocks = grouped[sector]
    cols = st.columns(min(len(sector_stocks), 3))

    for i, stock in enumerate(sector_stocks):
        ticker  = stock["ticker"]
        company = stock["company"]

        with cols[i % 3]:
            with st.container():
                st.markdown(
                    f'<div class="ticker-label">{ticker}</div>'
                    f'<div class="company-label">{company}</div>',
                    unsafe_allow_html=True,
                )

                # Read latest values from SQLite — no live Yahoo Finance call
                hist_data = cached_history(ticker)
                latest = hist_data["history"][-1] if hist_data["history"] else {}
                price       = latest.get("price")
                trailing_pe = latest.get("trailing_pe")
                forward_pe  = latest.get("forward_pe")
                as_of       = latest.get("date", "")

                m1, m2, m3 = st.columns(3)
                m1.metric("Price", f"${fmt(price)}")
                m2.metric("Trailing P/E", fmt(trailing_pe, 1),
                          help="Green <15 · Yellow 15–30 · Red >30")
                m3.metric("Forward P/E", fmt(forward_pe, 1))
                if as_of:
                    st.caption(f"as of {as_of}" + (" · market closed" if not is_market_open() else ""))

                if hist_data["history"]:
                    fig = build_pe_chart(ticker, hist_data)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    if hist_data["avg_pe"]:
                        st.caption(f"90-day avg P/E: {hist_data['avg_pe']:.1f} · spike threshold: {hist_data['spike_threshold']:.1f}")
                else:
                    st.caption("No history yet.")

                st.markdown("---")
