"""
forward_test.py — scorecard for the Exp4 trailing-exit forward test.

The walk-forward holdout was spent, so the live paper account is the one
honest out-of-sample test of the trailing-exit configuration. This script
measures it: account return vs SPY buy-and-hold since the pre-registered
baseline date (the day the bot switched to trailing exits).

Run with:
    python forward_test.py

Judge after MONTHS, not days. The pre-registered decision rule:
  * sustained positive alpha vs SPY after ~6 months -> Exp4 supported
  * negative alpha -> Exp4 refuted, same as the backtests predicted
"""
from datetime import datetime

import pandas as pd

from broker import Broker

BASELINE_DATE = "2026-06-11"   # trailing exits went live 11:13 MT this day


def main():
    b = Broker()

    hist = b.get_portfolio_history(period="6M", timeframe="1D")
    if "error" in hist:
        print(f"could not fetch portfolio history: {hist['error']}")
        return

    eq = pd.DataFrame({
        "date":   pd.to_datetime(hist["timestamp"], unit="s").date,
        "equity": hist["equity"],
    })
    base_rows = eq[eq["date"] >= datetime.fromisoformat(BASELINE_DATE).date()]
    if base_rows.empty:
        print(f"no account history on/after {BASELINE_DATE} yet.")
        return
    base_equity = base_rows["equity"].iloc[0]
    cur_equity  = eq["equity"].iloc[-1]

    spy = pd.DataFrame(b.get_bars("SPY", "1Day", limit=200))
    spy["date"] = pd.to_datetime(spy["timestamp"]).dt.date
    spy_base_rows = spy[spy["date"] >= datetime.fromisoformat(BASELINE_DATE).date()]
    if spy_base_rows.empty:
        print("no SPY bars since baseline yet.")
        return
    spy_base = spy_base_rows["close"].iloc[0]
    spy_cur  = spy["close"].iloc[-1]

    acct_ret = (cur_equity / base_equity - 1) * 100
    spy_ret  = (spy_cur / spy_base - 1) * 100
    alpha    = acct_ret - spy_ret
    n_days   = len(base_rows)

    print("=" * 64)
    print(" EXP4 FORWARD TEST — trailing exits, live paper account")
    print("=" * 64)
    print(f"  baseline:           {BASELINE_DATE}  (${base_equity:,.2f})")
    print(f"  trading days since: {n_days}")
    print(f"  account:            ${cur_equity:,.2f}  ({acct_ret:+.2f}%)")
    print(f"  SPY buy-and-hold:   {spy_ret:+.2f}%")
    print(f"  ALPHA (acct - SPY): {alpha:+.2f}%")
    print("=" * 64)
    if n_days < 40:
        print(f"  note: {n_days} trading days is NOISE. The pre-registered")
        print("  decision point is ~6 months of data. Do not react to this.")
    print()


if __name__ == "__main__":
    main()
