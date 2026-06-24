"""
Backtest a simple swing-trading RULE against historical data.

╔════════════════════════════════════════════════════════════════════════════╗
║  READ THIS FIRST — what this does and does NOT do                          ║
╠════════════════════════════════════════════════════════════════════════════╣
║  • This backtests a SIMPLIFIED, MECHANICAL rule: buy on a pullback to a     ║
║    rising 20-day moving average while in a longer-term uptrend, with a      ║
║    fixed 6% stop and 12% target. It is a fast PROXY for the *style* of      ║
║    trade the swing bot pursues.                                            ║
║                                                                            ║
║  • It does NOT replay the actual LLM. Replaying qwen3:4b for every          ║
║    historical day would take many hours on an 8GB Mac. The LLM's real       ║
║    decisions are fuzzier than this rule — sometimes better, sometimes       ║
║    worse, and influenced by news the rule ignores.                         ║
║                                                                            ║
║  • Treat the output as a sanity check on the STRATEGY STYLE, not a          ║
║    prediction of the bot's live results. If even this clean mechanical      ║
║    rule loses to SPY buy-and-hold, that's a strong signal the whole         ║
║    approach is unlikely to beat just holding the index.                     ║
╚════════════════════════════════════════════════════════════════════════════╝

Run with:
    python backtest.py                 # all symbols in the config whitelist
    python backtest.py SPY AAPL MSFT   # only specific symbols
    python backtest.py --days 500      # change the lookback window (default 365)
"""
import sys

import pandas as pd

from config import CONFIG
from broker import Broker


# ── Strategy parameters (the mechanical rule being tested) ──────────────────────
MA_FAST        = 20      # pullback-reference moving average
MA_SLOW        = 50      # longer-term trend filter
PULLBACK_BAND  = 0.02    # price must be within 2% above the fast MA to count as a pullback
STOP_PCT       = 0.06    # stop-loss: 6% below entry
TARGET_PCT     = 0.12    # take-profit: 12% above entry
MAX_HOLD_DAYS  = 20      # time-based exit if neither stop nor target triggers
START_CAPITAL  = 10_000  # per-symbol simulated starting capital


