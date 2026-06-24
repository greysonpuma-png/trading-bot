#!/bin/bash
# ===================================================================
#  TRADING BOT — health alert installer
#
#  Installs a background watchdog (launchd agent) that checks the
#  bot's heartbeat every 30 minutes. If the heartbeat is more than
#  2 hours stale during market hours (Mon-Fri, ~7:45 AM - 2:00 PM
#  Mountain), it pops a macOS notification so a hung bot gets
#  noticed in hours, not days.
#
#  The watchdog reads ~/.trading_bot_heartbeat (NOT the copy in
#  Documents/) because macOS blocks background agents from reading
#  ~/Documents. The bot writes both copies on every loop iteration.
#
#  Run:      ./setup_health_alert.sh
#  Remove:   ./stop_health_alert.sh
# ===================================================================
set -e

CHECK_SCRIPT="$HOME/.local/bin/trading-bot-healthcheck.sh"
PLIST="$HOME/Library/LaunchAgents/com.greysonrice.tradingbot.healthcheck.plist"
LABEL="com.greysonrice.tradingbot.healthcheck"

mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents"

# ── 1. The check script ────────────────────────────────────────────
cat > "$CHECK_SCRIPT" <<'EOF'
#!/bin/bash
# Trading bot heartbeat watchdog — installed by setup_health_alert.sh
HB="$HOME/.trading_bot_heartbeat"
MAX_AGE_SECS=7200   # alert when heartbeat > 2 hours stale

# Only check Mon-Fri during (rough) market hours, 7:45 AM - 2:00 PM Mountain.
dow=$(date +%u)
[ "$dow" -gt 5 ] && exit 0
hm=$((10#$(date +%H) * 60 + 10#$(date +%M)))
[ "$hm" -lt 465 ] && exit 0   # before 7:45 AM
[ "$hm" -gt 840 ] && exit 0   # after  2:00 PM

if [ -f "$HB" ]; then
  age=$(( $(date +%s) - $(stat -f %m "$HB") ))
else
  age=$((MAX_AGE_SECS + 1))   # no heartbeat file at all -> treat as stale
fi

if [ "$age" -gt "$MAX_AGE_SECS" ]; then
  mins=$((age / 60))
  osascript -e "display notification \"Heartbeat ${mins} min stale — the bot may be hung or stopped. Check the bot's Terminal window.\" with title \"⚠️ Trading Bot Health\" sound name \"Basso\""
fi
EOF
chmod +x "$CHECK_SCRIPT"

# ── 2. The launchd agent (runs the check every 30 minutes) ─────────
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$CHECK_SCRIPT</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# ── 3. (Re)load it ─────────────────────────────────────────────────
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "SUCCESS: health watchdog installed."
echo "  checks every 30 min, alerts if heartbeat > 2h stale during market hours"
echo "  remove anytime with ./stop_health_alert.sh"
