"""
Streamlit dashboard for the swing trading bot.

Run with:
    streamlit run dashboard.py

Opens a browser tab at http://localhost:8501 showing:
  - Account snapshot from Alpaca (equity, cash, positions, P&L)
  - Proposal history from logs/proposals.jsonl
  - Stats: total proposals, approval rate, by symbol, over time
"""
import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from config import CONFIG
from broker import Broker


# ────────────────────────────────────────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────────────────────────────────────────

def load_proposals() -> pd.DataFrame:
    path = os.path.join(CONFIG.log_dir, "proposals.jsonl")
    if not os.path.exists(path):
        return pd.DataFrame()
    rows = []
    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "update" in entry:
                continue
            rows.append(entry)
    df = pd.DataFrame(rows)
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp", ascending=False)
    return df


@st.cache_data(ttl=30)
def get_account_snapshot():
    broker = Broker()
    return {
        "account":   broker.get_account(),
        "positions": broker.get_positions(),
        "mode":      "PAPER" if CONFIG.paper else "LIVE",
    }


# ────────────────────────────────────────────────────────────────────────────────
# Page setup
# ────────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Swing Bot Dashboard", page_icon="📈", layout="wide")
st.title("📈 Swing Trading Bot — Dashboard")
st.caption(f"Reading from `{CONFIG.log_dir}/proposals.jsonl` — last refreshed {datetime.now().strftime('%H:%M:%S')}")

