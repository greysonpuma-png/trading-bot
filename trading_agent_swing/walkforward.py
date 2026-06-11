"""
walkforward.py — multi-window backtest of the swing-trading rule.

╔════════════════════════════════════════════════════════════════════════════╗
║ WHY THIS EXISTS                                                            ║
╠════════════════════════════════════════════════════════════════════════════╣
║ backtest.py runs the strategy on ONE historical window. A single-window    ║
║ result is the weakest possible evidence — strategies often win on one      ║
║ window and lose on every other one. The real question is consistency.      ║
║                                                                            ║
║ This script splits the last ~5 years into 5 non-overlapping 1-year         ║
║ windows and reports the strategy's behavior on each one. Look for:         ║
║                                                                            ║
║   * Is alpha vs SPY positive in MOST windows, or just one lucky year?      ║
║   * Is the Sharpe ratio (risk-adjusted return) any good?                   ║
║   * What's the worst drawdown — would you actually hold through it?        ║
║   * Is the profit factor > 1.0 (do gross winners exceed gross losers)?     ║
╚════════════════════════════════════════════════════════════════════════════╝

Run with:
    python walkforward.py                    # all whitelisted symbols
    python walkforward.py SPY AAPL MSFT      # specific symbols
"""
import argparse
import math
import sys

import pandas as pd

from config import CONFIG
from broker import Broker
from backtest import (
    MA_FAST, MA_SLOW, PULLBACK_BAND,
    STOP_PCT, TARGET_PCT, MAX_HOLD_DAYS, START_CAPITAL,
)


N_WINDOWS    = 5
WINDOW_DAYS  = 252                                          # ~1 trading year
REGIME_MA    = 200                                          # SPY trend filter window
BAR_LIMIT    = N_WINDOWS * WINDOW_DAYS + MA_SLOW + 100      # MUST stay = yesterday's baseline
TRADING_DAYS = 252                                          # used to annualize Sharpe
BREAKOUT_LOOKBACK = 20                                      # new N-day high triggers breakout entry
# REGIME_MIN_PERIODS lets the 200d MA compute even when the oldest window has
# only ~150 prior bars of history (vs the default 200 required). Trade-off:
# slightly weaker regime signal at the very start of the oldest window only.
REGIME_MIN_PERIODS = 50

# Train/holdout split. w=0 is the MOST RECENT window, w=N_WINDOWS-1 the OLDEST.
# Tune and develop hypotheses against TRAIN. Reserve HOLDOUT for ONE-TIME final
# validation of a candidate parameter set — repeatedly peeking at holdout
# defeats its purpose and is curve-fitting by another name.
TRAIN_W_INDICES   = {2, 3, 4}    # oldest 3 windows
HOLDOUT_W_INDICES = {0, 1}        # newest 2 windows


# ─── Metric helpers ─────────────────────────────────────────────────────────

def _annualized_sharpe(daily_returns: pd.Series) -> float:
    """Sharpe = mean / std × √252. Return per unit of volatility, annualized."""
    if len(daily_returns) < 2:
        return 0.0
    std = daily_returns.std()
    if std == 0 or pd.isna(std):
        return 0.0
    return float(daily_returns.mean() / std * math.sqrt(TRADING_DAYS))


def _max_drawdown_pct(equity: pd.Series) -> float:
    """Largest peak-to-trough equity drop, returned as a positive percent."""
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    dd = (running_max - equity) / running_max
    return float(dd.max() * 100)


# ─── Single-symbol, single-window simulator ─────────────────────────────────

