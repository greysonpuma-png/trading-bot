# Autonomous LLM Swing Trading Agent

A research project: an autonomous LLM-driven trading bot that runs 24/7 on
a $4/month VPS (originally on my laptop — the reliability section explains
why it moved), trades paper-only through the Alpaca API, and was used as a
sandbox for rigorous walk-forward backtesting of multiple swing-trading
strategy frameworks.

**The bottom-line finding:** across three structurally different strategy
frameworks tested with proper train/holdout walk-forward validation, none
produced positive alpha vs SPY buy-and-hold out-of-sample. The bot runs
autonomously and correctly, but the strategies it operates do not have
demonstrable edge. This document explains what was built, what was tested,
and what the data actually said.

This is — explicitly — a learning project. The value is in the methodology
and infrastructure, not in the simulated P&L.

**Current status (July 2026):** a fourth, pre-registered experiment —
trailing-stop exits — is running live on the paper account as a true
out-of-sample forward test (baseline 2026-06-11; first meaningful read
~Sept 3, 2026; full verdict ~Dec 2026). The scoreboard is one command
(`python forward_test.py`) and one number (alpha vs SPY), with the
decision rule written down in advance so the result can't be
rationalized after the fact. See `HANDOFF.md` at the repo root for the
operating rules while the test runs.

Two mid-test operational notes, recorded for honesty: on 2026-07-08,
position sizing was raised (~20% → ~60% target deployment) and a
per-symbol cap bug was fixed, so alpha comparisons spanning that date mix
two sizing regimes; and on 2026-07-15 the bot moved from my MacBook to an
always-on VPS, which ended the laptop-sleep coverage gaps described below.

---

## TL;DR for someone scanning this in 60 seconds

**What I built:**
- A 3-stage LLM agent pipeline (Position Manager → Scout → Risk Manager) that
  proposes and executes swing trades autonomously on an Alpaca paper account
- A pure-Python screener that scans 39 tickers each cycle for technical setups
- A hard-coded risk layer with 10 safety checks that every proposed trade
  must pass before reaching the broker
- Broker-side bracket orders so positions stay protected even if the bot,
  the Mac, or the LLM provider goes down
- A Streamlit dashboard with live positions, P&L, an SPY benchmark chart,
  and a bot-health indicator
- Runs 24/7 hands-free as a `systemd` service on a $4/month VPS, after the
  laptop-hosting era ended in a diagnosed macOS power-management failure
  mode (full story in the reliability section)
- Pluggable backend: local Ollama (`qwen3:4b`) or Gemini cloud API, swap via
  one `.env` line

**What I tested rigorously:**
| Strategy framework | Train α | Holdout α |
|---|---|---|
| Daily pullback to MA + breakout entries (with regime filter) | −6.78% | −1.88% |
| Weekly Donchian trend-following (slower-tuned candidate) | −0.61% | **−16.88%** |
| Sector rotation (top-2 SPDR ETFs, monthly rebalance) | −13.61% | (skipped — train alone was enough) |

**What I learned:** every framework underperformed SPY on training data,
even after disciplined parameter exploration. When candidates that looked
best on train were one-shot validated on holdout, the apparent edge
collapsed (this is the curve-fitting signature in practice). The
methodology worked exactly as designed — to prevent me from acting on
noise with real money.

---

## Architecture

```
    ┌─────────────────────────────────────────────────────────────┐
    │  Python pre-screener (no LLM)                               │
    │  scans 39 tickers/cycle for pullback-to-rising-20d-MA setup │
    └────────────────────────────┬────────────────────────────────┘
                                 │
                       candidate symbols + indicators
                                 │
                                 ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │  3-stage LLM agent loop (Ollama or Gemini, per cycle):             │
   │                                                                    │
   │    Position Manager  → reviews open positions, decides hold/close  │
   │    Scout            → picks single best long setup, or passes      │
   │    Risk Manager     → iterates to a sized, bracketed order until   │
   │                       all 10 risk checks pass                      │
   └────────────────────────────┬───────────────────────────────────────┘
                                 │
                       proposed trade w/ stop & target
                                 │
                                 ▼
                       ┌────────────────────┐
                       │  risk_layer.py     │   ← HARD LIMITS in Python
                       │  (10 checks)       │     LLM cannot bypass
                       └─────────┬──────────┘
                                 │
                                 ▼
                       ┌────────────────────┐
                       │   broker.py        │   ← submits protected order
                       │   (Alpaca API)     │     (bracket or trailing stop,
                       └────────────────────┘      held server-side at broker)
```

