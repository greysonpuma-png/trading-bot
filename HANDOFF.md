# Trading Bot — Handoff Doc

_Last updated: 2026-06-24. Read this first. It tells you exactly what the project
is, exactly how to run it, exactly what each number should look like, and exactly
what to do when something looks wrong._

> **TL;DR for a hurried reader:** The bot is running on its own. Don't change
> anything about how it trades. Around **September 3, 2026**, run one command
> (`python forward_test.py`, §6) and look at one number (**alpha**). That number
> decides what happens next. Everything else below is detail and troubleshooting.

---

## TABLE OF CONTENTS
1. What this project is
2. The one thing you must understand (no edge)
3. Exact current state (account, positions, settings)
4. The September decision — exact date and exact rule
5. The hard rules: what NOT to do, and why
6. How to run it — every command, with the output you should expect
7. Troubleshooting — symptom → check → fix
8. The 10 risk checks (what the safety layer blocks)
9. File map
10. Glossary (plain-English definitions)

---

## 1. WHAT THIS PROJECT IS

An autonomous LLM-driven **swing trading bot** trading a **paper** (fake-money)
Alpaca account. Flow each cycle:

1. A pure-Python **screener** scans 39 stocks for setups (no AI).
2. A 3-stage AI pipeline decides what to do, each stage running Gemini 2.5 Flash:
   - **Position Manager** — reviews holdings, decides hold/close.
   - **Scout** — picks the single best new candidate, or passes.
   - **Risk Manager** — sizes the trade and submits it.
3. A hard-coded **risk layer** (`risk_layer.py`) vets every order before the broker
   sees it (see §8).
4. Filled positions get a broker-side **trailing stop** so they're protected even
   if the bot or the Mac dies.

It runs hands-free: auto-starts at login, wakes the Mac before market open.

- **GitHub:** https://github.com/greysonpuma-png/trading-bot
- **Code folder:** `~/Documents/trading-bot/trading_agent_swing/`
- **Goal:** to be a **profitable** trading system — to beat a simple buy-and-hold
  of SPY. Whether it can is being tested live right now (see §2 and §4).

---

## 2. THE GOAL — AND THE HONEST STATUS

**The goal of this bot is to be profitable: to beat a simple buy-and-hold of SPY.**

**Honest status as of 2026-06-24: it has not done that yet.** We tested three
completely different strategies (daily pullback/breakout, weekly Donchian
trend-following, sector rotation) using proper out-of-sample validation, and all
three underperformed buy-and-hold SPY. We also showed, on the bot's own data, that
leverage and fancy exit techniques change the *risk* of the returns but do not
create *edge* — the repeatable advantage that actually produces profit.

This is not "give up." It means the path to profitability runs through finding a
real, validated edge — **not** through piling more risk or cleverness onto a
strategy that hasn't shown one (that just loses faster; we proved it). The live
forward test (§4) is the current attempt: it measures whether the trailing-exit
version can beat SPY going forward. **Until that shows positive alpha over a
meaningful stretch, treat the bot as _not yet profitable_, and do not put real
money behind it (§5).** The honest scoreboard is alpha vs SPY — nothing else.

---

## 3. EXACT CURRENT STATE (snapshot 2026-06-24 — these numbers drift daily)

**Account:** equity ≈ $100,687 · cash ≈ $66,196 · started at $100,000.

**Open positions (8):**

| Symbol | Shares | Entry | Recent price | Unrealized P/L |
|--------|--------|-------|--------------|----------------|
| GS  | 4  | $1015.79 | $1082.06 | +$265 |
| HD  | 14 | $325.29  | $335.68  | +$145 |
| JNJ | 50 | $233.81  | $241.62  | +$391 |
| SPY | 2  | $734.34  | $736.26  | +$4   |
| V   | 14 | $326.83  | $328.23  | +$20  |
| WMT | 21 | $117.00  | $119.48  | +$52  |
| XLI | 13 | $179.55  | $180.21  | +$9   |
| XLV | 16 | $153.28  | $153.91  | +$10  |

**Settings (in `trading_agent_swing/.env` and `config.py`) — do not change these
during the experiment (§4):**

| Setting | Value | Meaning |
|---|---|---|
| `ALPACA_PAPER` | `true` | Fake money. **Keep it true.** |
| `EXIT_STYLE` | `trailing` | The experiment being tested. Don't change. |
| `TRAIL_PERCENT` | `10` | Sell after a position falls 10% from its peak. |
| `MODEL_PROVIDER` | `gemini` | Cloud LLM backend. |
| `auto_execute` | `True` | Bot places trades itself (no manual approval). |
| `max_position_size_usd` | `2500` | Most it will put in one position. |
| `max_daily_loss_usd` | `500` | Stops trading for the day if down this much. |
| `max_open_positions` | `8` | Most positions held at once (currently at 8). |
| `max_positions_per_sector` | `3` | Diversification cap. |
| `max_order_qty` | `100` | Max shares per order. |

