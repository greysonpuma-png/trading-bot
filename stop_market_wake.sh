#!/bin/bash
# ===================================================================
#  Trading Bot - Turn OFF the Market-Open Auto-Wake
#
#  Removes the scheduled weekday wake. Your Mac will no longer wake
#  itself on a schedule.
#
#  To turn it back on:
#    bash ~/Documents/trading-bot/setup_market_wake.sh
# ===================================================================

echo "Turning OFF the market-open auto-wake schedule..."
echo ""
echo "Your Mac will ask for your password to change the power schedule."
echo "Type it directly into Terminal - it is not saved anywhere."
echo ""

sudo pmset repeat cancel

echo ""
echo "Scheduled power events now on your Mac:"
pmset -g sched

echo ""
echo "DONE - your Mac will no longer wake itself on a schedule."
echo ""
echo "Turn auto-wake back on with:"
echo "  bash ~/Documents/trading-bot/setup_market_wake.sh"
