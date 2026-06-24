#!/bin/bash
# ===================================================================
#  Trading Bot - Auto-Wake the Mac for Market Open
#
#  Schedules your Mac to wake itself ~15 minutes before the US stock
#  market opens, every weekday (Mon-Fri), so the bot is always live
#  for the open.
#
#  Run this ONCE. It will ask for your Mac password (needed to change
#  the system power schedule) - type it yourself; it is not stored.
#
#  Turn it off later with:
#    bash ~/Documents/trading-bot/stop_market_wake.sh
# ===================================================================

echo "Setting up auto-wake before market open..."
echo ""

# --- Work out the local time that matches 9:15am US-Eastern --------
# (The market opens 9:30am Eastern; we wake the Mac 15 minutes early.)
WAKE_TIME="$(/usr/bin/python3 - <<'PYEOF'
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
    et_open = datetime.now(ZoneInfo("America/New_York")).replace(
        hour=9, minute=30, second=0, microsecond=0)
    wake = (et_open - timedelta(minutes=15)).astimezone()
    print(wake.strftime("%H:%M:%S"))
except Exception:
    print("")
PYEOF
)"

if [ -z "$WAKE_TIME" ]; then
  echo "ERROR: couldn't work out the wake time automatically."
  echo "Nothing was changed."
  exit 1
fi

echo "The US stock market opens at 9:30am Eastern time."
echo "Translated into your Mac's own local time, your Mac will wake at:"
echo ""
echo "    $WAKE_TIME   every weekday (Mon-Fri)"
echo ""
echo "Your Mac will now ask for your password to set the power schedule."
echo "Type it directly into Terminal - it is not saved anywhere."
echo ""

# --- Apply the repeating wake schedule -----------------------------
sudo pmset repeat wakeorpoweron MTWRF "$WAKE_TIME"

echo ""
echo "Scheduled power events now on your Mac:"
pmset -g sched

echo ""
echo "DONE - auto-wake is set."
echo "  - Your Mac will wake every weekday at $WAKE_TIME (local time)."
echo "  - Combined with auto-start, the bot will be live for the open."
echo ""
echo "Important: keep the Mac LOGGED IN and let it sleep normally"
echo "(lid open, plugged in). Don't fully shut it down - a wake-from-"
echo "shutdown stops at the login screen, and the bot only runs once"
echo "you're logged in."
echo ""
echo "Turn auto-wake OFF later with:"
echo "  bash ~/Documents/trading-bot/stop_market_wake.sh"
