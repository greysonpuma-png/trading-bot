# Trading Bot

Autonomous LLM-driven swing trading agent (paper trading) with a hard-coded
risk layer, walk-forward backtesting framework, and honest negative results.

**→ Full project documentation: [trading_agent_swing/README.md](trading_agent_swing/README.md)**

**Status (July 2026):** a pre-registered forward test of trailing-stop exits
is running live on the paper account — first read ~Sept 3, 2026, scored as
alpha vs SPY (`python forward_test.py`). Operating rules in
[HANDOFF.md](HANDOFF.md).

## Layout

| path | purpose |
|---|---|
| `trading_agent_swing/` | The project: agents, risk layer, backtesters, dashboard, tests |
| `start_bot.command` | Launcher — opens the bot in a Terminal window (used by Login Item) |
| `setup_autostart.sh` / `stop_autostart.sh` | Install/remove auto-start at login |
| `setup_market_wake.sh` / `stop_market_wake.sh` | Schedule/cancel Mac auto-wake before market open |
| `setup_health_alert.sh` / `stop_health_alert.sh` | Install/remove a watchdog that notifies if the bot's heartbeat goes stale during market hours |
| `setup_auto_restart.sh` / `stop_auto_restart.sh` | Install/remove a watchdog that kills + relaunches a hung bot automatically |
| `HANDOFF.md` | Operating manual + the pre-registered forward-test decision rule |
| `COMMANDS.md` | Beginner-friendly command cheat sheet |
