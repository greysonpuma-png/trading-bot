"""
╔════════════════════════════════════════════════════════════════════════════╗
║ Exp6 — CROSS-SECTIONAL MOMENTUM on crypto (walk-forward backtest)          ║
║                                                                            ║
║ Why this framework: the equity dataset is spent. Six configurations across ║
║ three frameworks plus a live forward test have been evaluated on the same  ║
║ 39 symbols of daily bars, so any further backtest there is curve-fitting   ║
║ by another name. Crypto is genuinely untouched data — a real holdout by    ║
║ construction.                                                              ║
║                                                                            ║
║ Why cross-sectional: all three equity frameworks asked a TIME-SERIES       ║
║ question — "is this symbol a buy right now?" This asks a different one:    ║
║ "which of these is strongest relative to the others?" Rank the universe,   ║
║ hold the top K, rebalance. Structurally different, not a re-skin.          ║
║                                                                            ║
║ BENCHMARK: equal-weight buy-and-hold of the SAME universe — not BTC, not   ║
║ SPY. The question is whether the strategy adds anything over simply owning ║
║ these assets. And it is judged RISK-ADJUSTED FIRST: at 44-96% annualized   ║
║ volatility, raw return comparisons are a beta contest, and a strategy      ║
║ capturing 70% of the return at 40% of the volatility is genuinely good.    ║
║                                                                            ║
║ Holdout discipline: train windows for hypothesis development; holdout is   ║
║ touched ONCE per candidate parameter set. Repeatedly evaluating on holdout ║
║ defeats its purpose. See EXPERIMENT_CRYPTO_SCOPE.md.                       ║
║                                                                            ║
║   python walkforward_crypto.py                     # train windows         ║
║   python walkforward_crypto.py --lookback 60       # a hypothesis          ║
║   python walkforward_crypto.py --windows holdout   # ONE-SHOT validation   ║
╚════════════════════════════════════════════════════════════════════════════╝

Research only — this file never touches the live bot, the risk layer, or any
account. It reads market data and simulates.
"""
import argparse
import statistics
from datetime import datetime, timezone

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

# ── universe ────────────────────────────────────────────────────────────────
# Chosen for HISTORY, not for narrative: every pair below has enough daily bars
# to cover the windows plus lookback warmup. Pairs excluded for thin history:
# ADA (208 bars), FIL (205), XRP (982), DOT (1118). PAXG excluded separately —
# it is gold-backed and should sit near 15% annualized volatility, but the feed
# reports 172%, which is a data-quality problem rather than a market fact.
UNIVERSE = [
    "BTC/USD", "ETH/USD", "LINK/USD", "UNI/USD", "DOGE/USD", "BCH/USD", "LTC/USD",
    "SOL/USD", "AVAX/USD", "AAVE/USD",
]

# ── pre-registered windows (fixed 2026-09-08, before any result was seen) ───
# Data begins 2021-01-01; windows start in April to leave lookback warmup.
# Bars after 2026-04 are deliberately left unused as reserve.
TRAIN_WINDOWS = [
    ("2021-04-01", "2022-04-01"),   # the 2021 bull and its unwind
    ("2022-04-01", "2023-04-01"),   # the bear
    ("2023-04-01", "2024-04-01"),   # the recovery
]
HOLDOUT_WINDOWS = [
    ("2024-04-01", "2025-04-01"),
    ("2025-04-01", "2026-04-01"),
]

# ── strategy defaults ───────────────────────────────────────────────────────
LOOKBACK_DAYS  = 90    # trailing window used to rank
TOP_K          = 3     # how many to hold, equal-weighted
REBALANCE_DAYS = 7     # weekly
REGIME_MA      = 100   # BTC above its own N-day MA = risk-on
BARS_PER_YEAR  = 365   # crypto trades every day — NOT 252


def fetch(symbols, start="2020-12-01"):
    """Daily closes per symbol as {symbol: {date: close}}."""
    client = CryptoHistoricalDataClient()
    req = CryptoBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
    )
    raw = client.get_crypto_bars(req)
    out = {}
    for sym in symbols:
        bars = raw.data.get(sym, [])
        if bars:
            out[sym] = {b.timestamp.date(): b.close for b in bars}
    return out


