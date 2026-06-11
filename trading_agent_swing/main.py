"""
Entry point.

Usage:
    python main.py              # one cycle
    python main.py loop         # loop every 15 min during market hours
    python main.py loop 300     # loop every 300 seconds
    python main.py panic        # emergency: flatten all positions
"""
import os
import sys
import time
import traceback
from datetime import datetime

from config import CONFIG
from broker import Broker
from agent import TradingAgent


def _write_heartbeat():
    """Touch the heartbeat files so a stalled loop is visible without scraping logs.

    Two copies: logs/heartbeat.txt for the dashboard, and ~/.trading_bot_heartbeat
    for the launchd health-check agent — background agents can't read ~/Documents
    (macOS TCC), so the watchdog needs a copy outside it.
    """
    stamp = datetime.now().isoformat()
    for path in (os.path.join(CONFIG.log_dir, "heartbeat.txt"),
                 os.path.expanduser("~/.trading_bot_heartbeat")):
        try:
            with open(path, "w") as f:
                f.write(stamp)
        except OSError:
            pass  # heartbeat failure must never crash the loop


def banner():
    mode = "PAPER" if CONFIG.paper else "*** LIVE — REAL MONEY ***"
    print("=" * 60)
    print(f" SWING Trading Agent  |  mode: {mode}")
    if CONFIG.model_provider == "gemini":
        print(f" provider: Gemini (cloud)   model: {CONFIG.gemini_model}")
    else:
        print(f" provider: Ollama (local)   model: {CONFIG.model_name}")
    print(f" auto_execute: {CONFIG.auto_execute_proposals}")
    print(f" max position: ${CONFIG.max_position_size_usd}")
    print(f" max daily loss: ${CONFIG.max_daily_loss_usd}")
    print(f" max open positions: {CONFIG.max_open_positions}")
    print(f" symbol universe: {len(CONFIG.allowed_symbols)} symbols")
    print("=" * 60)


def confirm_live():
    if CONFIG.paper:
        return
    print()
    print("YOU ARE ABOUT TO TRADE WITH REAL MONEY.")
    print(f"max position size: ${CONFIG.max_position_size_usd}")
    print(f"max daily loss:    ${CONFIG.max_daily_loss_usd}")
    print(f"auto execute:      {CONFIG.auto_execute_proposals}")
    if input("type 'I UNDERSTAND' to continue: ").strip() != "I UNDERSTAND":
        print("aborting.")
        sys.exit(1)


def cmd_once():
    confirm_live()
    agent = TradingAgent()
    out = agent.run_once()
    print("\n--- AGENT OUTPUT ---")
    print(out)


def cmd_loop(interval: int):
    confirm_live()
    broker = Broker()
    agent = TradingAgent()
    print(f"loop mode, interval {interval}s. ctrl+C to stop.")
    while True:
        try:
            _write_heartbeat()
            if broker.is_market_open():
                print(f"\n[{datetime.now().isoformat()}] cycle...")
                out = agent.run_once()
                print(out)
            else:
                print(f"[{datetime.now().isoformat()}] market closed, sleeping.")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopping.")
            return
        except Exception as e:
            ts = datetime.now().isoformat()
            print(f"[{ts}] cycle error: {type(e).__name__}: {e}")
            print(traceback.format_exc())
            time.sleep(60)


def cmd_panic():
    print("PANIC: closing all positions, cancelling all orders.")
    if input("type 'YES' to confirm: ").strip() != "YES":
        print("aborted.")
        return
    broker = Broker()
    result = broker.close_all_positions()
    print("closed:", result)


def main():
    banner()
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "once":
        cmd_once()
    elif mode == "loop":
        # Default loop interval for swing trading in active mode: 1 hour.
        # This gives the bot enough chances per day to spot fresh setups while
        # respecting that swing trading doesn't need minute-by-minute reaction.
        # Override with: python main.py loop 7200 (every 2 hours), etc.
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
        cmd_loop(interval)
    elif mode == "panic":
        cmd_panic()
    else:
        print(f"unknown mode: {mode}")
        print(__doc__)


if __name__ == "__main__":
    main()
