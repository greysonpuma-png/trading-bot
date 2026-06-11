"""
walkforward_weekly.py — weekly Donchian trend-following backtest.

╔════════════════════════════════════════════════════════════════════════════╗
║ STRATEGY                                                                   ║
║ ────────                                                                   ║
║ Classic Turtle-style long-only Donchian channel breakout on WEEKLY bars.   ║
║ Holds for weeks-to-months. Structurally different from the daily           ║
║ pullback+breakout framework: this rides confirmed trends, it does not      ║
║ try to scalp pullbacks.                                                    ║
║                                                                            ║
║ Entry (long):                                                              ║
║   * Weekly close STRICTLY ABOVE the prior ENTRY_WEEKS-week high close.     ║
║   * Optional regime filter: SPY > REGIME_WEEKS-week MA (default ON).       ║
║                                                                            ║
║ Exit:                                                                      ║
║   * Weekly close STRICTLY BELOW the prior EXIT_WEEKS-week low close, OR    ║
║   * ATR stop: close ≤ entry_price − ATR_MULTIPLE × 14-week ATR             ║
║                                                                            ║
║ Imports NOTHING from the daily backtester. Fresh framework, fresh code.    ║
║                                                                            ║
║ Holdout discipline: same as walkforward.py — develop on `--windows train`, ║
║ validate ONCE on `--windows holdout`. Re-peeking at holdout is curve-      ║
║ fitting by another name.                                                   ║
╚════════════════════════════════════════════════════════════════════════════╝

Run with:
    python walkforward_weekly.py                    # default params, train set
    python walkforward_weekly.py --windows holdout  # one-shot validation
    python walkforward_weekly.py --no-regime        # disable regime filter
"""
import argparse
import math
import sys

import pandas as pd

from config import CONFIG
from broker import Broker


# ─── Strategy parameters — literature-standard Turtle values ────────────────
# Do NOT tune these before seeing a baseline. Hypothesis first, then test.
ENTRY_WEEKS    = 20      # new N-week high triggers entry
EXIT_WEEKS     = 10      # new M-week low triggers exit
REGIME_WEEKS   = 40      # SPY MA period for the trending-regime filter
ATR_WEEKS      = 14      # ATR averaging window
ATR_MULTIPLE   = 2.0     # stop = entry − ATR_MULTIPLE × ATR
START_CAPITAL  = 10_000  # per-symbol simulated capital (matches walkforward.py)

# ─── Backtest infrastructure ────────────────────────────────────────────────
N_WINDOWS         = 5
WINDOW_WEEKS      = 52         # 1 trading year in weekly bars
BAR_LIMIT         = 500        # ~9.6 years of weekly bars from Alpaca
TRADING_WEEKS     = 52         # used to annualize Sharpe (√52, not √252)
TRAIN_W_INDICES   = {2, 3, 4}  # oldest 3 windows — develop/tune here
HOLDOUT_W_INDICES = {0, 1}     # newest 2 windows — final validation only


# ─── Metric helpers ─────────────────────────────────────────────────────────

def _annualized_sharpe(weekly_returns: pd.Series) -> float:
    """Sharpe = mean / std × √52 (weekly bars → annualized)."""
    if len(weekly_returns) < 2:
        return 0.0
    std = weekly_returns.std()
    if std == 0 or pd.isna(std):
        return 0.0
    return float(weekly_returns.mean() / std * math.sqrt(TRADING_WEEKS))


