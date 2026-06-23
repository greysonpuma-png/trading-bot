"""
Three-stage swing trading pipeline.

Instead of one overloaded agent, the work is split into three focused stages.
Each stage is the SAME local model (qwen3:4b) given a SHORT, single-purpose
prompt and only the tools it needs — small models are far more reliable on
narrow tasks than on one giant do-everything prompt.

  Stage 1  SCOUT             — from the Python screener's candidates, pick the
                               single best long setup (or none).
  Stage 2  RISK MANAGER      — turn the Scout's pick into a precise bracket order
                               (entry, stop, target, size) and submit it.
  Stage 3  POSITION MANAGER  — review open positions for hold/close, and journal.

Each cycle runs: Position Manager  ->  Scout  ->  Risk Manager.

The public interface (TradingAgent().run_once()) is unchanged, so main.py,
review.py, and loop mode all keep working without modification.
"""
import json
import os
from datetime import datetime
from ollama import Client

from config import CONFIG
from tools import TOOLS_SCHEMA, execute_tool, clear_cycle_cache
from screener import scan_market


# ── which tools each stage is allowed to use ──
SCOUT_TOOLS   = ["get_market_regime", "get_bars", "get_news",
                 "get_recent_proposals", "select_candidate"]
RISK_TOOLS    = ["get_account", "get_positions", "get_quote",
                 "get_bars", "get_volatility", "propose_trade"]
MANAGER_TOOLS = ["get_positions", "get_quote", "get_bars", "get_news",
                 "propose_trade", "write_journal"]


SCOUT_PROMPT = """You are the SCOUT — stage 1 of a 3-stage swing trading system.

Your ONLY job: from a pre-screened list of candidate stocks, identify the single
best LONG swing-trade setup — or decide none is good enough. You do NOT place
trades and you do NOT set entry/stop/target. You only analyze and choose.

The candidates you are given already passed a Python screen: each is in an uptrend
and has pulled back to a rising 20-day moving average. For the most promising ones:
- get_bars(symbol, "1Day", 30) — read the trend, structure, and support levels.
- get_news(symbol) — understand what is driving the stock right now.
- get_market_regime() — a bullish regime favors taking a setup; bearish favors waiting.

Then decide:
- If ONE candidate is a clear, high-quality long setup, call
  select_candidate(symbol, rationale). The rationale must be specific: the setup,
  the trend, the technical read (note the RSI if relevant), and the news context.
- If none is good enough, do NOT call select_candidate. Reply "NO PICK THIS CYCLE"
  and briefly say why.

Choose AT MOST ONE. Quality over activity — but if a genuinely good setup is
present, take it; do not pass out of pure caution.
"""

_RISK_PROMPT_BRACKET = """You are the RISK MANAGER — stage 2 of a 3-stage swing trading system.

The Scout has selected ONE stock for a long swing trade. Your ONLY job: turn that
idea into a precise, risk-managed bracket order.

Steps, in order:
1. get_account and get_positions — check available capital and current holdings.
2. get_quote(symbol) and get_volatility(symbol). get_volatility returns a suggested
   stop price, take-profit price, and share count, all sized so the trade risks a
   constant dollar amount and already passes the risk layer. USE those values.
3. propose_trade(symbol, side="buy", qty, reason, stop_price, take_profit_price) —
   submit exactly ONE trade for the Scout's pick.

The reason field must state: entry, stop (price and %), target (price and %), and
a one-line rationale. If the data shows the trade is genuinely unworkable (for
example, even one share exceeds the position cap), explain why and do not propose.
Otherwise, submit it.
"""

_RISK_PROMPT_TRAILING = """You are the RISK MANAGER — stage 2 of a 3-stage swing trading system.

The Scout has selected ONE stock for a long swing trade. Your ONLY job: size the
position and submit it. Exit protection is automatic: the system attaches a
broker-side TRAILING STOP ({trail}% below the highest price reached) after the
fill. There is NO profit target — losers get cut by the trailing stop, winners
run as long as the trend holds. Do NOT pass stop_price or take_profit_price.

Steps, in order:
1. get_account and get_positions — check available capital and current holdings.
2. get_quote(symbol) and get_volatility(symbol) — use the suggested share count
   (the qty sizing logic still applies even though the stop is a trailing one).
3. propose_trade(symbol, side="buy", qty, reason) — submit exactly ONE trade.

The reason field must state: entry price, the {trail}% trailing-stop protection,
and a one-line rationale. If the trade is genuinely unworkable (for example, even
one share exceeds the position cap), explain why and do not propose. Otherwise,
submit it.
"""

RISK_PROMPT = (_RISK_PROMPT_TRAILING.format(trail=CONFIG.trail_percent)
               if CONFIG.exit_style == "trailing" else _RISK_PROMPT_BRACKET)

MANAGER_PROMPT = """You are the POSITION MANAGER — stage 3 of a 3-stage swing trading system.

Your job: review every open position, decide hold or close, then journal.

1. get_positions — list what is currently held. If nothing is held, just write a
   brief journal note and finish.
2. For each open position: get_quote, get_bars(symbol, "1Day", 30), and get_news.
   - Is the original thesis still intact? Has the multi-day trend genuinely broken?
   - IMPORTANT: every position already has automatic broker-side exit protection
     (older positions: a bracket stop + target; newer ones: a trailing stop that
     ratchets up as the price rises). It will exit on its own. So do NOT close a
     position just because price wobbled. Close ONLY if the multi-day trend has
     clearly broken or the reason for the trade is gone.
   - To close a position, call propose_trade(symbol, side="sell", qty, reason).
3. Finally, call write_journal with a 1-3 sentence review of how the portfolio is
   doing and any lesson worth remembering.

If every position is healthy, holding them all is the correct, expected outcome.
"""