**The 10 risk checks** (`risk_layer.py`):
approved-symbol whitelist, long-only enforcement (no shorts), per-position
dollar cap, daily-loss circuit breaker, max open positions, max share count,
sector concentration cap (no more than 3 positions in one sector), market-
hours check, exit-protection sanity (bracket mode: stop 3–15% and R:R ≥ 1.5;
trailing mode: trail % within 3–15%), sufficient buying power.

**The 11 LLM tools** (`tools.py`): account / positions / quotes / bars /
news / recent-proposals / market-regime detection / ATR-based volatility-
sized position sizing + the 3 action tools (`select_candidate`,
`propose_trade`, `write_journal`).

---

## Why the LLM pipeline is split into three stages

Early versions of this project used one big LLM agent for everything. Small
models (4–14B class) handle long multi-purpose prompts poorly — they
hallucinate, drift, and produce confident-sounding nonsense. Splitting the
work into three narrowly-scoped agents (each with its own focused prompt
and restricted tool set) made the system dramatically more reliable.

Each stage runs in sequence per cycle. The Scout cannot execute trades; the
Risk Manager cannot select symbols. Tool restrictions are enforced in code,
not just in the prompt.

---

## Keeping an unattended bot alive (harder than the trading)

The most instructive engineering in this project wasn't the strategy — it
was making a long-running process survive real-world conditions, first on a
consumer MacBook and eventually on a VPS. Each layer below exists because
something actually failed without it:

1. **Broker-side exits, always.** Every position's stop lives at Alpaca,
   not in the bot. A dead bot, a sleeping Mac, or a crashed LLM provider
   never leaves a position unprotected. This is the load-bearing safety
   decision; everything else is convenience.

2. **macOS TCC vs. background agents.** A launchd background agent cannot
   read `~/Documents`, so the bot can't run as a proper daemon from its
   project folder. It runs as a Login Item in a visible Terminal window
   instead, and writes its heartbeat to TWO places — `logs/heartbeat.txt`
   (for the dashboard) and `~/.trading_bot_heartbeat` (TCC-free, for
   watchdogs).

3. **Sleep kills TCP connections, and hidden no-timeout calls hang forever.**
   The Mac sleeping mid-cycle leaves dead sockets behind. The first fix
   (`socket.setdefaulttimeout`) turned out to be a no-op for `requests`/
   urllib3 — alpaca-py issues session requests with NO timeout. Real fixes:
   force (30s, 30s) timeouts onto both Alpaca clients' sessions, plus a
   SIGALRM watchdog that hard-aborts any cycle exceeding 300s.

4. **The watchdog gap you only find in production.** After the SIGALRM fix,
   the bot still hung twice — both times pre-market. Root cause: the
   market-open check ran *before* the alarm was armed, so a dead-connection
   hang in that one call was unprotected. Interim mitigation: an external
   launchd watchdog (`setup_auto_restart.sh`) that killed and relaunched
   the bot if the heartbeat went >90 min stale during market hours. The
   one-line root-cause fix (arm the alarm around the market-open check too)
   landed with the VPS migration, where it matters more — `systemd`
   restarts crashes, not hangs.

5. **The failure mode that ended laptop hosting.** A Login Item relaunched
   the bot at login and `pmset` scheduled the Mac to wake before market
   open on weekdays. It worked — as long as the laptop was plugged in.
   The `pmset -g log` diagnosis for the recurring "hangs": on battery,
   macOS downgrades scheduled wakes to 45-second **DarkWakes** — background
   maintenance blips that never reach full wake. An unplugged, closed
   MacBook gave the bot a few seconds of CPU per hour: enough to stamp a
   heartbeat and look alive, not enough to trade. The process wasn't hung;
   the computer was asleep, and no `caffeinate` flag can override
   lid-closed-on-battery sleep — that's OS policy, not a bug. The external
   watchdog dutifully "fixed" it after every lid-open, which is how a real
   suspend-failure masqueraded as a recurring software hang. After the
   fourth missed market open in two weeks, the answer was architectural,
   not another watchdog.

6. **The actual fix: stop hosting a 24/7 process on a machine that sleeps.**
   The bot now runs on a $4/month DigitalOcean droplet as a `systemd`
   service — boot-time start plus `Restart=always` replaced the entire
   launchd watchdog stack (three shell scripts and two launch agents became
   a 15-line unit file). Verified the honest way: reboot the server, watch
   the bot come back and run a cycle unassisted. One wrinkle worth
   recording: campus WiFi silently blocks outbound port 22, so the first
   deploy bootstrapped through the provider's browser console to put SSH on
   port 443 — the HTTPS port no network blocks. `deploy/deploy.sh`
   re-deploys any code change in one command.

