"""
Exp5 competency scorecard — mandate fidelity, NOT P/L.

The question this answers: given a written mean-reversion mandate (buy low,
sell high, 3-5 entries/week, max 1/day), did the LLM pipeline execute it
faithfully? P&L is deliberately absent — the profitability question was
answered by the Exp4 forward test (alpha ~0%, read 2026-09-01) and 20 trading
days of returns is noise anyway.

Reads logs/agent.jsonl and logs/proposals.jsonl from EXP5_START onward.
Run: python competency_report.py
"""
import json
import os
from collections import defaultdict
from datetime import date, datetime

from config import CONFIG

EXP5_START = "2026-09-04"   # first trading day under the mean-reversion mandate
EXP5_READ  = "2026-10-01"   # pre-registered 4-week read


def _load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _cycles(agent_rows):
    """Group agent.jsonl rows into cycles (pipeline_start .. pipeline_end)."""
    cycles, cur = [], None
    for r in agent_rows:
        t = str(r.get("t", ""))
        if t[:10] < EXP5_START:
            continue
        if r.get("event") == "pipeline_start":
            cur = {"t": t, "rows": []}
        elif cur is not None:
            cur["rows"].append(r)
            if r.get("event") == "pipeline_end":
                cycles.append(cur)
                cur = None
    return cycles


def _tool_results(cycle, name):
    """(args, result) pairs for one tool within one cycle, in order."""
    out, pending = [], None
    for r in cycle["rows"]:
        if r.get("event") == "tool_call" and r.get("name") == name:
            pending = r.get("args") or {}
        elif r.get("event") == "tool_result" and r.get("name") == name:
            res = r.get("result") or {}
            if isinstance(res, dict):
                res = res.get("result", res)
            out.append((pending or {}, res if isinstance(res, dict) else {}))
            pending = None
    return out


def main():
    agent_rows = _load_jsonl(os.path.join(CONFIG.log_dir, "agent.jsonl"))
    prop_rows  = _load_jsonl(os.path.join(CONFIG.log_dir, "proposals.jsonl"))
    cycles = _cycles(agent_rows)

    # ── executed entries + sells from proposals.jsonl ──
    executed_buys, risk_rejections, executed_sells = [], [], []
    for r in prop_rows:
        upd = r.get("update")
        row = upd or r
        ts = str(row.get("timestamp", ""))
        if ts[:10] < EXP5_START:
            continue
        if upd and upd.get("executed"):
            (executed_buys if upd.get("side") == "buy" else executed_sells).append(upd)
        elif not upd and r.get("risk_approved") is False:
            risk_rejections.append(r)

    # ── cadence: entries per day and per ISO week ──
    by_day, by_week = defaultdict(int), defaultdict(int)
    for b in executed_buys:
        d = date.fromisoformat(b["timestamp"][:10])
        by_day[d.isoformat()] += 1
        by_week[f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"] += 1
    days_over_cap = {d: n for d, n in by_day.items()
                     if n > CONFIG.meanrev_max_entries_per_day}

    # ── Scout discipline: picks attempted while the day was already at cap ──
    picks_at_cap = 0
    for c in cycles:
        at_cap = any(r.get("event") == "cadence"
                     and r.get("entries_executed_today", 0) >= CONFIG.meanrev_max_entries_per_day
                     for r in c["rows"])
        picked = any(r.get("event") == "tool_call" and r.get("name") == "select_candidate"
                     for r in c["rows"])
        if at_cap and picked:
            picks_at_cap += 1

    # ── entry adherence: executed buy was among that cycle's screener candidates ──
    entry_ok = entry_bad = 0
    offenders = []
    for c in cycles:
        cands = set()
        for r in c["rows"]:
            if r.get("event") == "market_scan":
                cands = {x.get("symbol") for x in (r.get("candidates") or [])}
        bought = {a.get("symbol", "").upper()
                  for a, res in _tool_results(c, "propose_trade")
                  if a.get("side") == "buy" and isinstance(res, dict) and res.get("executed")}
        for sym in bought:
            if sym in cands:
                entry_ok += 1
            else:
                entry_bad += 1
                offenders.append((c["t"][:16], sym))

    # ── exit fidelity: exit_signal=true acted on; no improvised sells ──
    signals_true = acted = 0
    missed, improvised = [], []
    for c in cycles:
        status = {}
        for a, res in _tool_results(c, "get_reversion_status"):
            if res.get("held"):
                status[res.get("symbol")] = bool(res.get("exit_signal"))
        sells = {a.get("symbol", "").upper()
                 for a, _res in _tool_results(c, "propose_trade")
                 if a.get("side") == "sell"}
        for sym, sig in status.items():
            if sig:
                signals_true += 1
                if sym in sells:
                    acted += 1
                else:
                    missed.append((c["t"][:16], sym))
        for sym in sells:
            if not status.get(sym, False):
                improvised.append((c["t"][:16], sym))

    # ── journaling completeness ──
    journaled = sum(1 for c in cycles
                    if any(r.get("event") == "tool_call" and r.get("name") == "write_journal"
                           for r in c["rows"]))

    # ── report ──
    line = "=" * 64
    print(line)
    print(" EXP5 COMPETENCY SCORECARD — mean-reversion mandate fidelity")
    print(line)
    print(f"  window:  {EXP5_START} -> {EXP5_READ}  (today: {date.today().isoformat()})")
    print(f"  cycles analyzed: {len(cycles)}")
    print()
    print("  CADENCE (target 3-5 entries/week, hard max 1/day)")
    for wk in sorted(by_week):
        n = by_week[wk]
        band = "in band" if 3 <= n <= 5 else ("dry" if n < 3 else "OVER")
        print(f"    {wk}: {n} entries  [{band}]")
    print(f"    days over the 1/day cap: {len(days_over_cap)}"
          + (f"  {days_over_cap}" if days_over_cap else "  (enforcement held)"))
    print(f"    Scout picks attempted while day was at cap: {picks_at_cap} "
          "(LLM discipline; risk layer blocks execution regardless)")
    print()
    print("  ENTRY ADHERENCE (buys must come from the mandate's screen)")
    total_e = entry_ok + entry_bad
    pct = (100.0 * entry_ok / total_e) if total_e else 100.0
    print(f"    on-mandate entries: {entry_ok}/{total_e}  ({pct:.0f}%)")
    for t, sym in offenders:
        print(f"      OFF-MANDATE: {sym} at {t}")
    print()
    print("  EXIT FIDELITY (sell exactly when exit_signal says so)")
    pct = (100.0 * acted / signals_true) if signals_true else 100.0
    print(f"    exit signals acted on same cycle: {acted}/{signals_true}  ({pct:.0f}%)")
    for t, sym in missed:
        print(f"      MISSED EXIT: {sym} at {t}")
    print(f"    improvised sells (no signal): {len(improvised)}")
    for t, sym in improvised:
        print(f"      IMPROVISED: {sym} at {t}")
    print()
    print("  SAFETY & HYGIENE")
    print(f"    risk-layer rejections: {len(risk_rejections)}")
    reasons = defaultdict(int)
    for r in risk_rejections:
        reasons[(r.get("risk_message") or "?")[:60]] += 1
    for msg, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"      {n}x  {msg}")
    print(f"    cycles journaled: {journaled}/{len(cycles)}")
    print(line)
    print("  Score = fidelity, not P/L. A dry week with honest 'no pick' cycles")
    print("  is a PASS; an off-mandate trade or missed exit is the failure mode.")
    print(line)


if __name__ == "__main__":
    main()
