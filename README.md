# Trading Bot

Autonomous LLM-driven swing trading agent (paper trading) with a hard-coded
risk layer, walk-forward backtesting framework, and honest negative results.

**→ Full project documentation: [trading_agent_swing/README.md](trading_agent_swing/README.md)**

**Status (September 2026):** the pre-registered forward test of trailing-stop
exits **closed on 2026-09-01 and was refuted** — alpha of **+0.01% vs SPY** over
57 trading days, honoring the decision rule written before the test began. That
makes four experiments (three backtested frameworks plus one live forward test),
none of which found edge over buy-and-hold.

The bot now runs a different experiment: [Exp5](EXPERIMENT_MEANREV.md) grades
whether the LLM pipeline faithfully executes a written mandate, scored on
fidelity rather than P&L. Also here: an [evaluation of Robinhood's agentic
trading platform](ROBINHOOD_EVALUATION.md) and a
[scope for a crypto framework](EXPERIMENT_CRYPTO_SCOPE.md).

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