**A bug worth confessing:** for the project's first weeks, `broker.get_bars`
passed `limit` to Alpaca, which truncates from the *oldest* end of the
window — so every history call silently dropped the most recent ~2 weeks of
bars. The LLM stages and screener were reading two-week-stale charts while
quotes were live. Nothing crashed; the bot happily traded on it. Found only
by noticing backtest windows ended earlier than labeled. Lesson: data
pipelines fail silently, and "it runs without errors" says nothing about
whether the inputs are right.

---

## Setup

### 1. Alpaca paper account

Sign up at https://alpaca.markets, generate **paper** API keys.

### 2. LLM backend (pick one)

**Local Ollama** (free, slower, runs on 8GB+ RAM):
```bash
brew install ollama
ollama serve &
ollama pull qwen3:4b
```

**Gemini cloud** (small daily cost, much faster):
- Get an API key from Google AI Studio
- Free tier caps at 20 requests/day/project — one good cycle can exhaust
  this. Paid tier is recommended (pennies/day at this volume).

### 3. Python deps

```bash
cd trading_agent_swing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER=true,
#           MODEL_PROVIDER=ollama|gemini, GEMINI_API_KEY (if applicable)
```

### 4. Run

```bash
python main.py            # one cycle
python main.py loop       # loop every 1 hour during market hours (default swing cadence)
python main.py loop 900   # loop every 15 min
python main.py panic      # emergency: flatten everything
streamlit run dashboard.py   # dashboard at http://localhost:8501
```

### 5. Run autonomously (optional)

**VPS (how it actually runs now)** — any $4–6/month Ubuntu 24.04 box:

```bash
./deploy/deploy.sh <server-ip>   # from repo root: syncs code + .env,
                                 # builds venv, installs systemd service
```

The service starts on boot and auto-restarts on crash. Check on it with
`journalctl -u trading-bot -n 50`.

**Laptop (the original way, kept for reference)**:

```bash
./setup_autostart.sh        # adds bot to Login Items, opens it now
./setup_market_wake.sh      # schedules Mac to wake at 9:15 AM ET weekdays
```