---

## 4. THE SEPTEMBER DECISION — EXACT DATE AND RULE

We pre-committed to a clean forward test so the decision is made by **data**, not
by impatience or a good/bad week.

- **Baseline (experiment start):** 2026-06-11, account ≈ $99,633.
- **First meaningful read:** **~September 3, 2026** (≈60 trading days in — the
  earliest point the numbers aren't pure noise).
- **Full verdict:** **~December 11, 2026** (≈6 months / ~125 trading days).
- **What to do on that date:** run `python forward_test.py` (§6) and read the
  **ALPHA (acct − SPY)** line.

**Decision rule (decided in advance, do not move the goalposts):**
- **Alpha clearly positive** (e.g. > +2–3% and trending up) → the trailing-exit
  change may have merit. Keep running; consider the next honest step.
- **Alpha negative or ~zero** → the change is refuted, exactly as the backtests
  predicted. Stop here; the bot has answered honestly.

Before that date, **9 days or 9 weeks of green or red means nothing.** Do not react
to it. The whole point of naming a date in advance is to not trade on emotion.

---

## 5. THE HARD RULES — WHAT NOT TO DO

1. **Do NOT set `ALPACA_PAPER=false` (do not go to real money).** The bar is months
   of *positive forward alpha* + money you can afford to lose entirely + a written
   stop rule. None are met. There is no near-term path to this.
2. **Do NOT add risk to "drive profits"** — no leverage, no bigger `max_position_size_usd`,
   no looser stops. We proved on the bot's own data that this makes a no-edge
   strategy lose *faster*, not win. (Demo: `python walkforward.py --leverage 3`.)
3. **Do NOT change the trading logic before the September read.** Any change resets
   the experiment and throws away the only clean test we have.
4. **Do NOT add new "advanced strategies" expecting profit.** We tested several;
   they don't beat SPY, and the historical data is now over-tested.

Safe to do anytime: read the dashboard, run the scoreboard, restart the bot,
run the tests, read the logs.

---

## 6. HOW TO RUN IT — COMMANDS + EXPECTED OUTPUT

**The activate chunk (always run this first in a new Terminal window):**
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate
```
You'll know it worked when your prompt shows `(.venv)` at the start.

---

**A. Is the bot alive?**
```bash
cat ~/Documents/trading-bot/trading_agent_swing/logs/heartbeat.txt && echo
```
- **Expected (good):** a timestamp within the last ~1 hour during market hours.
  Example: `2026-06-24T11:13:13` when it's around 11–12am.
- **Bad:** timestamp more than ~2 hours old during market hours (7:30am–2:00pm
  Mountain). → go to §7.

---

**B. See the dashboard** (the nice visual view):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && streamlit run dashboard.py
```
- A browser tab opens at http://localhost:8501.
- **Top banner:** green "Bot alive" = good; red = see §7.
- **Sidebar:** equity, cash, and each open position with live P/L.
- **Main chart "Account vs SPY":** the line that matters. Above SPY = beating it.
- To close it: press **Ctrl+C** in that Terminal. (This stops the dashboard only,
  NOT the bot.)

---

**C. The forward-test scoreboard** (the September read):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python forward_test.py
```
Expected output looks like:
```
 EXP4 FORWARD TEST — trailing exits, live paper account
  baseline:           2026-06-11  ($99,633.45)
  trading days since: 9
  account:            $100,356.81  (+0.73%)
  SPY buy-and-hold:   -0.33%
  ALPHA (acct - SPY): +1.06%
  note: 9 trading days is NOISE...
```
The number you care about is **ALPHA**. Ignore it entirely until ~Sept 3 (§4).

---

**D. Restart the bot** (after it dies, or after any code change):
```bash
pkill -f "main.py loop"; pkill -f "caffeinate -i python"
open ~/Documents/trading-bot/start_bot.command
```
- A new Terminal window opens with a banner: `SWING Trading Agent | mode: PAPER`.
  **That window IS the bot. Leave it open. Never type into it.**
- Verify with command A — the heartbeat should be fresh within ~30 seconds.

---

**E. Run the tests** (after editing any code; all should pass):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python -m pytest -q
```
- **Expected:** `30 passed` (a number may grow if tests are added).
- **Bad:** any "failed" → a safety check broke. Do NOT run the bot until fixed.

---

**F. Emergency — sell everything now:**
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python main.py panic
```
Type `YES` when asked. Flattens all positions and cancels all orders.

---

## 7. TROUBLESHOOTING — SYMPTOM → CHECK → FIX

**Heartbeat is stale (older than ~2 hours during market hours):**
- *Most common cause:* the Mac slept (lid closed / overnight / weekend). The bot
  freezes while the Mac sleeps and resumes on wake. If you just opened the laptop,
  wait ~2 minutes and re-check command A — it should refresh on its own.
- *If it stays stale with the Mac awake and market open:* the bot died or hung.
  **Fix:** restart it (§6D).
- *Either way, your money is safe* — the stops live at Alpaca, not on the Mac.

**No bot window anywhere / `cat heartbeat` shows a very old date:**
- The bot isn't running. **Fix:** restart it (§6D).

**Dashboard shows a red "Bot may be hung" banner:**
- Same as a stale heartbeat. Restart (§6D).

**`streamlit: command not found`:**
- You forgot the activate chunk. Run the `cd ... && source .venv/bin/activate`
  line first, then the streamlit command (§6B).

**A command pastes weirdly / shows `[200~`:**
- A copy-paste glitch. Type the command by hand, or paste it as a single line.

**You see "market closed, sleeping" over and over:**
- Normal. The market is closed (nights, weekends, holidays). The bot only trades
  during market hours. Nothing is wrong.

---

## 8. THE 10 RISK CHECKS (what `risk_layer.py` blocks)

Every proposed order must pass ALL of these or it is rejected before reaching the
broker. The LLM cannot override them — they are plain Python:

1. Symbol must be on the 39-name approved whitelist.
2. Quantity must be positive and ≤ `max_order_qty` (100).
3. Market must be open.
4. Daily loss must be under `max_daily_loss_usd` ($500) — else trading halts for the day.
5. Position value must be ≤ `max_position_size_usd` ($2500).
6. Must not exceed `max_open_positions` (8).
7. No shorting; can't sell shares you don't own.
8. Must have enough buying power.
9. No more than `max_positions_per_sector` (3) in one sector.
10. Exit protection must be valid (in trailing mode: trail % within 3–15%).

These are covered by automated tests in `test_risk_layer.py` (run with §6E).

---

## 9. FILE MAP (inside `trading_agent_swing/`)

| File | What it is |
|---|---|
| `risk_layer.py` | **Most important.** The 10 hard checks (§8). |
| `test_risk_layer.py`, `test_resilience.py` | 30 tests for safety + anti-hang logic. |
| `agent.py` | The 3-stage AI pipeline + per-cycle prompts. |
| `tools.py` | The 11 functions the AI can call (+ per-cycle data cache). |
| `screener.py` | Pure-Python candidate finder (no AI). |
| `broker.py` | Alpaca connection (has the network-timeout fix). |
| `gemini_client.py` | Gemini AI backend. |
| `main.py` | The loop + 5-minute hang watchdog + log rotation. |
| `config.py` | All settings/risk limits; reads `.env`. |
| `dashboard.py` | The Streamlit dashboard. |
| `forward_test.py` | The September alpha-vs-SPY scoreboard. |
| `walkforward*.py` | The 3 research backtesters (not live). |
| `backtest.py` | Quick single-window backtest. |
| `logs/` | heartbeat, AI trace, and the trade record (proposals/journal/picks). |
| `.env` | Secrets + settings. **Never commit this to GitHub.** |

Repo-root scripts: `start_bot.command`, `setup_autostart.sh`, `setup_market_wake.sh`,
`setup_health_alert.sh` (+ matching `stop_*` versions).

---

## 10. GLOSSARY (plain English)

- **Alpha** — how much you beat (or lost to) SPY. +2% alpha = you did 2% better
  than just holding SPY. This is the only scoreboard that matters here.
- **SPY** — an ETF that tracks the S&P 500. "Buying SPY and holding" is the simple
  benchmark the bot is trying (and so far failing) to beat.
- **Paper trading** — trading with fake money on real market data. Zero real
  dollars at risk.
- **Trailing stop** — an order that follows the price up and sells if it falls a
  set % (here 10%) from its highest point. Locks in gains, caps losses.
- **Edge** — a real, repeatable advantage that makes a strategy beat the benchmark.
  This strategy hasn't demonstrated one yet — which is exactly what the forward
  test (§4) is checking. Without edge, no amount of risk or cleverness produces
  profit, so finding edge is the only real path to the profitability goal.
- **Heartbeat** — a timestamp file the bot updates every loop, so you can tell it's
  alive without reading logs.
- **Walk-forward / out-of-sample test** — testing a strategy on data it was never
  tuned on. The honest way to tell if a backtest is real or just curve-fit.
- **Forward test** — testing live, going forward in time (what the paper bot is
  doing now). The cleanest test of all.

---

## IF YOU ONLY REMEMBER ONE THING
Leave the bot alone until ~September 3, 2026. Then run `python forward_test.py` and
read the alpha. That one number — not a hunch, not a good week — decides what's next.