class TradingAgent:
    """Runs the three-stage pipeline. run_once() is the unchanged public entry point."""

    def __init__(self):
        # Pick the model backend from config. The rest of the class is identical
        # either way — both clients expose the same .chat(model, messages, tools).
        if CONFIG.model_provider == "gemini":
            from gemini_client import GeminiClient
            self.client = GeminiClient(api_key=CONFIG.gemini_api_key)
            self.model = CONFIG.gemini_model
        else:
            self.client = Client(host=CONFIG.ollama_host)
            self.model = CONFIG.model_name
        os.makedirs(CONFIG.log_dir, exist_ok=True)
        self.log_file = os.path.join(CONFIG.log_dir, "agent.jsonl")

    # ---- run one focused stage ----
    def _run_stage(self, role, system_prompt, user_prompt, tool_names, max_iters=12):
        """Run a single stage as a focused agent loop. Returns (final_text, captured),
        where captured maps each tool name called to the arguments of its last call."""
        schema = [t for t in TOOLS_SCHEMA if t["function"]["name"] in tool_names]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
        self._log({"event": "stage_start", "role": role})
        captured = {}

        for i in range(max_iters):
            response = self.client.chat(model=self.model, messages=messages, tools=schema)
            msg = response["message"]
            messages.append(msg)
            self._log({"event": "stage_msg", "role": role, "iter": i,
                       "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                final = msg.get("content", "") or "(no output)"
                self._log({"event": "stage_end", "role": role, "final": final})
                return final, captured

            for tc in tool_calls:
                name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                self._log({"event": "tool_call", "role": role, "name": name, "args": args})
                result = execute_tool(name, args)
                self._log({"event": "tool_result", "role": role, "name": name, "result": result})
                captured[name] = args
                messages.append({"role": "tool", "content": json.dumps(result, default=str)})

        self._log({"event": "stage_end", "role": role, "final": "hit max iterations"})
        return "stage hit max iterations", captured

    # ---- run the full cycle ----
    def run_once(self, user_prompt: str = None) -> str:
        self._log({"event": "pipeline_start", "t": datetime.now().isoformat()})
        clear_cycle_cache()   # fresh market data each cycle; dedup re-fetches within it
        parts = []

        # Stage 0 — Python screener (no LLM): reliably scans every symbol.
        try:
            candidates = scan_market(top_n=5)
        except Exception as e:
            candidates = []
            self._log({"event": "scan_error", "error": str(e)})
        self._log({"event": "market_scan", "n_candidates": len(candidates),
                   "candidates": candidates})

        # Stage 3 — POSITION MANAGER: manage what we already hold.
        pm_user = ("Review every open position now. For each, decide hold or close, "
                   "then write a short journal entry on how the portfolio is doing.")
        pm_text, _ = self._run_stage("PositionManager", MANAGER_PROMPT, pm_user, MANAGER_TOOLS)
        parts.append("--- POSITION MANAGER ---\n" + pm_text)

        # Stage 1 — SCOUT: find one new setup from the screened candidates.
        if candidates:
            lines = "\n".join(
                f"  - {c['symbol']} ({c['sector']}): ${c['price']}, "
                f"{c['pct_above_ma20']:+.2f}% vs 20-day MA, RSI {c.get('rsi', 'n/a')}, "
                f"MACD {'bullish' if c.get('macd_bullish') else 'bearish/flat'}"
                for c in candidates
            )
            scout_user = ("Today's pre-screened candidates (already in an uptrend and pulled "
                          "back to a rising 20-day moving average):\n" + lines +
                          "\n\nAnalyze them and select the single best long setup, or make no pick.")
        else:
            scout_user = ("The Python screener found no qualifying candidates today. There is "
                          "very likely no pick this cycle — confirm briefly and do not force one.")
        scout_text, scout_cap = self._run_stage("Scout", SCOUT_PROMPT, scout_user, SCOUT_TOOLS)
        parts.append("--- SCOUT ---\n" + scout_text)

        # Stage 2 — RISK MANAGER: only runs if the Scout actually picked something.
        pick = scout_cap.get("select_candidate")
        if pick and pick.get("symbol"):
            rm_user = (f"The Scout selected {pick['symbol']} for a long swing trade.\n"
                       f"Scout's rationale: {pick.get('rationale', '(none provided)')}\n\n"
                       "Determine the entry, stop-loss, take-profit, and position size, "
                       "and submit the trade with propose_trade.")
            rm_text, _ = self._run_stage("RiskManager", RISK_PROMPT, rm_user, RISK_TOOLS)
            parts.append("--- RISK MANAGER ---\n" + rm_text)
        else:
            parts.append("--- RISK MANAGER ---\nSkipped — the Scout made no pick this cycle.")

        final = "\n\n".join(parts)
        self._log({"event": "pipeline_end", "final": final})
        return final

    def _log(self, entry: dict):
        entry["t"] = datetime.now().isoformat()
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
