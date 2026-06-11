# Trading Bot

Autonomous LLM-driven swing trading agent (paper trading) with a hard-coded
risk layer, walk-forward backtesting framework, and honest negative results.

**→ Full project documentation: [trading_agent_swing/README.md](trading_agent_swing/README.md)**

## Layout

| path | purpose |
|---|---|
| `trading_agent_swing/` | The project: agents, risk layer, backtesters, dashboard, tests |
| `start_bot.command` | Launcher — opens the bot in a Terminal window (used by Login Item) |
| `setup_autostart.sh` / `stop_autostart.sh` | Install/remove auto-start at login |
| `setup_market_wake.sh` / `stop_market_wake.sh` | Schedule/cancel Mac auto-wake before market open |
| `COMMANDS.md` | Beginner-friendly command cheat sheet |