def backtest_symbol(symbol: str, bars: list) -> dict:
    """Simulate the mechanical rule on one symbol's daily bars."""
    df = pd.DataFrame(bars)
    if len(df) < MA_SLOW + 10:
        return {"symbol": symbol, "error": f"only {len(df)} bars, need {MA_SLOW + 10}+"}

    df = df.reset_index(drop=True)
    df["ma_fast"]      = df["close"].rolling(MA_FAST).mean()
    df["ma_slow"]      = df["close"].rolling(MA_SLOW).mean()
    df["ma_fast_prev"] = df["ma_fast"].shift(5)

    cash        = START_CAPITAL
    shares      = 0
    entry_price = 0.0
    entry_idx   = -1
    stop = target = 0.0
    trades      = []

    for i in range(MA_SLOW + 5, len(df)):
        row   = df.iloc[i]
        price = row["close"]

        if shares == 0:
            # ── entry check ──
            if pd.isna(row["ma_fast"]) or pd.isna(row["ma_slow"]) or pd.isna(row["ma_fast_prev"]):
                continue
            ma_rising   = row["ma_fast"] > row["ma_fast_prev"]
            in_uptrend  = price > row["ma_slow"]
            near_ma     = row["ma_fast"] <= price <= row["ma_fast"] * (1 + PULLBACK_BAND)
            if ma_rising and in_uptrend and near_ma:
                shares = int(cash // price)
                if shares > 0:
                    entry_price = price
                    entry_idx   = i
                    stop        = entry_price * (1 - STOP_PCT)
                    target      = entry_price * (1 + TARGET_PCT)
                    cash       -= shares * price
        else:
            # ── exit checks ──
            exit_price = None
            reason     = None
            if row["low"] <= stop:
                exit_price, reason = stop, "stop"
            elif row["high"] >= target:
                exit_price, reason = target, "target"
            elif i - entry_idx >= MAX_HOLD_DAYS:
                exit_price, reason = price, "time"

            if exit_price is not None:
                cash  += shares * exit_price
                trades.append({
                    "entry":  round(entry_price, 2),
                    "exit":   round(exit_price, 2),
                    "pl_pct": round((exit_price / entry_price - 1) * 100, 2),
                    "reason": reason,
                })
                shares = 0

    # close any still-open position at the final close
    if shares > 0:
        last = df.iloc[-1]["close"]
        cash += shares * last
        trades.append({
            "entry":  round(entry_price, 2),
            "exit":   round(last, 2),
            "pl_pct": round((last / entry_price - 1) * 100, 2),
            "reason": "open",
        })

    return {
        "symbol":      symbol,
        "trades":      trades,
        "n_trades":    len(trades),
        "final_value": cash,
        "return_pct":  (cash / START_CAPITAL - 1) * 100,
    }


def main():
    args = sys.argv[1:]
    days = 365
    if "--days" in args:
        idx = args.index("--days")
        try:
            days = int(args[idx + 1])
        except (IndexError, ValueError):
            print("--days needs a number, e.g. --days 500")
            return
        args = args[:idx] + args[idx + 2:]

    symbols = [s.upper() for s in args] if args else list(CONFIG.allowed_symbols)
    # daily bars: ask for a bit more than `days` trading days of history
    bar_limit = min(int(days * 0.75) + MA_SLOW + 20, 1000)

    print("=" * 66)
    print(" BACKTEST — mechanical swing rule (PROXY, not the actual LLM)")
    print(f" rule: buy pullback to rising {MA_FAST}d MA in {MA_SLOW}d uptrend")
    print(f"       {int(STOP_PCT*100)}% stop, {int(TARGET_PCT*100)}% target, {MAX_HOLD_DAYS}-day time exit")
    print(f" symbols: {len(symbols)}   lookback: ~{days} days")
    print("=" * 66)

    broker = Broker()
    results   = []
    all_trades = []

    for sym in symbols:
        try:
            bars = broker.get_bars(sym, "1Day", limit=bar_limit)
        except Exception as e:
            print(f"  {sym:6s}  data error: {str(e)[:60]}")
            continue
        res = backtest_symbol(sym, bars)
        if "error" in res:
            print(f"  {sym:6s}  skipped: {res['error']}")
            continue
        results.append(res)
        all_trades.extend(res["trades"])
        print(f"  {sym:6s}  {res['n_trades']:>3d} trades   return {res['return_pct']:+7.2f}%")

    if not results:
        print("\nNo symbols produced results. Try a longer --days window.")
        return

    # ── SPY buy-and-hold benchmark over the same window ──
    try:
        spy_bars = broker.get_bars("SPY", "1Day", limit=bar_limit)
        spy_df = pd.DataFrame(spy_bars)
        spy_ret = (spy_df["close"].iloc[-1] / spy_df["close"].iloc[0] - 1) * 100
    except Exception:
        spy_ret = None

    # ── aggregate stats ──
    avg_return = sum(r["return_pct"] for r in results) / len(results)
    wins   = [t for t in all_trades if t["pl_pct"] > 0]
    losses = [t for t in all_trades if t["pl_pct"] <= 0]
    win_rate = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_win  = sum(t["pl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pl_pct"] for t in losses) / len(losses) if losses else 0

    print("=" * 66)
    print(" RESULTS")
    print("=" * 66)
    print(f" symbols tested:        {len(results)}")
    print(f" total trades:          {len(all_trades)}")
    print(f" win rate:              {win_rate:.1f}%")
    print(f" average winner:        {avg_win:+.2f}%")
    print(f" average loser:         {avg_loss:+.2f}%")
    print(f" STRATEGY avg return:   {avg_return:+.2f}%   (equal-weight across symbols)")
    if spy_ret is not None:
        print(f" SPY buy-and-hold:      {spy_ret:+.2f}%")
        edge = avg_return - spy_ret
        print(f" edge vs SPY:           {edge:+.2f}%   "
              f"({'strategy ahead' if edge > 0 else 'SPY ahead — strategy underperformed'})")
    print("=" * 66)
    print(" Reminder: this is a simplified mechanical rule, not the LLM. A good")
    print(" result here is necessary but NOT sufficient evidence the bot will")
    print(" work live. A bad result here is a strong reason to be skeptical.")
    print("=" * 66)


if __name__ == "__main__":
    main()