Caveat that eventually ended this era: scheduled wakes only fully wake a
MacBook on AC power (see reliability section #5). A heartbeat file at
`logs/heartbeat.txt` is touched every loop iteration so you can verify the
bot isn't silently hung — or silently suspended.

---

## File map

| file                   | purpose                                                            |
|------------------------|--------------------------------------------------------------------|
| `config.py`            | Knobs: risk limits, symbol whitelist, model provider               |
| `broker.py`            | Alpaca wrapper. Same code paper or live. Supports day & week bars  |
| `risk_layer.py`        | **Most important file.** 10 hard checks the LLM cannot bypass      |
| `test_risk_layer.py`   | Tests proving every risk check rejects what it must (`pytest`)     |
| `test_resilience.py`   | Tests for the anti-hang machinery (timeouts, cycle watchdog)       |
| `screener.py`          | Pure-Python pre-screener — no LLM                                  |
| `tools.py`             | 11 tool definitions exposed to the LLM via function calling        |
| `agent.py`             | 3-stage agent loop: Position Manager → Scout → Risk Manager        |
| `gemini_client.py`     | Drop-in stand-in for `ollama.Client` (60s request timeout)         |
| `main.py`              | Entry point — once / loop / panic. Heartbeat + timestamped errors  |
| `review.py`            | Manual approve/reject for queued proposals (when AUTO_EXECUTE off) |
| `dashboard.py`         | Streamlit dashboard — equity, positions, SPY benchmark, journal    |
| `backtest.py`          | Single-window mechanical backtest of the pullback rule             |
| `walkforward.py`       | Walk-forward backtester for the daily pullback + breakout framework |
| `walkforward_weekly.py`| Walk-forward backtester for the weekly Donchian framework          |
| `walkforward_rotation.py` | Walk-forward backtester for the sector rotation framework       |
| `forward_test.py`      | One-command scoreboard: account vs SPY alpha since the 2026-06-11 forward-test baseline |
| `deploy/deploy.sh`     | One-command VPS deploy: server setup, code sync, venv, systemd unit (repo root) |
| `deploy/trading-bot.service` | systemd unit — start on boot, auto-restart on crash (repo root) |
| `start_bot.command`    | Launcher for the Login Item autostart (repo root, Mac era)         |
| `setup_autostart.sh`   | Installs the Login Item (repo root, Mac era)                       |
| `setup_market_wake.sh` | Schedules Mac to wake before market open weekdays (repo root, Mac era) |
| `setup_health_alert.sh` | Notify-only watchdog: macOS alert if heartbeat goes stale (repo root, Mac era) |
| `setup_auto_restart.sh` | Auto-restart watchdog: kills + relaunches a hung bot (repo root, Mac era) |

Logs land in `./logs/`:
- `agent.jsonl` — every model message and tool call
- `proposals.jsonl` — every trade proposal (approved or rejected)
- `picks.jsonl` — Scout's symbol selections each cycle
- `journal.jsonl` — Position Manager's per-cycle review
- `daily_pnl.json` — snapshot of starting equity for daily-loss check
- `heartbeat.txt` — touched every loop iteration; check freshness to verify
  the bot isn't silently hung

---

## The research story

The bot is the operational system. The walk-forward backtesters are the
research system. The two are decoupled by design: I could iterate on the
strategy without touching the bot, and vice versa.

### Methodology

For each candidate strategy framework, I split the available historical
data into:
- **Train windows** — used to develop hypotheses, explore parameters,
  diagnose failure modes
- **Holdout windows** — touched ONCE per candidate parameter set, for
  final out-of-sample validation

The rule: if a hypothesis improves results on train, validate it on
holdout. If holdout confirms, the apparent edge may be real. If holdout
collapses, the train improvement was curve-fitting to those specific
windows. Repeatedly peeking at holdout to "find what works" defeats the
purpose — that's just curve-fitting with extra steps.

Metrics tracked per window:
- **Alpha vs SPY buy-and-hold** — the only return metric that matters,
  because SPY is the alternative
- **Annualized Sharpe ratio** — return per unit of volatility
- **Max drawdown** — the psychological pain test (would I actually hold
  through this in real life?)
- **Profit factor** — sum of winning trades $ / sum of losing trades $

### Three frameworks tested

**1. Daily pullback to MA + breakout entries** (`walkforward.py`)

The original strategy the bot was designed around. Buy on pullback to a
rising 20-day MA in confirmed uptrend, with 6% stop and 12% target.
Tested variations:
- Baseline pullback only
- "Let winners run" exit params (target 25%, hold 60d)
- Trending-regime breakout entries (new 20-day high when SPY > 200d MA)
- Combination ("both" entry mode)

Best train candidate (combined entries): −6.78% avg alpha.
Holdout validation: −1.88% avg alpha. Improvement vs baseline was real
but tiny (+0.62%) — most of the train gains evaporated. Strategy is
defensive: wins by losing less in down years, misses the upside in rallies.

**2. Weekly Donchian trend-following** (`walkforward_weekly.py`)

Classic Turtle Trading: buy new N-week-high closes, exit on new M-week-low
closes or ATR stop. Long-only with optional SPY > 40-week MA regime gate.

Sensitivity analysis showed monotonic improvement as the Donchian period
slowed (faster 12/6 → default 20/10 → slower 26/13). Best train: −0.61%
alpha, Sharpe 0.92 — nearly matched SPY on train.

Holdout validation of slower 26/13: **−16.88% avg alpha**. Both holdout
windows were sustained rally years — the 26-week confirmation lag that
worked beautifully on the 2022–2023 AI rally happened to misalign with
the post-AI continuation. Catastrophic out-of-sample collapse. Textbook
curve-fitting.

**3. Sector rotation** (`walkforward_rotation.py`)

Dual-momentum: rank 11 SPDR sector ETFs by trailing 6-month return,
hold the top 2 equal-weighted, monthly rebalance. Regime-gated.

Train baseline: **−13.61% avg alpha**, 0/3 windows positive — worse than
either prior framework's baseline. Top-2 selection misses broad rallies
where 9+ sectors are up, and got the rotation wrong in 2021 (lost outright
in a +14.8% SPY year). Skipped holdout validation — train alone was
sufficient to inform the verdict.

**4. Trailing-stop exits — forward test in progress** (`--exit trailing`)

A fourth, pre-registered experiment (June 2026): replace bracket exits with a
−7% hard stop + 10% trailing stop and **no profit target** — cut losers, let
winners run. On the train windows this was the largest single-variable
improvement found (avg alpha −10.7% → −2.0% for the deployed pure-trail
config, Sharpe +1.0), driven by the COVID-crash window flipping to +8.8%
alpha. But the holdout windows were already spent, so no honest backtest
validation exists. Instead, the live paper bot now runs this exit style
(server-side trailing stops at Alpaca, `EXIT_STYLE=trailing`) as a true
out-of-sample forward test, measured as alpha vs SPY from 2026-06-11.
Until that forward record exists, the train improvement should be assumed
to be at least partly curve-fit.

### What the results add up to

Three structurally different frameworks. Disciplined train/holdout
methodology. Consistent finding: **no demonstrable out-of-sample edge over
SPY buy-and-hold.** This is the expected result from rigorous quant
research — most strategy ideas don't work, and proper validation reveals
which apparent edges are real vs noise. Professional quant teams find
exactly this on most ideas.

The infrastructure works. The methodology is sound. The strategies tested
just don't have edge in this market regime, on this data, with what a
retail trader (or a 4–14B LLM) can plausibly design.

---

## What I'd do differently if I were starting over

- Build the walk-forward framework BEFORE building the live bot. I built
  the bot first and tuned it against intuition. The rigorous backtester
  later showed the strategy was a SPY underperformer. Building the
  rigor-first version of this would have saved real time.
- Treat the LLM as the wrapper around a rules-based engine, not the
  brain. In practice the screener and risk layer do the strategy work;
  the LLM is mostly cosmetic (it rubber-stamps the screener's pick).
- Don't pick a strategy because it sounds plausible. Test the simplest
  mechanical version of it first. If even the clean rule loses to SPY,
  no amount of LLM polish saves it.

---

## Going to live trading — read this if you're tempted

I'm not going to. The data is the data: the strategies I've tested don't
beat SPY, and the most honest use of money I might otherwise deploy here
is a low-cost index fund.

The rest of this section is preserved from the original README in case
anyone considering live deployment is reading. The bar should be very high.

### Before flipping the switch

1. **Run paper for at least 3 months** across different market regimes.
   Two days of paper trading tells you nothing.

2. **Measure honestly** against SPY buy-and-hold over the same window.
   If you don't beat SPY, you have no edge. The bot is a losing
   proposition regardless of how good the trades "look."

3. **Validate out-of-sample.** Backtests that look good on the window
   you tuned them on don't predict live performance. Use train/holdout
   discipline. Run `walkforward.py --windows holdout` once per
   candidate.

4. **Audit the proposals.** Read 50 random proposals from
   `proposals.jsonl`. Did the stated reason match what actually
   happened? If the model hallucinated patterns, you have a problem
   the risk layer can't fix.

### When you switch

Edit `.env`:
```
ALPACA_API_KEY=<live key>
ALPACA_SECRET_KEY=<live secret>
ALPACA_PAPER=false
```

Tighten everything in `config.py` for the first month. Fund with the
smallest amount that makes the project feel real ($500–$1000). Not
savings. Not rent.

### Pattern Day Trader rule

If your live account is under $25,000 and you make 4 or more day trades
in 5 business days, your broker will lock you out for 90 days. Plan
holding periods accordingly, or fund above $25k. Swing-trade timeframes
should avoid this, but be aware.

### Slippage and the paper-to-live gap

Paper trading often fills at midpoint. Real fills are worse. If your
paper edge is thin, slippage will eat it.

### Tax notes (US)

- Short-term capital gains taxed as ordinary income
- Wash-sale rules apply if you re-enter at a loss within 30 days
- Talk to a CPA. I'm not one.

### The kill switch

`python main.py panic` flattens all positions and cancels all orders.
Know that command before you go live.

---

## Honest assessment

A 4-billion-parameter local LLM (or Gemini Flash) is not going to be a
great trader. Function calling is unreliable, market intuition is
nonexistent, and the model will produce confident-sounding analysis
that's often just plausible text. The risk layer prevents catastrophic
mistakes. It cannot manufacture an edge that isn't there.

I tested three structurally different strategy frameworks with
disciplined out-of-sample validation. None had edge. That's a real,
informative, valuable result — not a failure of the project. It's the
project working correctly.

This codebase is a learning artifact first. The infrastructure (autonomous
agent, risk layer, dashboard, monitoring, walk-forward backtester) is the
durable output. The strategy results are the honest finding. Both are
the point.

If you're considering building something like this: do the rigor first.
Most retail strategy ideas do not have edge. Find out cheaply, before
real money is involved.
