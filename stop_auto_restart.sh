#!/bin/bash
# Removes the trading bot auto-restart watchdog installed by setup_auto_restart.sh
PLIST="$HOME/Library/LaunchAgents/com.greysonrice.tradingbot.autorestart.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST" "$HOME/.local/bin/trading-bot-autorestart.sh"
echo "Auto-restart watchdog removed."