# Bot heartbeat freshness — green if the loop wrote within the last ~75 min,
# red if older (likely hung). 75 min covers a normal 1-hour cycle plus slack.
_hb_path = os.path.join(CONFIG.log_dir, "heartbeat.txt")
if os.path.exists(_hb_path):
    try:
        with open(_hb_path) as _hf:
            _hb_age = (datetime.now() - datetime.fromisoformat(_hf.read().strip())).total_seconds()
        if _hb_age < 4500:
            st.success(f"🟢 Bot alive — last heartbeat {int(_hb_age // 60)} min ago")
        else:
            _h, _m = int(_hb_age // 3600), int((_hb_age % 3600) // 60)
            st.error(f"🔴 Bot may be hung — last heartbeat {_h}h {_m}m ago. Check the bot terminal window.")
    except (ValueError, OSError):
        st.warning("Heartbeat file present but unreadable.")
else:
    st.info("No heartbeat file yet — the bot writes one on each loop iteration.")

# ────────────────────────────────────────────────────────────────────────────────
# Sidebar: account + positions
# ────────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Account")
    try:
        snap = get_account_snapshot()
        acct = snap["account"]
        mode = snap["mode"]

        if mode == "PAPER":
            st.success(f"Mode: {mode}")
        else:
            st.warning(f"Mode: {mode}")

        st.metric("Equity",        f"${acct['equity']:,.2f}")
        st.metric("Cash",          f"${acct['cash']:,.2f}")
        st.metric("Buying Power",  f"${acct['buying_power']:,.2f}")
        st.metric("Day Trades",    acct.get("daytrade_count", 0))

        st.divider()
        st.subheader("Open Positions")
        positions = snap["positions"]
        if not positions:
            st.info("No open positions yet.")
        else:
            for p in positions:
                pl = p["unrealized_pl"]
                plpc = p["unrealized_plpc"] * 100
                arrow = "🟢" if pl >= 0 else "🔴"
                st.markdown(f"**{arrow} {p['symbol']}** — {int(p['qty'])} shares")
                st.markdown(f"&nbsp;&nbsp;Entry: `${p['avg_entry_price']:.2f}` → Now: `${p['current_price']:.2f}`")
                st.markdown(f"&nbsp;&nbsp;P&L: `${pl:+,.2f}` ({plpc:+.2f}%)", unsafe_allow_html=True)
                st.markdown("&nbsp;")
    except Exception as e:
        st.error(f"Could not fetch account: {e}")

    st.divider()
    st.caption("Refreshes when you rerun (top-right ⋮ → Rerun) or after 30s cache expires.")

# ────────────────────────────────────────────────────────────────────────────────
# Main panel: proposals
# ────────────────────────────────────────────────────────────────────────────────

proposals = load_proposals()

if proposals.empty:
    st.info("No proposals yet. Run `python main.py once` from the project folder to generate one, then refresh this page.")
    st.stop()

# Summary metrics
total = len(proposals)
approved = int(proposals["risk_approved"].sum()) if "risk_approved" in proposals.columns else 0
rejected = total - approved
buys = int((proposals["side"] == "buy").sum()) if "side" in proposals.columns else 0
sells = int((proposals["side"] == "sell").sum()) if "side" in proposals.columns else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total proposals", total)
c2.metric("Risk-approved",   approved)
c3.metric("Risk-rejected",   rejected)
c4.metric("Buy proposals",   buys)
c5.metric("Sell proposals",  sells)

st.divider()

# ── Benchmark: account equity vs SPY buy-and-hold ───────────────────────────────
# THE metric that matters: is the bot beating just buying and holding SPY?
st.subheader("Account vs SPY buy-and-hold")
try:
    bench_broker = Broker()
    hist = bench_broker.get_portfolio_history(period="1M", timeframe="1D")
    if "error" in hist or len(hist.get("equity", [])) < 2:
        st.info(
            "Not enough account history yet for a benchmark comparison. "
            "This chart becomes meaningful after a week or two of trading days — check back."
        )
    else:
        eq = hist["equity"]
        ts = hist["timestamp"]
        # Use plain date objects (no timezone) on both sides so the merge below
        # doesn't fail comparing tz-aware SPY timestamps to tz-naive epoch ones.
        acct_df = pd.DataFrame({
            "date":    pd.to_datetime(ts, unit="s").date,
            "Account": eq,
        })
        spy_bars = bench_broker.get_bars("SPY", "1Day", limit=max(len(eq) + 5, 10))
        if spy_bars:
            spy_df = pd.DataFrame(spy_bars)
            spy_df["date"] = pd.to_datetime(spy_df["timestamp"]).dt.date
            spy_df = spy_df[["date", "close"]]
            merged = pd.merge(acct_df, spy_df, on="date", how="left").sort_values("date")
            merged["close"] = merged["close"].ffill().bfill()
            # Normalize SPY so it "starts" at the account's first equity value —
            # this answers: if I'd put the same money in SPY instead, where would I be?
            start_equity = merged["Account"].iloc[0]
            spy_start = merged["close"].iloc[0]
            merged["SPY buy-and-hold"] = merged["close"] / spy_start * start_equity
            st.line_chart(merged.set_index("date")[["Account", "SPY buy-and-hold"]])

            acct_ret = (merged["Account"].iloc[-1] / merged["Account"].iloc[0] - 1) * 100
            spy_ret  = (merged["close"].iloc[-1]   / merged["close"].iloc[0]   - 1) * 100
            b1, b2, b3 = st.columns(3)
            b1.metric("Your account return", f"{acct_ret:+.2f}%")
            b2.metric("SPY buy-and-hold",    f"{spy_ret:+.2f}%")
            b3.metric("Alpha (you − SPY)",   f"{acct_ret - spy_ret:+.2f}%")
        else:
            st.line_chart(acct_df.set_index("date"))
except Exception as e:
    st.warning(f"Benchmark unavailable: {e}")

st.divider()

# Charts
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Proposals per day")
    if "timestamp" in proposals.columns:
        daily = (proposals.assign(date=proposals["timestamp"].dt.date)
                          .groupby("date").size().rename("count"))
        st.bar_chart(daily)
with col_b:
    st.subheader("Proposals by symbol")
    if "symbol" in proposals.columns:
        by_sym = proposals.groupby("symbol").size().rename("count").sort_values(ascending=False)
        st.bar_chart(by_sym)

st.divider()

# Risk decision breakdown
if "risk_message" in proposals.columns:
    st.subheader("Why proposals were rejected")
    rej = proposals[proposals["risk_approved"] == False]  # noqa: E712
    if len(rej) == 0:
        st.success("No rejections in the log.")
    else:
        msgs = rej["risk_message"].value_counts().head(10)
        st.bar_chart(msgs)

st.divider()

# Detailed table
st.subheader("All proposals (most recent first)")
display_cols = [c for c in ["timestamp", "symbol", "side", "qty", "risk_approved", "status", "executed", "reason"]
                if c in proposals.columns]
st.dataframe(proposals[display_cols], use_container_width=True, hide_index=True)

# ── Bot journal — what the Position Manager recorded each cycle ──
st.divider()
st.subheader("🤖 Bot journal — what the bots have been doing")
_jpath = os.path.join(CONFIG.log_dir, "journal.jsonl")
_jrows = []
if os.path.exists(_jpath):
    with open(_jpath) as _jf:
        for _line in _jf:
            try:
                _jrows.append(json.loads(_line))
            except json.JSONDecodeError:
                continue
if _jrows:
    for _entry in reversed(_jrows[-15:]):
        _ts = str(_entry.get("timestamp", ""))[:16].replace("T", " ")
        st.markdown(f"**{_ts}**  —  {_entry.get('note', '')}")
else:
    st.info("No journal entries yet — the Position Manager writes one each cycle once the bot runs.")

st.caption(
    "Reminder: paper trades. Approval rates and proposal counts mean little until you've collected "
    "60-90+ days of data and compared to SPY buy-and-hold over the same window."
)
