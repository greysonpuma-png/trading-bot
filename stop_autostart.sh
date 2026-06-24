#!/bin/bash
# ===================================================================
#  Trading Bot - Turn OFF Auto-Start
#
#  Removes the login item so the bot no longer opens by itself.
#  Also clears out the old background auto-start, just in case.
#
#  This does NOT close a bot that is already running. To stop a
#  running bot, click its Terminal window and press Ctrl+C.
#
#  Turn auto-start back on with:
#    bash ~/Documents/trading-bot/setup_autostart.sh
# ===================================================================

LABEL="com.greyson.swingbot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "Turning OFF auto-start..."
echo ""

# Remove the login item
echo "macOS may ask 'Terminal wants to control System Events' - click OK."
osascript -e 'tell application "System Events" to delete (every login item whose name is "start_bot.command")' 2>/dev/null

# Clear the old background auto-start too, if it is still around
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl unload "$PLIST" 2>/dev/null
[ -f "$PLIST" ] && mv "$PLIST" "$PLIST.disabled"

echo ""
if osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q "start_bot.command"; then
  echo "Could not confirm removal. Remove it by hand:"
  echo "  System Settings > General > Login Items, select"
  echo "  start_bot.command, then click the '-' button."
else
  echo "DONE - the bot will no longer open by itself at login."
fi

echo ""
echo "Note: if the bot is running right now, this did NOT stop it."
echo "To stop a running bot, click its window and press Ctrl+C."
echo ""
echo "Turn auto-start back on with:"
echo "  bash ~/Documents/trading-bot/setup_autostart.sh"
