#!/bin/bash
# ===================================================================
#  TRADING BOT — auto-restart watchdog installer
#
#  Installs a background watchdog (launchd agent) that checks the
#  bot's heartbeat every 10 minutes during market hours (Mon-Fri,
#  ~7:45 AM - 2:00 PM Mountain). If the heartbeat is more than
#  90 minutes stale, it KILLS the hung bot and RELAUNCHES it via
#  start_bot.command — the same restart procedure as the handoff
#  doc (§6D), just automated. It also pops a notification so you
#  know a restart happened.
#
#  Why 90 minutes: the bot's loop only writes the heartbeat every
#  ~15-60 min, so a tighter threshold would restart a healthy bot.
#
#  This does NOT touch the bot's code or trading logic in any way.
#  It is pure ops: the same "pkill + open start_bot.command" you'd
#  run by hand.
#
#  The watchdog reads ~/.trading_bot_heartbeat (NOT the copy in
#  Documents/) because macOS blocks background agents from reading
#  ~/Documents. The bot writes both copies on every loop iteration.
#
#  Pause it without uninstalling:  touch ~/.trading_bot_watchdog_off
#  Resume:                         rm ~/.trading_bot_watchdog_off
#  Restart log:                    ~/.trading_bot_watchdog.log
#
#  Run:      ./setup_auto_restart.sh
#  Remove:   ./stop_auto_restart.sh
# ===================================================================
set -e

CHECK_SCRIPT="$HOME/.local/bin/trading-bot-autorestart.sh"
PLIST="$HOME/Library/LaunchAgents/com.greysonrice.tradingbot.autorestart.plist"
LABEL="com.greysonrice.tradingbot.autorestart"

mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents"

# ── 1. The watchdog script ─────────────────────────────────────────
cat > "$CHECK_SCRIPT" <<'EOF'
#!/bin/bash
# Trading bot auto-restart watchdog — installed by setup_auto_restart.sh
HB="$HOME/.trading_bot_heartbeat"
LOG="$HOME/.trading_bot_watchdog.log"
CMD_FILE="$HOME/Documents/trading-bot/start_bot.command"
MAX_AGE_SECS="${TRADING_BOT_WATCHDOG_MAX_AGE:-5400}"   # 90 min default

# Manual off-switch: touch ~/.trading_bot_watchdog_off to pause.
[ -f "$HOME/.trading_bot_watchdog_off" ] && exit 0

# Only act Mon-Fri during (rough) market hours, 7:45 AM - 2:00 PM Mountain.
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

[ "$age" -le "$MAX_AGE_SECS" ] && exit 0   # heartbeat fresh -> all good

# ── Heartbeat is stale: restart the bot (same as handoff doc §6D) ──
mins=$((age / 60))
echo "$(date '+%Y-%m-%d %H:%M:%S')  heartbeat ${mins} min stale -> restarting bot" >> "$LOG"

pkill -f "main.py loop" 2>/dev/null
pkill -f "caffeinate -i python" 2>/dev/null
sleep 3
open "$CMD_FILE"

osascript -e "display notification \"Heartbeat was ${mins} min stale — the bot was hung and has been auto-restarted. See ~/.trading_bot_watchdog.log\" with title \"🔄 Trading Bot Auto-Restart\" sound name \"Basso\"" 2>/dev/null

echo "$(date '+%Y-%m-%d %H:%M:%S')  relaunch issued via start_bot.command" >> "$LOG"
EOF
chmod +x "$CHECK_SCRIPT"

# ── 2. The launchd agent (runs the check every 10 minutes) ─────────
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
    <integer>600</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# ── 3. (Re)load it ─────────────────────────────────────────────────
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "SUCCESS: auto-restart watchdog installed."
echo "  checks every 10 min during market hours"
echo "  restarts the bot if heartbeat > 90 min stale"
echo "  pause anytime:  touch ~/.trading_bot_watchdog_off"
echo "  restart log:    ~/.trading_bot_watchdog.log"
echo "  remove with:    ./stop_auto_restart.sh"
