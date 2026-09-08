"""
Exit-timing analysis — did selling at the profit target leave money on the table?

The question this exists to answer, empirically rather than by argument: the
mandate exits on RSI >= 60 (a statistical reversion signal) OR gain >= +6% (a
fixed accounting rule). For every exit the bot actually made, what did the price
do over the following 5, 10, and 20 trading days?

Reading the output:
  - Forward returns near ZERO  -> the exit was well timed; the move was spent.
  - Forward returns POSITIVE   -> the bot sold too early and capped a winner.
                                  A consistently positive number under 'gain'
                                  is the profit-target trap showing up in data.
  - Forward returns NEGATIVE   -> the exit dodged a decline; good timing.

Comparing the 'rsi' and 'gain' rows is the real payoff: it says whether the
signal timed exits better than the accounting rule.

Nothing here influences trading. It reads logs/exits.jsonl (written at exit
time, with no knowledge of the future) and fetches price history afterwards.

Run: python exit_analysis.py
"""
import json
import os
import statistics
from datetime import datetime, timedelta

from config import CONFIG

HORIZONS = (5, 10, 20)     # trading days after the exit


def _load_exits():
    path = os.path.join(CONFIG.log_dir, "exits.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _forward_returns(broker, symbol, exit_iso, exit_price):
    """Return {horizon: pct_change} for bars strictly AFTER the exit date."""
    exit_day = datetime.fromisoformat(exit_iso).date()
    # Enough calendar days to cover the longest horizon plus weekends/holidays.
    need = max(HORIZONS) + 15
    try:
        bars = broker.get_bars(symbol, "1Day", limit=need + 40)
    except Exception:
        return None
    after = [b for b in bars if _bar_date(b) > exit_day]
    if not after or not exit_price:
        return None
    out = {}
    for h in HORIZONS:
        if len(after) >= h:
            out[h] = (after[h - 1]["close"] / exit_price - 1.0) * 100.0
    return out or None


def _bar_date(bar):
    t = bar.get("timestamp") or bar.get("t")
    if isinstance(t, str):
        return datetime.fromisoformat(t.replace("Z", "+00:00")).date()
    return t.date() if hasattr(t, "date") else datetime.now().date()


def main():
    exits = _load_exits()
    line = "=" * 68
    print(line)
    print(" EXIT TIMING ANALYSIS — did the profit target cost us anything?")
    print(line)

    if not exits:
        print("  No exits recorded yet. logs/exits.jsonl is written when the")
        print("  Position Manager's sells execute under the mean-reversion mandate.")
        print(line)
        return

    from broker import Broker
    broker = Broker()

    by_rule = {}
    matured = 0
    print(f"  {len(exits)} exit(s) recorded\n")
    print(f"  {'date':11s} {'sym':6s} {'rule':6s} {'RSI':>5s} {'gain':>7s}"
          + "".join(f" {'+' + str(h) + 'd':>8s}" for h in HORIZONS))
    print("  " + "-" * 64)

    for e in exits:
        fwd = _forward_returns(broker, e["symbol"], e["timestamp"], e.get("exit_price"))
        rule = e.get("exit_rule") or "—"
        rsi = e.get("rsi_at_exit")
        gain = e.get("gain_pct_at_exit")
        cells = ""
        for h in HORIZONS:
            v = (fwd or {}).get(h)
            cells += f" {v:>+7.2f}%" if v is not None else f" {'pending':>8s}"
        print(f"  {e['timestamp'][:10]:11s} {e['symbol']:6s} {rule:6s} "
              f"{rsi if rsi is not None else '—':>5} "
              f"{(f'{gain:+.1f}%' if gain is not None else '—'):>7s}{cells}")
        if fwd:
            matured += 1
            by_rule.setdefault(rule, []).append(fwd)

    if not by_rule:
        print("\n  No exits have matured past the shortest horizon yet —")
        print(f"  re-run once {min(HORIZONS)} trading days have passed since an exit.")
        print(line)
        return

    print(f"\n  AVERAGE FORWARD RETURN AFTER EXIT  (n={matured} matured)")
    print(f"  {'rule':10s} {'n':>4s}" + "".join(f" {'+' + str(h) + 'd':>9s}" for h in HORIZONS))
    print("  " + "-" * 44)
    for rule in sorted(by_rule):
        rows = by_rule[rule]
        cells = ""
        for h in HORIZONS:
            vals = [r[h] for r in rows if h in r]
            cells += f" {statistics.mean(vals):>+8.2f}%" if vals else f" {'—':>9s}"
        print(f"  {rule:10s} {len(rows):>4}{cells}")

    print()
    print("  positive = sold too early (capped a winner)")
    print("  ~zero    = well-timed exit, move was spent")
    print("  negative = dodged a decline")
    print()
    print("  Compare 'gain' (fixed +6% target) against 'rsi' (reversion signal):")
    print("  a consistently positive 'gain' row is the profit-target trap in data.")
    print(line)


if __name__ == "__main__":
    main()
