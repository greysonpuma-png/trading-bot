# Trading Bot — Command Cheat Sheet

Your bot lives in: `~/Documents/trading-bot/trading_agent_swing/`

---

## The one rule to remember

Every command runs in the **Terminal app** (open a new window with **Cmd+N**).

Most commands begin with this "activate" chunk, which moves into the project
folder and switches on the Python environment:

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate
```

After that runs, your prompt shows `(.venv)` at the start. **If you see
`(.venv)`, you can run the short commands. If you don't, always use the full
command (with the `cd ... && source ...` chunk in front).**

---

## Everyday commands

### ▶ Start the bot (continuous)

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && caffeinate -i python main.py loop
```

Runs the bot on a loop — it cycles during market hours and sleeps nights and
weekends, automatically. **Start this ONCE and leave the window open. You do
NOT need to restart it each day** — it keeps itself running across days.

The `caffeinate -i` part keeps your Mac from falling asleep while the bot runs
(a sleeping Mac pauses the bot). Keep the laptop lid open and plugged in —
closing the lid still sleeps the Mac even with `caffeinate`.

**This is the key to getting trades:** the bot can only find and place trades
while it's actually running during market hours (weekdays, 9:30am–4pm ET). If
it's off, or the Mac slept, it misses setups. Start it once and keep it alive.

### ▶ Run one cycle right now

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python main.py once
```

Runs a single cycle, then stops. Good for testing.

### ▶ Open the dashboard (the website)

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && streamlit run dashboard.py
```

Opens the monitoring website at **http://localhost:8501**. Leave this window
open too. Refresh the browser tab for fresh data.

### ▶ EMERGENCY — sell everything

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python main.py panic
```

Immediately closes all positions and cancels all orders. It will ask you to
type `YES` to confirm. This is your kill-switch — remember it.

### ▶ Stop a running command

Press **Ctrl+C** (the Control key + C) inside the window. This stops the loop,
the dashboard, a log viewer — anything. Your universal "stop this" key.

---

## Auto-start — the bot opens itself at login

With auto-start on, the bot opens in its own Terminal window every time you log
in to your Mac. You don't type anything — the window appears and the bot starts
running. (It uses a "login item," which runs the bot the same way you would by
hand — that's why it works reliably.)

### Turn auto-start ON (run once)

```
bash ~/Documents/trading-bot/setup_autostart.sh
```

macOS may pop up "Terminal wants to control System Events" — click OK. After
that, the bot opens automatically at every login. **The window that opens IS
the bot — leave it open.** Closing it stops the bot.

### Turn auto-start OFF

```
bash ~/Documents/trading-bot/stop_autostart.sh
```

Stops the bot from opening itself at login. It does **not** close a window
that's already running — for that, click the window and press Ctrl+C.

### Good to know

- The bot opens in a normal Terminal window. You can minimize it; just don't
  close it.
- It still pauses when the Mac is **asleep, off, or the lid is closed** —
  auto-start removes the "type the command" step, it can't run a sleeping Mac.
- `python main.py panic` (emergency sell-all) still works exactly the same.
- After editing `.env`, stop the bot (Ctrl+C in its window), then start it
  again — double-click `start_bot.command`, or just log out and back in.

---

## Auto-wake — the Mac wakes itself for the open

Auto-start launches the bot when you log in. Auto-wake goes one step further:
it tells the Mac to wake itself up ~15 minutes before the market opens each
weekday, so the bot is always live for the open without you touching anything.

### Turn auto-wake ON (run once)

```
bash ~/Documents/trading-bot/setup_market_wake.sh
```

It asks for your Mac password (needed to set the system power schedule) — type
it yourself; it isn't stored. It figures out the right local time for you
automatically (the market opens 9:30am Eastern).

### Turn auto-wake OFF

```
bash ~/Documents/trading-bot/stop_market_wake.sh
```

### Good to know

- This handles the **asleep** case: leave the Mac logged in, lid open, plugged
  in, and let it sleep normally — it'll wake itself each weekday morning.
- It does **not** fully handle a **shut-down** Mac: a powered-off Mac will turn
  on, but it stops at the login screen, and the bot only runs once you're
  logged in. So don't shut the Mac down — just let it sleep.

---

## Less common

### Review pending trades by hand

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python review.py
```

Only matters if `AUTO_EXECUTE` is off. Type `y` to approve a trade, `n` to skip,
`q` to quit. (Right now AUTO_EXECUTE is on, so trades execute themselves and
this will usually say "no pending proposals.")

### Run a backtest

```
cd ~/Documents/trading-bot/trading_agent_swing && source .venv/bin/activate && python backtest.py
```

Tests the strategy against historical data and prints how it would have done.

### Change settings

```
cd ~/Documents/trading-bot/trading_agent_swing && open -e .env
```

Opens the settings file in TextEdit. Things you can change here:
- `MODEL_PROVIDER` — `gemini` (cloud, fast) or `ollama` (local, free)
- `AUTO_EXECUTE` — `true` (bot trades itself) or `false` (review queue)
- `ALPACA_PAPER` — keep this `true` (fake money). Do NOT set it to false.

Save with **Cmd+S**, then restart the bot for changes to take effect.

### See what the bot has done (raw logs)

```
cat ~/Documents/trading-bot/trading_agent_swing/logs/proposals.jsonl
```
Shows every trade proposal the bot has made.

```
tail -f ~/Documents/trading-bot/trading_agent_swing/logs/agent.jsonl
```
Watch the bot think in real time. Press Ctrl+C to stop watching (this does NOT
stop the bot — just the viewer).

---

## Rules of thumb

- **Leave windows open.** The bot's loop window and the dashboard window must
  stay open — closing a window stops whatever was running in it.
- **Keep the Mac awake and plugged in.** If the Mac sleeps, the bot pauses.
- **Ctrl+C** stops whatever is running in the current window.
- **Don't type into the bot's loop window.** It doesn't read what you type.
  Use a separate new window (Cmd+N) for other commands.
- After changing `.env`, **restart the bot** so it re-reads the settings.

---

## Quick reference

| What you want | Command (add the activate chunk if no `(.venv)`) |
|---|---|
| Start the bot | `caffeinate -i python main.py loop` |
| Run one cycle | `python main.py once` |
| Open the dashboard | `streamlit run dashboard.py` |
| EMERGENCY: sell all | `python main.py panic` |
| Review trades by hand | `python review.py` |
| Run a backtest | `python backtest.py` |
| Edit settings | `open -e .env` |
| Turn ON auto-start | `bash ~/Documents/trading-bot/setup_autostart.sh` |
| Turn OFF auto-start | `bash ~/Documents/trading-bot/stop_autostart.sh` |
| Turn ON auto-wake | `bash ~/Documents/trading-bot/setup_market_wake.sh` |
| Turn OFF auto-wake | `bash ~/Documents/trading-bot/stop_market_wake.sh` |
| Stop anything running | `Ctrl+C` |
