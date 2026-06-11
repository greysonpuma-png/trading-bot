"""
walkforward_rotation.py — sector rotation backtest (relative strength momentum).

╔════════════════════════════════════════════════════════════════════════════╗
║ STRATEGY                                                                   ║
║ ────────                                                                   ║
║ Classic dual-momentum sector rotation (Antonacci-style). At each monthly   ║
║ rebalance:                                                                 ║
║   1. Rank the 11 SPDR sector ETFs by their LOOKBACK_MONTHS return.         ║
║   2. Hold the top TOP_K sectors, equal-weighted. Sell anything not in top. ║
║   3. Optional regime filter: only hold sectors if SPY > 200d MA, else cash.║
║                                                                            ║
║ This is structurally different from everything tested so far:              ║
║   * Portfolio strategy (holdings interact), not per-symbol independent     ║
║   * Sector ETFs, not individual stocks                                     ║
║   * Monthly rebalance (~12 trades/year vs 250+ daily)                      ║
║   * Selection by relative strength ranking, not price-trigger signals      ║
║                                                                            ║
║ Holdout discipline: same windows as the daily framework but the strategy   ║
║ is structurally far enough removed that one-shot validation is defensible. ║
║ Per usual: develop on train, validate ONCE on holdout.                     ║
╚════════════════════════════════════════════════════════════════════════════╝

Run with:
    python walkforward_rotation.py                    # default params, train
    python walkforward_rotation.py --windows holdout  # one-shot validation
    python walkforward_rotation.py --no-regime        # disable regime filter
    python walkforward_rotation.py --top-k 3          # hold top 3 sectors
"""
import argparse
import math

import pandas as pd

from broker import Broker


# ─── Sector universe (SPDR sector ETFs) ─────────────────────────────────────
SECTOR_ETFS = [
    "XLK",   # Technology
    "XLF",   # Financials
    "XLV",   # Health Care
    "XLY",   # Consumer Discretionary
    "XLP",   # Consumer Staples
    "XLI",   # Industrials
    "XLE",   # Energy
    "XLB",   # Materials
    "XLU",   # Utilities
    "XLRE",  # Real Estate  (inception 2015)
    "XLC",   # Communication Services  (inception 2018)
]

# ─── Strategy parameters — literature-standard defaults ─────────────────────
LOOKBACK_DAYS    = 126    # ~6 months of trading days for momentum ranking
TOP_K            = 2      # how many sectors to hold
REBALANCE_DAYS   = 21     # rebalance every ~1 month
REGIME_MA        = 200    # SPY 200d MA for regime filter (~10 months)
START_CAPITAL    = 100_000

# ─── Backtest infrastructure ────────────────────────────────────────────────
N_WINDOWS         = 5
WINDOW_DAYS       = 252
BAR_LIMIT         = N_WINDOWS * WINDOW_DAYS + REGIME_MA + 100
TRADING_DAYS      = 252
TRAIN_W_INDICES   = {2, 3, 4}
HOLDOUT_W_INDICES = {0, 1}


# ─── Metric helpers ─────────────────────────────────────────────────────────

def _annualized_sharpe(daily_returns: pd.Series) -> float:
    if len(daily_returns) < 2:
        return 0.0
    std = daily_returns.std()
    if std == 0 or pd.isna(std):
        return 0.0
    return float(daily_returns.mean() / std * math.sqrt(TRADING_DAYS))


