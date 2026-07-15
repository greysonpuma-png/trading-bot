# Whale Watch

What the famous 13F filers (Buffett, Dalio's Bridgewater, RenTec, Ackman,
Burry, Druckenmiller) held last quarter and what changed — straight from SEC
EDGAR, no API key.

```bash
cd whale_watch
../trading_agent_swing/.venv/bin/python whales.py            # all filers, summary
../trading_agent_swing/.venv/bin/python whales.py buffett    # one filer, full detail
../trading_agent_swing/.venv/bin/python whales.py --list     # who's tracked
```

`[TICKER*]` marks stocks that are also on the trading bot's whitelist.

**Deliberately not wired into the bot.** 13F snapshots are quarterly and
filed up to 45 days late, from investors with 5–30 year horizons — a
learning tool for how the greats position, not a timing signal for a
days-to-weeks swing bot. It also keeps the forward test's inputs frozen.
If the September forward-test read justifies it, a 13F-based signal would
be designed as its own pre-registered experiment.