def _simulate_window(window_df: pd.DataFrame, regime_mask=None, entry_mode: str = "pullback") -> dict:
    """Run the strategy on one symbol's window of bars.

    entry_mode:
        "pullback" — original rule: buy on pullback to rising 20d MA in 50d uptrend
        "breakout" — Exp2: in SPY trending regime, buy on a new 20-day high in uptrend
        "both"     — try pullback first; if no signal, fall back to breakout

    regime_mask: boolean Series (aligned to window_df) — True where SPY > 200d MA.
                 Only used by the breakout entry path. Pullback ignores regime.

    Returns the trade log and a daily mark-to-market equity series.
    """
    df = window_df.reset_index(drop=True)
    cash        = float(START_CAPITAL)
    shares      = 0
    entry_price = 0.0
    entry_idx   = -1
    stop = target = 0.0
    trades = []
    equity = []

    for i in range(len(df)):
        row   = df.iloc[i]
        price = row["close"]

        if shares == 0:
            # ── Pullback entry (original rule) ──
            if entry_mode in ("pullback", "both"):
                if (not pd.isna(row["ma_fast"]) and not pd.isna(row["ma_slow"])
                        and not pd.isna(row["ma_fast_prev"])):
                    ma_rising  = row["ma_fast"] > row["ma_fast_prev"]
                    in_uptrend = price > row["ma_slow"]
                    near_ma    = row["ma_fast"] <= price <= row["ma_fast"] * (1 + PULLBACK_BAND)
                    if ma_rising and in_uptrend and near_ma:
                        shares = int(cash // price)
                        if shares > 0:
                            entry_price = price
                            entry_idx   = i
                            stop        = entry_price * (1 - STOP_PCT)
                            target      = entry_price * (1 + TARGET_PCT)
                            cash       -= shares * price

            # ── Breakout entry (Exp2): only in SPY trending regime ──
            if shares == 0 and entry_mode in ("breakout", "both"):
                in_trend = (regime_mask is not None
                            and i < len(regime_mask)
                            and bool(regime_mask.iloc[i]))
                if (in_trend and i >= BREAKOUT_LOOKBACK
                        and not pd.isna(row["ma_slow"]) and price > row["ma_slow"]):
                    prior_high_max = df["high"].iloc[i - BREAKOUT_LOOKBACK:i].max()
                    if row["high"] >= prior_high_max:
                        shares = int(cash // price)
                        if shares > 0:
                            entry_price = price
                            entry_idx   = i
                            stop        = entry_price * (1 - STOP_PCT)
                            target      = entry_price * (1 + TARGET_PCT)
                            cash       -= shares * price
        else:
            exit_price = None
            reason     = None
            if row["low"] <= stop:
                exit_price, reason = stop, "stop"
            elif row["high"] >= target:
                exit_price, reason = target, "target"
            elif i - entry_idx >= MAX_HOLD_DAYS:
                exit_price, reason = price, "time"

            if exit_price is not None:
                cash += shares * exit_price
                trades.append({
                    "pl_pct":     (exit_price / entry_price - 1) * 100,
                    "pl_dollars": shares * (exit_price - entry_price),
                    "reason":     reason,
                })
                shares = 0

        equity.append(cash + shares * price)

    # Force-close any still-open position at the window's final close so
    # ending equity reflects mark-to-market, not unrealized phantom value.
    if shares > 0:
        last = df.iloc[-1]["close"]
        cash += shares * last
        trades.append({
            "pl_pct":     (last / entry_price - 1) * 100,
            "pl_dollars": shares * (last - entry_price),
            "reason":     "open",
        })
        equity[-1] = cash

    return {"trades": trades, "equity": equity}


# ─── Window-level aggregation across all symbols ────────────────────────────

def _window_stats(per_symbol_equities: list, all_trades: list, spy_ret_pct: float) -> dict:
    """Combine per-symbol equity curves into one portfolio curve, then compute metrics."""
    eq_df = pd.DataFrame(per_symbol_equities).T              # rows=days, cols=symbols
    portfolio_eq = eq_df.sum(axis=1).dropna()
    if len(portfolio_eq) < 2:
        return {}

    start_eq   = portfolio_eq.iloc[0]
    end_eq     = portfolio_eq.iloc[-1]
    return_pct = (end_eq / start_eq - 1) * 100

    daily_ret = portfolio_eq.pct_change().dropna()
    sharpe    = _annualized_sharpe(daily_ret)
    max_dd    = _max_drawdown_pct(portfolio_eq)

    winners  = [t for t in all_trades if t["pl_dollars"] >  0]
    losers   = [t for t in all_trades if t["pl_dollars"] <= 0]
    win_rate = (len(winners) / len(all_trades) * 100) if all_trades else 0.0
    gross_w  = sum(t["pl_dollars"] for t in winners)
    gross_l  = abs(sum(t["pl_dollars"] for t in losers))
    pf       = (gross_w / gross_l) if gross_l > 0 else float("inf")

    return {
        "return_pct":    return_pct,
        "spy_return":    spy_ret_pct,
        "alpha":         return_pct - spy_ret_pct,
        "sharpe":        sharpe,
        "max_dd_pct":    max_dd,
        "profit_factor": pf,
        "n_trades":      len(all_trades),
        "win_rate":      win_rate,
    }


# ─── Main entry ─────────────────────────────────────────────────────────────

def _add_ma_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma_fast"]      = df["close"].rolling(MA_FAST).mean()
    df["ma_slow"]      = df["close"].rolling(MA_SLOW).mean()
    df["ma_fast_prev"] = df["ma_fast"].shift(5)
    return df


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest of the swing rule.")
    parser.add_argument("--target",  type=float, help="Take-profit percent (default 12)")
    parser.add_argument("--stop",    type=float, help="Stop-loss percent (default 6)")
    parser.add_argument("--hold",    type=int,   help="Max hold days (default 20)")
    parser.add_argument("--windows", choices=["train", "holdout", "all"], default="train",
                        help="Which window set to evaluate (default: train)")
    parser.add_argument("--entry",   choices=["pullback", "breakout", "both"], default="pullback",
                        help="Entry rule (default: pullback — original behavior)")
    parser.add_argument("symbols",   nargs="*",  help="Symbols (default: whole whitelist)")
    args = parser.parse_args()

    if args.windows == "train":
        allowed_w = TRAIN_W_INDICES
    elif args.windows == "holdout":
        allowed_w = HOLDOUT_W_INDICES
        print("⚠️  HOLDOUT VALIDATION RUN — should be done ONCE per candidate parameter set.")
        print("   Re-running on holdout to tune defeats its purpose.")
    else:
        allowed_w = set(range(N_WINDOWS))

    # Apply CLI overrides on top of the defaults imported from backtest.py.
    # This lets us A/B parameter changes without editing files between runs.
    global STOP_PCT, TARGET_PCT, MAX_HOLD_DAYS
    if args.target is not None: TARGET_PCT    = args.target / 100
    if args.stop   is not None: STOP_PCT      = args.stop / 100
    if args.hold   is not None: MAX_HOLD_DAYS = args.hold

    symbols = [s.upper() for s in args.symbols] if args.symbols else list(CONFIG.allowed_symbols)

    print("=" * 84)
    print(" WALK-FORWARD BACKTEST — rolling 1-year windows")
    print(f" entry: {args.entry}    exit: {int(STOP_PCT*100)}% stop / "
          f"{int(TARGET_PCT*100)}% target, {MAX_HOLD_DAYS}d hold")
    print(f" symbols: {len(symbols)}   windows: {len(allowed_w)} ({args.windows})")
    print("=" * 84)

    broker = Broker()

    # Load each symbol's full history once; compute MAs on the full series so
    # every window has clean MA values without per-window warmup gymnastics.
    bars_by_symbol = {}
    for sym in symbols:
        try:
            bars = broker.get_bars(sym, "1Day", limit=BAR_LIMIT)
        except Exception as e:
            print(f"  skipping {sym}: {str(e)[:60]}")
            continue
        df = pd.DataFrame(bars)
        if len(df) < N_WINDOWS * WINDOW_DAYS:
            print(f"  skipping {sym}: only {len(df)} bars, need {N_WINDOWS * WINDOW_DAYS}")
            continue
        bars_by_symbol[sym] = _add_ma_columns(df)

    if not bars_by_symbol:
        print("\nNo symbols had enough history. Aborting.")
        return

    spy_df = pd.DataFrame(broker.get_bars("SPY", "1Day", limit=BAR_LIMIT))
    # Precompute SPY's trending-regime mask for the breakout entry rule.
    # min_periods=50 keeps the MA valid early on with weaker history;
    # fillna(False) treats "regime unknown" as "do not fire breakout."
    spy_df["regime_ma"] = spy_df["close"].rolling(REGIME_MA, min_periods=REGIME_MIN_PERIODS).mean()
    spy_df["in_trend"]  = (spy_df["close"] > spy_df["regime_ma"]).fillna(False)

    total_bars = min(min(len(df) for df in bars_by_symbol.values()), len(spy_df))

    window_results = []
    for w in range(N_WINDOWS):
        if w not in allowed_w:
            continue
        end_idx   = total_bars - w * WINDOW_DAYS
        start_idx = end_idx - WINDOW_DAYS
        if start_idx < MA_SLOW + 10:
            print(f"  window {w}: not enough history before start; skipping.")
            continue

        spy_window        = spy_df.iloc[start_idx:end_idx]
        spy_regime_window = spy_df["in_trend"].iloc[start_idx:end_idx].reset_index(drop=True)
        spy_ret           = (spy_window["close"].iloc[-1] / spy_window["close"].iloc[0] - 1) * 100

        per_symbol_equities = []
        all_trades          = []
        for sym, df in bars_by_symbol.items():
            sim = _simulate_window(df.iloc[start_idx:end_idx],
                                   regime_mask=spy_regime_window,
                                   entry_mode=args.entry)
            per_symbol_equities.append(sim["equity"])
            all_trades.extend(sim["trades"])

        stats = _window_stats(per_symbol_equities, all_trades, spy_ret)
        if not stats:
            continue

        anchor     = next(iter(bars_by_symbol.values()))
        start_date = pd.to_datetime(anchor.iloc[start_idx]["timestamp"]).date()
        end_date   = pd.to_datetime(anchor.iloc[end_idx - 1]["timestamp"]).date()
        stats["label"] = f"{start_date} → {end_date}"
        window_results.append(stats)

    if not window_results:
        print("No windows produced results.")
        return

    # ── Per-window table (oldest → newest) ──
    print()
    print(f"  {'Window':24s} {'Return':>8s} {'SPY':>8s} {'Alpha':>8s} {'Sharpe':>7s} {'MaxDD':>8s} {'PF':>6s} {'Trades':>7s} {'Win%':>6s}")
    print("  " + "-" * 100)
    for r in reversed(window_results):
        pf_str = f"{r['profit_factor']:6.2f}" if math.isfinite(r['profit_factor']) else "   inf"
        print(f"  {r['label']:24s} {r['return_pct']:+7.2f}% {r['spy_return']:+7.2f}% {r['alpha']:+7.2f}% {r['sharpe']:+7.2f} {r['max_dd_pct']:7.2f}% {pf_str} {r['n_trades']:7d} {r['win_rate']:5.1f}%")

    # ── Summary stats ──
    n           = len(window_results)
    n_alpha_pos = sum(1 for r in window_results if r["alpha"] > 0)
    avg_alpha   = sum(r["alpha"] for r in window_results) / n
    avg_sharpe  = sum(r["sharpe"] for r in window_results) / n
    worst_dd    = max(r["max_dd_pct"] for r in window_results)

    print()
    print("=" * 84)
    print(" SUMMARY")
    print("=" * 84)
    print(f"  windows with positive alpha vs SPY:   {n_alpha_pos}/{n}")
    print(f"  average alpha:                         {avg_alpha:+.2f}%")
    print(f"  average annualized Sharpe:             {avg_sharpe:+.2f}")
    print(f"  worst max drawdown across windows:     {worst_dd:.2f}%")
    print()
    print(" INTERPRETATION")
    print("  * Alpha > 0 in 4-5/5 windows  → strategy may have real, repeatable edge")
    print("  * Alpha > 0 in 1-2/5 windows  → looks like a lucky year, not a signal")
    print("  * Sharpe < 0.5                → returns aren't worth the volatility, even if positive")
    print("  * Max drawdown > 25%          → would you actually hold through that pain in real life?")
    print("  * Profit factor < 1.0         → gross losses exceed gross wins; no execution can save it")
    print("=" * 84)


if __name__ == "__main__":
    main()
