"""
Review pending trade proposals and approve / reject manually.

Run this when CONFIG.auto_execute_proposals is False.

After a proposal is approved and submitted, an "update" record is appended to
proposals.jsonl marking it executed — so the same trade can never be approved
or submitted twice across multiple runs of this script.
"""
import json
import os
from datetime import datetime

from config import CONFIG
from broker import Broker


def _load_state(path):
    """Return (proposals, executed_timestamps).

    proposals           — every proposal record (non-update lines)
    executed_timestamps — set of proposal timestamps that have an execution update
    """
    proposals = []
    executed = set()
    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "update" in entry:
                upd = entry["update"]
                ts = upd.get("timestamp")
                if ts and upd.get("executed"):
                    executed.add(ts)
                continue
            proposals.append(entry)
    return proposals, executed


def main():
    path = os.path.join(CONFIG.log_dir, "proposals.jsonl")
    if not os.path.exists(path):
        print("no proposals file yet.")
        return

    proposals, executed = _load_state(path)

    # Pending = risk-approved (status 'pending'), not flagged executed on its own
    # record, AND not already executed via a later update record.
    pending = [
        p for p in proposals
        if p.get("status") == "pending"
        and not p.get("executed")
        and p.get("timestamp") not in executed
    ]

    if not pending:
        print("no pending proposals.")
        return

    broker = Broker()
    print(f"\n{len(pending)} pending proposal(s):\n")
    for i, p in enumerate(pending, 1):
        print(f"[{i}] {p['side'].upper():4s} {p['qty']:>4d} {p['symbol']:<6s}  ({p['timestamp']})")
        if p.get("stop_price") and p.get("take_profit_price"):
            print(f"     stop-loss: ${p['stop_price']}   take-profit: ${p['take_profit_price']}")
        print(f"     reason: {p['reason']}\n")

    for p in pending:
        choice = input(f"approve {p['side']} {p['qty']} {p['symbol']}? (y/n/q): ").strip().lower()
        if choice == "q":
            print("done.")
            return
        if choice != "y":
            print("  skipped.\n")
            continue
        try:
            # Buys with a stop and target go in as bracket orders (broker-enforced
            # stop-loss + take-profit). Sells to close a position are plain orders.
            if p["side"] == "buy" and p.get("stop_price") and p.get("take_profit_price"):
                order = broker.submit_bracket_order(
                    p["symbol"], p["qty"], "buy",
                    stop_price=p["stop_price"],
                    take_profit_price=p["take_profit_price"],
                )
            else:
                order = broker.submit_order(p["symbol"], p["qty"], p["side"])

            # Mark this proposal executed so it can never be submitted twice.
            with open(path, "a") as f:
                f.write(json.dumps({"update": {
                    "timestamp":   p["timestamp"],
                    "status":      "executed",
                    "executed":    True,
                    "order":       order,
                    "executed_at": datetime.now().isoformat(),
                }}) + "\n")

            print(f"  submitted: {order}\n")
        except Exception as e:
            print(f"  failed: {e}\n")


if __name__ == "__main__":
    main()
