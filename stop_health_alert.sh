#!/bin/bash
# Removes the trading bot health watchdog installed by setup_health_alert.sh
PLIST="$HOME/Library/LaunchAgents/com.greysonrice.tradingbot.healthcheck.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST" "$HOME/.local/bin/trading-bot-healthcheck.sh"
echo "Health watchdog removed."