def _max_drawdown_pct(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    dd = (running_max - equity) / running_max
    return float(dd.max() * 100)


# ─── Indicator precomputation on full history ───────────────────────────────

def _add_indicator_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute Donchian thresholds and ATR on the full series so each window
    slice has valid values from its first bar — no per-window warmup gymnastics.
    """
    df = df.copy()
    # Donchian thresholds: shift(1) excludes today's bar from the rolling
    # window, so "close > donchian_high" means today is making a NEW high
    # vs the prior N weeks (not just matching one).
    df["donchian_high"] = df["close"].shift(1).rolling(ENTRY_WEEKS).max()
    df["donchian_low"]  = df["close"].shift(1).rolling(EXIT_WEEKS).min()

    # True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    # ATR = N-period average of TR. Standard Wilder smoothing replaced with
    # simple mean here for transparency.
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_WEEKS).mean()
    return df


# ─── Single-symbol single-window simulator ──────────────────────────────────

def _simulate_window(window_df: pd.DataFrame, regime_mask=None, use_regime: bool = True) -> dict:
    """Run the weekly Donchian rule on one symbol's window of bars.

    Returns the trade log and a daily-equivalent (weekly) mark-to-market
    equity series for portfolio-level Sharpe / drawdown computation.
    """
    df = window_df.reset_index(drop=True)
    cash        = float(START_CAPITAL)
    shares      = 0
    entry_price = 0.0
    atr_stop    = 0.0
    trades      = []
    equity      = []

    for i in range(len(df)):
        row   = df.iloc[i]
        close = row["close"]

        if shares == 0:
            # ── Donchian entry ──
            if not pd.isna(row.get("donchian_high")) and not pd.isna(row.get("atr")):
                regime_on = True
                if use_regime:
                    regime_on = (regime_mask is not None
                                 and i < len(regime_mask)
                                 and bool(regime_mask.iloc[i]))
                if regime_on and close > row["donchian_high"]:
                    shares = int(cash // close)
                    if shares > 0:
                        entry_price = close
                        atr_stop    = entry_price - ATR_MULTIPLE * row["atr"]
                        cash       -= shares * close
        else:
            # ── Exits: Donchian-low OR ATR stop ──
            exit_price = None
            reason     = None
            if close <= atr_stop:
                exit_price, reason = close, "atr_stop"
            elif not pd.isna(row.get("donchian_low")) and close < row["donchian_low"]:
                exit_price, reason = close, "donchian_exit"

            if exit_price is not None:
                cash += shares * exit_price
                trades.append({
                    "pl_pct":     (exit_price / entry_price - 1) * 100,
                    "pl_dollars": shares * (exit_price - entry_price),
                    "reason":     reason,
                })
                shares = 0

        equity.append(cash + shares * close)

    # Force-close at window end so ending equity is mark-to-market
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


# ─── Window-level aggregation ───────────────────────────────────────────────

def _window_stats(per_symbol_equities: list, all_trades: list, spy_ret_pct: float) -> dict:
    eq_df = pd.DataFrame(per_symbol_equities).T
    portfolio_eq = eq_df.sum(axis=1).dropna()
    if len(portfolio_eq) < 2:
        return {}

    start_eq   = portfolio_eq.iloc[0]
    end_eq     = portfolio_eq.iloc[-1]
    return_pct = (end_eq / start_eq - 1) * 100

    weekly_ret = portfolio_eq.pct_change().dropna()
    sharpe     = _annualized_sharpe(weekly_ret)
    max_dd     = _max_drawdown_pct(portfolio_eq)

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

def main():
    global ENTRY_WEEKS, EXIT_WEEKS

    parser = argparse.ArgumentParser(description="Weekly Donchian trend-following backtest.")
    parser.add_argument("--windows",     choices=["train", "holdout", "all"], default="train",
                        help="Which window set to evaluate (default: train)")
    parser.add_argument("--no-regime",   action="store_true",
                        help="Disable the SPY trend regime filter")
    parser.add_argument("--entry-weeks", type=int, default=ENTRY_WEEKS,
                        help=f"Donchian entry lookback in weeks (default {ENTRY_WEEKS})")
    parser.add_argument("--exit-weeks",  type=int, default=EXIT_WEEKS,
                        help=f"Donchian exit lookback in weeks (default {EXIT_WEEKS})")
    parser.add_argument("symbols",       nargs="*", help="Symbols (default: whole whitelist)")
    args = parser.parse_args()

    ENTRY_WEEKS = args.entry_weeks
    EXIT_WEEKS  = args.exit_weeks
    use_regime  = not args.no_regime

    if args.windows == "train":
        allowed_w = TRAIN_W_INDICES
    elif args.windows == "holdout":
        allowed_w = HOLDOUT_W_INDICES
        print("⚠️  HOLDOUT VALIDATION RUN — should be done ONCE per candidate parameter set.")
        print("   Re-running on holdout to tune defeats its purpose.")
    else:
        allowed_w = set(range(N_WINDOWS))

    symbols = [s.upper() for s in args.symbols] if args.symbols else list(CONFIG.allowed_symbols)

    print("=" * 84)
    print(" WALK-FORWARD BACKTEST — weekly Donchian trend-following")
    print(f" entry: new {ENTRY_WEEKS}-week high   exit: new {EXIT_WEEKS}-week low "
          f"OR {ATR_MULTIPLE}×ATR stop")
    print(f" regime: {'SPY > ' + str(REGIME_WEEKS) + '-week MA' if use_regime else 'OFF'}")
    print(f" symbols: {len(symbols)}   windows: {len(allowed_w)} ({args.windows})")
    print("=" * 84)

    broker = Broker()

    bars_by_symbol = {}
    for sym in symbols:
        try:
            bars = broker.get_bars(sym, "1Week", limit=BAR_LIMIT)
        except Exception as e:
            print(f"  skipping {sym}: {str(e)[:60]}")
            continue
        df = pd.DataFrame(bars)
        if len(df) < N_WINDOWS * WINDOW_WEEKS:
            print(f"  skipping {sym}: only {len(df)} weekly bars, need {N_WINDOWS * WINDOW_WEEKS}")
            continue
        bars_by_symbol[sym] = _add_indicator_columns(df)

    if not bars_by_symbol:
        print("\nNo symbols had enough weekly history. Aborting.")
        return

    spy_df = pd.DataFrame(broker.get_bars("SPY", "1Week", limit=BAR_LIMIT))
    # min_periods=20 lets the regime MA compute earlier than 40 weeks with
    # weaker signal; fillna(False) means "regime unknown → don't fire entries."
    spy_df["regime_ma"] = spy_df["close"].rolling(REGIME_WEEKS, min_periods=20).mean()
    spy_df["in_trend"]  = (spy_df["close"] > spy_df["regime_ma"]).fillna(False)

    total_bars = min(min(len(df) for df in bars_by_symbol.values()), len(spy_df))

    window_results = []
    for w in range(N_WINDOWS):
        if w not in allowed_w:
            continue
        end_idx   = total_bars - w * WINDOW_WEEKS
        start_idx = end_idx - WINDOW_WEEKS
        if start_idx < ENTRY_WEEKS + 5:
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
                                   use_regime=use_regime)
            per_symbol_equities.append(sim["equity"])
            all_trades.extend(sim["trades"])

        stats = _window_stats(per_symbol_equities, all_trades, spy_ret)
        if not stats:
            continue

        anchor = next(iter(bars_by_symbol.values()))
        start_date = pd.to_datetime(anchor.iloc[start_idx]["timestamp"]).date()
        end_date   = pd.to_datetime(anchor.iloc[end_idx - 1]["timestamp"]).date()
        stats["label"] = f"{start_date} → {end_date}"
        window_results.append(stats)

    if not window_results:
        print("No windows produced results.")
        return

    print()
    print(f"  {'Window':24s} {'Return':>8s} {'SPY':>8s} {'Alpha':>8s} {'Sharpe':>7s} {'MaxDD':>8s} {'PF':>6s} {'Trades':>7s} {'Win%':>6s}")
    print("  " + "-" * 100)
    for r in reversed(window_results):
        pf_str = f"{r['profit_factor']:6.2f}" if math.isfinite(r['profit_factor']) else "   inf"
        print(f"  {r['label']:24s} {r['return_pct']:+7.2f}% {r['spy_return']:+7.2f}% {r['alpha']:+7.2f}% {r['sharpe']:+7.2f} {r['max_dd_pct']:7.2f}% {pf_str} {r['n_trades']:7d} {r['win_rate']:5.1f}%")

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
    print(" INTERPRETATION (same bar as the daily backtester)")
    print("  * Alpha > 0 in 4-5/5 windows  → strategy may have real, repeatable edge")
    print("  * Alpha > 0 in 1-2/5 windows  → looks like a lucky year, not a signal")
    print("  * Sharpe < 0.5                → returns aren't worth the volatility, even if positive")
    print("  * Max drawdown > 25%          → would you actually hold through that pain in real life?")
    print("  * Profit factor < 1.0         → gross losses exceed gross wins; no execution can save it")
    print("=" * 84)


if __name__ == "__main__":
    main()