def _max_drawdown_pct(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    dd = (running_max - equity) / running_max
    return float(dd.max() * 100)


# ─── Portfolio simulator (NOT per-symbol — sectors interact) ────────────────

def _simulate_window(
    start_idx: int,
    end_idx: int,
    sector_data: dict,
    spy_data: pd.DataFrame,
    top_k: int,
    use_regime: bool,
) -> dict:
    """Run sector rotation on the given window. Returns equity curve + rebalance count."""
    cash         = float(START_CAPITAL)
    holdings     = {}                       # symbol -> shares
    equity       = []
    rebalances   = 0
    last_rebal   = -1

    for i in range(start_idx, end_idx):
        # Current prices for all sectors we have data for at this index
        prices = {sym: df.iloc[i]["close"] for sym, df in sector_data.items()
                  if i < len(df) and not pd.isna(df.iloc[i]["close"])}

        # Mark to market
        port_value = cash + sum(holdings.get(s, 0) * prices.get(s, 0) for s in holdings)
        equity.append(port_value)

        # Rebalance every REBALANCE_DAYS or at very first bar of window
        if i - last_rebal >= REBALANCE_DAYS or i == start_idx:
            # Determine target portfolio
            target_symbols = []
            regime_on = True
            if use_regime:
                if i >= len(spy_data) or pd.isna(spy_data.iloc[i].get("regime_ma")):
                    regime_on = False
                else:
                    regime_on = spy_data.iloc[i]["close"] > spy_data.iloc[i]["regime_ma"]

            if regime_on:
                # Rank sectors by trailing LOOKBACK_DAYS return
                ranked = []
                for sym, df in sector_data.items():
                    if i < LOOKBACK_DAYS or i >= len(df):
                        continue
                    past_close = df.iloc[i - LOOKBACK_DAYS]["close"]
                    cur_close  = df.iloc[i]["close"]
                    if past_close > 0 and not pd.isna(past_close):
                        ranked.append((sym, cur_close / past_close - 1))
                ranked.sort(key=lambda x: x[1], reverse=True)
                target_symbols = [s for s, _ in ranked[:top_k]]

            # Sell anything not in target
            for sym in list(holdings.keys()):
                if sym not in target_symbols and holdings[sym] > 0 and sym in prices:
                    cash += holdings[sym] * prices[sym]
                    holdings[sym] = 0

            # Rebalance to equal weight on targets
            if target_symbols:
                # Total currently allocated to target sectors + cash = available for rebalance
                available = cash + sum(holdings.get(s, 0) * prices[s] for s in target_symbols if s in prices)
                per_sym   = available / len(target_symbols)
                for sym in target_symbols:
                    if sym not in prices:
                        continue
                    target_shares = int(per_sym / prices[sym])
                    delta = target_shares - holdings.get(sym, 0)
                    if delta > 0:
                        cost = delta * prices[sym]
                        if cash >= cost:
                            cash -= cost
                            holdings[sym] = holdings.get(sym, 0) + delta
                    elif delta < 0:
                        cash += abs(delta) * prices[sym]
                        holdings[sym] += delta

            rebalances += 1
            last_rebal = i

    # Mark final to market for ending equity
    final_idx = end_idx - 1
    final_prices = {sym: df.iloc[final_idx]["close"] for sym, df in sector_data.items()
                    if final_idx < len(df) and not pd.isna(df.iloc[final_idx]["close"])}
    final_value = cash + sum(holdings.get(s, 0) * final_prices.get(s, 0) for s in holdings)
    if equity:
        equity[-1] = final_value

    return {"equity": equity, "rebalances": rebalances}


# ─── Window-level stats ─────────────────────────────────────────────────────

def _window_stats(equity_list: list, spy_ret_pct: float, rebalances: int) -> dict:
    eq = pd.Series(equity_list).dropna()
    if len(eq) < 2:
        return {}
    start_eq = eq.iloc[0]
    end_eq   = eq.iloc[-1]
    return_pct = (end_eq / start_eq - 1) * 100

    daily_ret = eq.pct_change().dropna()
    sharpe    = _annualized_sharpe(daily_ret)
    max_dd    = _max_drawdown_pct(eq)

    return {
        "return_pct": return_pct,
        "spy_return": spy_ret_pct,
        "alpha":      return_pct - spy_ret_pct,
        "sharpe":     sharpe,
        "max_dd_pct": max_dd,
        "rebalances": rebalances,
    }


# ─── Main entry ─────────────────────────────────────────────────────────────

def main():
    global LOOKBACK_DAYS

    parser = argparse.ArgumentParser(description="Sector rotation walk-forward backtest.")
    parser.add_argument("--windows",   choices=["train", "holdout", "all"], default="train",
                        help="Which window set to evaluate (default: train)")
    parser.add_argument("--no-regime", action="store_true",
                        help="Disable SPY > 200d MA regime filter")
    parser.add_argument("--top-k",     type=int, default=TOP_K,
                        help=f"How many top sectors to hold (default {TOP_K})")
    parser.add_argument("--lookback",  type=int, default=LOOKBACK_DAYS,
                        help=f"Momentum ranking lookback in days (default {LOOKBACK_DAYS})")
    args = parser.parse_args()

    top_k         = args.top_k
    LOOKBACK_DAYS = args.lookback
    use_regime    = not args.no_regime

    if args.windows == "train":
        allowed_w = TRAIN_W_INDICES
    elif args.windows == "holdout":
        allowed_w = HOLDOUT_W_INDICES
        print("⚠️  HOLDOUT VALIDATION RUN — should be done ONCE per candidate parameter set.")
        print("   Re-running on holdout to tune defeats its purpose.")
    else:
        allowed_w = set(range(N_WINDOWS))

    print("=" * 84)
    print(" WALK-FORWARD BACKTEST — sector rotation (relative strength momentum)")
    print(f" rule: top {top_k} sector ETFs by {LOOKBACK_DAYS}-day return, monthly rebalance")
    print(f" regime: {'SPY > ' + str(REGIME_MA) + 'd MA (else cash)' if use_regime else 'OFF'}")
    print(f" universe: {len(SECTOR_ETFS)} sector ETFs   windows: {len(allowed_w)} ({args.windows})")
    print("=" * 84)

    broker = Broker()

    # Load each sector's full daily history
    sector_data = {}
    for sym in SECTOR_ETFS:
        try:
            bars = broker.get_bars(sym, "1Day", limit=BAR_LIMIT)
        except Exception as e:
            print(f"  skipping {sym}: {str(e)[:60]}")
            continue
        df = pd.DataFrame(bars)
        if len(df) < N_WINDOWS * WINDOW_DAYS:
            print(f"  warning: {sym} has only {len(df)} bars — included but will be skipped in early windows where data is short.")
        if len(df) > 0:
            sector_data[sym] = df

    if len(sector_data) < top_k:
        print(f"\nNeed at least {top_k} sectors with data. Got {len(sector_data)}. Aborting.")
        return

    spy_df = pd.DataFrame(broker.get_bars("SPY", "1Day", limit=BAR_LIMIT))
    spy_df["regime_ma"] = spy_df["close"].rolling(REGIME_MA, min_periods=50).mean()

    total_bars = min(min(len(df) for df in sector_data.values()), len(spy_df))

    window_results = []
    for w in range(N_WINDOWS):
        if w not in allowed_w:
            continue
        end_idx   = total_bars - w * WINDOW_DAYS
        start_idx = end_idx - WINDOW_DAYS
        if start_idx < LOOKBACK_DAYS + 5:
            print(f"  window {w}: not enough history for lookback; skipping.")
            continue

        sim = _simulate_window(start_idx, end_idx, sector_data, spy_df, top_k, use_regime)

        spy_window = spy_df.iloc[start_idx:end_idx]
        spy_ret = (spy_window["close"].iloc[-1] / spy_window["close"].iloc[0] - 1) * 100

        stats = _window_stats(sim["equity"], spy_ret, sim["rebalances"])
        if not stats:
            continue

        anchor = next(iter(sector_data.values()))
        start_date = pd.to_datetime(anchor.iloc[start_idx]["timestamp"]).date()
        end_date   = pd.to_datetime(anchor.iloc[end_idx - 1]["timestamp"]).date()
        stats["label"] = f"{start_date} → {end_date}"
        window_results.append(stats)

    if not window_results:
        print("No windows produced results.")
        return

    print()
    print(f"  {'Window':24s} {'Return':>8s} {'SPY':>8s} {'Alpha':>8s} {'Sharpe':>7s} {'MaxDD':>8s} {'Rebals':>7s}")
    print("  " + "-" * 90)
    for r in reversed(window_results):
        print(f"  {r['label']:24s} {r['return_pct']:+7.2f}% {r['spy_return']:+7.2f}% {r['alpha']:+7.2f}% {r['sharpe']:+7.2f} {r['max_dd_pct']:7.2f}% {r['rebalances']:7d}")

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
    print("=" * 84)


if __name__ == "__main__":
    main()