def _calendar(data, start, end):
    """Sorted dates present in BTC (the reference clock) within [start, end)."""
    s, e = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    return sorted(d for d in data["BTC/USD"] if s <= d < e)


def _trailing_return(series, day, lookback):
    """Return over `lookback` days ending at `day`, or None if history is short."""
    days = sorted(d for d in series if d <= day)
    if len(days) < lookback + 1:
        return None
    then, now = series[days[-(lookback + 1)]], series[days[-1]]
    return (now / then - 1.0) if then > 0 else None


def _btc_risk_on(data, day, ma_days):
    """Crypto's regime proxy: is BTC above its own moving average?"""
    days = sorted(d for d in data["BTC/USD"] if d <= day)
    if len(days) < ma_days:
        return True                      # insufficient history -> don't gate
    closes = [data["BTC/USD"][d] for d in days[-ma_days:]]
    return closes[-1] > sum(closes) / len(closes)


def simulate(data, dates, lookback, top_k, rebalance_days, use_regime):
    """Equal-weight top-K by trailing return, rebalanced on a fixed schedule.

    Returns (equity_curve, n_rebalances). Frictionless by design: the question
    at this stage is whether a signal exists at all, and costs can only make a
    result worse. Any candidate that survives must be re-run with fees before
    it means anything.
    """
    equity, holdings, rebalances = [1.0], {}, 0

    for i, day in enumerate(dates):
        # Mark the book to today's prices before deciding anything.
        if i > 0 and holdings:
            prev = dates[i - 1]
            growth = 0.0
            for sym, w in holdings.items():
                p_now, p_prev = data[sym].get(day), data[sym].get(prev)
                growth += w * (p_now / p_prev if p_now and p_prev and p_prev > 0 else 1.0)
            equity.append(equity[-1] * growth)
        elif i > 0:
            equity.append(equity[-1])    # in cash

        if i % rebalance_days:
            continue

        if use_regime and not _btc_risk_on(data, day, REGIME_MA):
            holdings = {}                # risk-off: stand aside
            rebalances += 1
            continue

        ranked = []
        for sym, series in data.items():
            if day not in series:
                continue
            r = _trailing_return(series, day, lookback)
            if r is not None:
                ranked.append((r, sym))
        if not ranked:
            continue
        ranked.sort(reverse=True)
        picks = [s for _r, s in ranked[:top_k]]
        holdings = {s: 1.0 / len(picks) for s in picks}
        rebalances += 1

    return equity, rebalances


def buy_and_hold(data, dates):
    """Equal-weight buy-and-hold of the same universe — the benchmark."""
    members = [s for s in data if dates[0] in data[s]]
    equity = [1.0]
    for i in range(1, len(dates)):
        day, prev = dates[i], dates[i - 1]
        growth, n = 0.0, 0
        for sym in members:
            p_now, p_prev = data[sym].get(day), data[sym].get(prev)
            if p_now and p_prev and p_prev > 0:
                growth += p_now / p_prev
                n += 1
        equity.append(equity[-1] * (growth / n if n else 1.0))
    return equity


def stats(equity):
    """Total return %, annualized Sharpe, and max drawdown %."""
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity))
            if equity[i - 1] > 0]
    total = (equity[-1] / equity[0] - 1) * 100
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (statistics.mean(rets) / sd * (BARS_PER_YEAR ** 0.5)) if sd > 0 else 0.0
    peak, dd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak if peak > 0 else 0.0)
    return total, sharpe, dd * 100


