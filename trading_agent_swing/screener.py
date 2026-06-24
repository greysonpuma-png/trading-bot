"""
Market pre-screener.

This runs in PURE PYTHON — no LLM involved. That is the whole point: a small local
model does not reliably grind through 39 symbols looking for setups, so we don't
ask it to. Python does the systematic scan every cycle (it never gets bored or
quits early), and hands the agent a short, ranked list of real candidates to judge.

The screen looks for a classic swing-trade entry:
  - the stock is in an established uptrend (price above its 50-day moving average)
  - its 20-day moving average is rising
  - price has pulled back close to that rising 20-day MA (a buyable dip, not a chase)
"""
from config import CONFIG
from broker import Broker


# ── screen parameters ──
MA_FAST          = 20      # pullback-reference moving average
MA_SLOW          = 50      # trend filter
RISING_LOOKBACK  = 5       # the fast MA must be higher than it was this many days ago
PULLBACK_LOW     = -1.0    # price may dip slightly below the fast MA (% terms)
PULLBACK_HIGH    = 4.0     # ...up to this far above it — beyond that it's a chase
BARS_NEEDED      = MA_SLOW + 5


def _sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _rsi(values, n=14):
    """Relative Strength Index over the last n periods. None if not enough data."""
    if len(values) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain, avg_loss = gains / n, losses / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def _ema_series(values, period):
    """Exponential moving average series, seeded with a simple average."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    out = [ema]
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _macd(closes):
    """MACD (12/26/9). Returns (macd_line, signal_line, bullish). 'bullish' is
    True when the MACD line sits above its signal line — a common momentum read.
    Returns (None, None, None) if there isn't enough history."""
    if len(closes) < 35:
        return None, None, None
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    n = min(len(ema12), len(ema26))
    if n < 10:
        return None, None, None
    macd_line = [ema12[-n + i] - ema26[-n + i] for i in range(n)]
    signal = _ema_series(macd_line, 9)
    if not signal:
        return round(macd_line[-1], 3), None, None
    macd_v, sig_v = macd_line[-1], signal[-1]
    return round(macd_v, 3), round(sig_v, 3), bool(macd_v > sig_v)


def scan_market(broker=None, top_n=5):
    """Screen every allowed symbol. Returns a ranked list of candidate dicts,
    best setup first. Never raises for a single bad symbol — it just skips it.
    """
    if broker is None:
        broker = Broker()

    candidates = []
    for sym in CONFIG.allowed_symbols:
        try:
            bars = broker.get_bars(sym, "1Day", limit=BARS_NEEDED + 10)
        except Exception:
            continue
        closes = [b["close"] for b in bars]
        if len(closes) < BARS_NEEDED:
            continue

        price      = closes[-1]
        ma_fast    = _sma(closes, MA_FAST)
        ma_slow    = _sma(closes, MA_SLOW)
        ma_fast_be = _sma(closes[:-RISING_LOOKBACK], MA_FAST)  # fast MA N days ago
        if not (ma_fast and ma_slow and ma_fast_be):
            continue

        uptrend   = price > ma_slow
        ma_rising = ma_fast > ma_fast_be
        pct_above = (price - ma_fast) / ma_fast * 100.0
        in_band   = PULLBACK_LOW <= pct_above <= PULLBACK_HIGH

        if uptrend and ma_rising and in_band:
            # Closer to the moving average = a cleaner pullback = higher score.
            score = round(PULLBACK_HIGH - abs(pct_above), 2)
            macd_v, _macd_sig, macd_bull = _macd(closes)
            candidates.append({
                "symbol":         sym,
                "price":          round(price, 2),
                "ma20":           round(ma_fast, 2),
                "ma50":           round(ma_slow, 2),
                "pct_above_ma20": round(pct_above, 2),
                "rsi":            _rsi(closes),
                "macd":           macd_v,
                "macd_bullish":   macd_bull,
                "sector":         CONFIG.sector_map.get(sym, "unknown"),
                "setup":          "pullback to rising 20-day MA in an uptrend",
                "score":          score,
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]


if __name__ == "__main__":
    # Quick manual test: python screener.py
    results = scan_market(top_n=8)
    if not results:
        print("No candidates passed the screen today.")
    else:
        print(f"{len(results)} candidate(s):")
        for c in results:
            print(f"  {c['symbol']:6s} ${c['price']:>8.2f}  "
                  f"{c['pct_above_ma20']:+5.2f}% vs 20MA  [{c['sector']}]  score {c['score']}")
