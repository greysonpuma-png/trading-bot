#!/bin/bash
# ===================================================================
#  Trading Bot - Auto-Start Setup  (Terminal-window method)
#
#  Sets the bot to open in a Terminal window every time you log in.
#  This is the reliable method: the bot runs the same way you'd run
#  it by hand, so macOS file permissions are never a problem.
#
#  Run this ONCE.
#
#  Turn it off later with:
#    bash ~/Documents/trading-bot/stop_autostart.sh
# ===================================================================

LABEL="com.greyson.swingbot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CMD_FILE="$HOME/Documents/trading-bot/start_bot.command"
PROJECT="$HOME/Documents/trading-bot/trading_agent_swing"

echo "Setting up auto-start (Terminal-window method)..."
echo ""

# --- Safety checks -------------------------------------------------
if [ ! -d "$PROJECT" ]; then
  echo "ERROR: can't find the bot folder:"
  echo "  $PROJECT"
  echo "Nothing was changed."
  exit 1
fi
if [ ! -f "$CMD_FILE" ]; then
  echo "ERROR: can't find the bot launcher file:"
  echo "  $CMD_FILE"
  echo "Nothing was changed."
  exit 1
fi

# --- 1. Clear out the old background auto-start (macOS blocked it) --
echo "Clearing out the old background auto-start..."
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl unload "$PLIST" 2>/dev/null
[ -f "$PLIST" ] && mv "$PLIST" "$PLIST.disabled"
echo "  done."
echo ""

# --- 2. Make the launcher runnable ---------------------------------
chmod +x "$CMD_FILE"

# --- 3. Register the launcher as a login item ----------------------
echo "Setting the bot to open at login..."
echo "macOS may pop up: 'Terminal wants to control System Events' -"
echo "click OK / Allow so this can finish."
echo ""

osascript -e 'tell application "System Events" to delete (every login item whose name is "start_bot.command")' 2>/dev/null
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$CMD_FILE\", hidden:false}" >/dev/null 2>&1

# --- 4. Confirm ----------------------------------------------------
if osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q "start_bot.command"; then
  echo "SUCCESS - auto-start is set."
  echo ""
  echo "  - The bot will open in a Terminal window every time you log in."
  echo "  - That window IS the bot - leave it open."
else
  echo "Couldn't confirm the login item automatically."
  echo "Add it by hand: System Settings > General > Login Items,"
  echo "then under 'Open at Login' click '+' and choose this file:"
  echo "  $CMD_FILE"
fi
echo ""

# --- 5. Start it now too (unless already running) ------------------
if pgrep -f "main.py loop" >/dev/null 2>&1; then
  echo "A bot loop already appears to be running - not starting another."
  echo "It will also open on its own at your next login."
else
  echo "Starting the bot now in a new window..."
  open "$CMD_FILE"
  sleep 1
  echo "A new Terminal window should have opened - that one is the bot."
  echo "(Markets are closed right now, so it will say 'market closed,"
  echo " sleeping' until they open - that is normal and correct.)"
fi
echo ""
echo "Turn auto-start OFF later with:"
echo "  bash ~/Documents/trading-bot/stop_autostart.sh"
