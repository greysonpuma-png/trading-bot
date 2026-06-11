#!/bin/bash
# ===================================================================
#  SWING TRADING BOT - launcher
#
#  This file opens automatically at login (once auto-start is set up),
#  and you can also double-click it any time to start the bot.
#
#  The window this opens IS the bot. Leave it open.
#  Press Ctrl+C in the window to stop the bot.
# ===================================================================

echo "===================================================="
echo "   SWING TRADING BOT"
echo "   This window IS the bot. Leave it open."
echo "   Press Ctrl+C here to stop the bot."
echo "===================================================="
echo ""

cd "$HOME/Documents/trading-bot/trading_agent_swing" || {
  echo "ERROR: could not find the bot folder. Stopping."
  echo "(Press any key to close this window.)"
  read -n 1
  exit 1
}

source .venv/bin/activate
exec caffeinate -i python main.py loop