def main():
    p = argparse.ArgumentParser(description="Crypto cross-sectional momentum walk-forward.")
    p.add_argument("--windows", choices=["train", "holdout", "all"], default="train")
    p.add_argument("--lookback", type=int, default=LOOKBACK_DAYS)
    p.add_argument("--top-k", type=int, default=TOP_K)
    p.add_argument("--rebalance", type=int, default=REBALANCE_DAYS)
    p.add_argument("--no-regime", action="store_true", help="disable the BTC regime gate")
    args = p.parse_args()

    if args.windows == "train":
        windows = TRAIN_WINDOWS
    elif args.windows == "holdout":
        windows = HOLDOUT_WINDOWS
        print("⚠️  HOLDOUT RUN — do this ONCE per candidate parameter set.")
        print("   Re-running holdout to search for what works is curve-fitting.\n")
    else:
        windows = TRAIN_WINDOWS + HOLDOUT_WINDOWS
        print("⚠️  Includes holdout windows — not a clean validation run.\n")

    print("=" * 92)
    print(" EXP6 — CROSS-SECTIONAL MOMENTUM, CRYPTO")
    print("=" * 92)
    print(f"  universe:  {len(UNIVERSE)} pairs")
    print(f"  params:    lookback {args.lookback}d · top {args.top_k} · "
          f"rebalance {args.rebalance}d · regime gate {'off' if args.no_regime else f'BTC>{REGIME_MA}d MA'}")
    print(f"  benchmark: equal-weight buy-and-hold of the same universe")
    print(f"  windows:   {len(windows)} ({args.windows})")
    print()

    data = fetch(UNIVERSE)
    missing = [s for s in UNIVERSE if s not in data]
    if missing:
        print(f"  warning: no data for {missing}")
    if "BTC/USD" not in data:
        print("  BTC/USD is the reference clock and is missing — aborting.")
        return

    rows = []
    for start, end in windows:
        dates = _calendar(data, start, end)
        if len(dates) < args.lookback + args.rebalance:
            print(f"  {start} → {end}: insufficient history; skipped.")
            continue
        eq, n_rb = simulate(data, dates, args.lookback, args.top_k,
                            args.rebalance, not args.no_regime)
        bh = buy_and_hold(data, dates)
        s_ret, s_sharpe, s_dd = stats(eq)
        b_ret, b_sharpe, b_dd = stats(bh)
        rows.append({
            "label": f"{start[:7]} → {end[:7]}", "ret": s_ret, "bench": b_ret,
            "alpha": s_ret - b_ret, "sharpe": s_sharpe, "b_sharpe": b_sharpe,
            "dsharpe": s_sharpe - b_sharpe, "dd": s_dd, "b_dd": b_dd, "rb": n_rb,
        })

    if not rows:
        print("  No windows produced results.")
        return

    print(f"  {'Window':18s} {'Return':>9s} {'Bench':>9s} {'Alpha':>9s} "
          f"{'Sharpe':>7s} {'BenchSh':>8s} {'ΔSharpe':>8s} {'MaxDD':>7s} {'BenchDD':>8s}")
    print("  " + "-" * 88)
    for r in rows:
        print(f"  {r['label']:18s} {r['ret']:+8.2f}% {r['bench']:+8.2f}% {r['alpha']:+8.2f}% "
              f"{r['sharpe']:+7.2f} {r['b_sharpe']:+8.2f} {r['dsharpe']:+8.2f} "
              f"{r['dd']:6.1f}% {r['b_dd']:7.1f}%")

    n = len(rows)
    avg_alpha = sum(r["alpha"] for r in rows) / n
    avg_dsharpe = sum(r["dsharpe"] for r in rows) / n
    beat_sharpe = sum(1 for r in rows if r["dsharpe"] > 0)
    beat_alpha = sum(1 for r in rows if r["alpha"] > 0)

    print()
    print("=" * 92)
    print(" SUMMARY — risk-adjusted first")
    print("=" * 92)
    print(f"  windows beating benchmark on SHARPE:   {beat_sharpe}/{n}   <- the primary test")
    print(f"  average ΔSharpe vs benchmark:          {avg_dsharpe:+.2f}")
    print(f"  windows beating benchmark on return:   {beat_alpha}/{n}")
    print(f"  average alpha:                         {avg_alpha:+.2f}%")
    print(f"  worst drawdown (strategy / benchmark): "
          f"{max(r['dd'] for r in rows):.1f}% / {max(r['b_dd'] for r in rows):.1f}%")
    print()
    print("  PRE-REGISTERED RULE: a candidate advances to holdout only if it beats")
    print("  the benchmark on Sharpe in at least 2 of 3 train windows. Holdout is")
    print("  evaluated ONCE. Results are frictionless — fees and slippage can only")
    print("  make them worse, and Alpaca's crypto book is thin.")
    print("=" * 92)


if __name__ == "__main__":
    main()
