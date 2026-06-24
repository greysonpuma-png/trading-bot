# Trading Bot — Handoff Doc

_Last updated: 2026-06-24. This is the "read me first" status doc — where the
project stands, how to run it, and what's intentionally being left alone._

---

## 1. What this project is (in one paragraph)

An autonomous LLM-driven **swing trading bot** that trades a **paper** (fake-money)
Alpaca account. A Python screener finds candidate stocks; a 3-stage LLM pipeline
(Position Manager → Scout → Risk Manager, running on Gemini 2.5 Flash) decides
what to trade; a hard-coded Python **risk layer** vets every order before it
reaches the broker. It runs hands-free on the MacBook — auto-starts at login,
wakes the Mac before market open, and protects every position with broker-side
stops. It is a **learning / research / portfolio project**, NOT a money-maker
(see §3).

Repo: https://github.com/greysonpuma-png/trading-bot
Code lives in: `~/Documents/trading-bot/trading_agent_swing/`

---

## 2. Current status (2026-06-24)

- **Bot:** running (paper mode). Verify anytime — see §5.
- **Live experiment in progress:** "Exp4" — trailing-stop exits (let winners run,
  cut losers). Switched on 2026-06-11. Being measured as alpha vs SPY.
- **Forward-test scoreboard:** ~+1% alpha over ~9 trading days — **this is noise**,
  far too short to mean anything. The real read is in September (see §4).
- **Account:** ~$100k paper, roughly flat-to-slightly-up since inception.
- **Code:** all committed and pushed; 30 automated tests passing.

---

## 3. The single most important thing to understand

**The strategy has no demonstrated edge.** We tested three structurally different
strategies (daily pullback/breakout, weekly Donchian trend-following, sector
rotation) with proper train/holdout walk-forward validation. **All three lost to
just buying and holding SPY** out-of-sample. We also demonstrated that leverage,
partial-profit-taking, and other "advanced" techniques reshape the *risk* of the
returns but never create *edge*.

**What this means for decisions:**
- Do **NOT** flip the bot to real money (`ALPACA_PAPER=false`). The honest bar for
  that is months of positive *forward* alpha + a tuition-sized loss budget + a
  pre-committed stop rule — none of which are met.
- Do **NOT** add risk (leverage, bigger size, looser stops) "to drive profits."
  On a no-edge strategy that just loses faster — we proved this on the bot's own data.
- The *value* of this project is the engineering + the rigorous methodology + the
  honest negative result. That's a genuinely strong story for an internship or
  grad-school interview. It is not a P&L story.

---

## 4. The September decision point

We pre-committed to a clean forward test: don't change the strategy, let it run,
and read the result at a fixed future date so the decision is made by data, not
by impatience.

- **When:** ~early September 2026 (≈60 trading days of forward data — the earliest
  point worth reading; ~December = ~6 months = the real verdict).
- **How:** run the scoreboard (see §5) and look at **alpha vs SPY**.
- **Decision rule (pre-registered):**
  - Sustained **positive** alpha vs SPY → Exp4 (trailing exits) may have merit;
    keep running, consider the next honest step.
  - **Negative** alpha → Exp4 is refuted, same as the backtests predicted. Stop.
- Until then: **do not change the bot's trading logic.** Any change resets the
  experiment and contaminates the comparison.

---

## 5. How to operate it (commands)

**Activate first** (the one chunk to remember):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate
```

**Is the bot alive?** Heartbeat timestamp should be within ~1 hour during market hours:
```bash
cat ~/Documents/trading-bot/trading_agent_swing/logs/heartbeat.txt && echo
```

**See the dashboard** (positions, P&L, SPY benchmark chart, bot-health banner):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && streamlit run dashboard.py
```
Opens http://localhost:8501. Ctrl+C in that terminal to stop it (this does NOT stop the bot).

**Forward-test scoreboard** (the September read):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python forward_test.py
```

**Restart the bot** (if it died, or after a code change):
```bash
pkill -f "main.py loop"; pkill -f "caffeinate -i python"
open ~/Documents/trading-bot/start_bot.command
```
A Terminal window opens — that window *is* the bot. Leave it open; don't type in it.

**Run the tests** (after any code change to the risk layer or core files):
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python -m pytest -q
```

**Emergency: close everything:**
```bash
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python main.py panic
```

---

## 6. Known limitations (by design, not bugs)

- **Sleeping laptop = coverage gaps.** The bot and its health-watchdog are local
  processes. If the Mac sleeps (lid closed) or shuts down, the bot is simply off
  until it's awake again. Auto-wake covers weekday market opens; weekends/overnight
  with the lid closed will have gaps. Positions stay safe regardless — the stops
  live at Alpaca, not on the Mac. The real fix (a cloud host) is deferred until
  September says whether the strategy is worth hosting.
- **Hangs are now bounded, not eliminated.** A per-cycle 5-minute watchdog means a
  hang self-recovers within ~5 min while the Mac is awake. (Three multi-day silent
  hangs earlier were traced to a missing network timeout and fixed.)
- **Two leftover exit orders.** A couple of older positions (e.g. WMT, V) still
  carry original fixed take-profit orders from before the June 11 switch; newer
  positions use trailing stops. Minor inconsistency, harmless (extra protection).

---

## 7. File map (in `trading_agent_swing/`)

| file | what it is |
|---|---|
| `risk_layer.py` | **Most important.** 10 hard checks every order must pass. |
| `test_risk_layer.py` / `test_resilience.py` | 30 tests proving the safety + anti-hang logic. |
| `agent.py` | The 3-stage LLM pipeline (Position Manager → Scout → Risk Manager). |
| `tools.py` | The 11 functions the LLM can call (+ intra-cycle cache). |
| `screener.py` | Pure-Python candidate finder (no LLM). |
| `broker.py` | Alpaca wrapper (paper or live). Has the network-timeout fix. |
| `gemini_client.py` | Gemini backend, mimics the Ollama interface. |
| `main.py` | Entry point + the loop + the SIGALRM cycle watchdog + log rotation. |
| `config.py` | All knobs: risk limits, `EXIT_STYLE`, symbol list. Reads `.env`. |
| `dashboard.py` | Streamlit dashboard. |
| `walkforward*.py` | The 3 walk-forward backtesters (research, not live). |
| `forward_test.py` | Live alpha-vs-SPY scoreboard for Exp4. |
| `backtest.py` | Single-window backtest (quick checks). |
| `logs/` | heartbeat, agent trace, proposals/journal/picks (the trade record). |

Operational scripts in the repo root: `start_bot.command`, `setup_autostart.sh`,
`setup_market_wake.sh`, `setup_health_alert.sh` (+ matching `stop_*` scripts).

Config: secrets live in `trading_agent_swing/.env` (NOT in git). `EXIT_STYLE=trailing`,
`TRAIL_PERCENT=10`, `ALPACA_PAPER=true`, `MODEL_PROVIDER=gemini`.

---

## 8. If you only do one thing

Leave it alone until September, then run `forward_test.py` and read the alpha.
Everything else — adding strategies, leverage, going live — has been tested or
reasoned through and the answer is "not until the data earns it."
