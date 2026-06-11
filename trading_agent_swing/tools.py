"""
Tools exposed to the LLM via Ollama function calling.

Design choice: the model can READ freely (account, positions, quotes, bars, news,
recent proposals) but the only WRITE tool is propose_trade(), which always passes
through risk_layer before doing anything. There is no direct "submit_order" tool
the LLM can call.
"""
import json
import os
from datetime import datetime

from config import CONFIG
from broker import Broker
from risk_layer import RiskLayer


# module-level singletons
_broker = Broker()
_risk = RiskLayer(_broker)

os.makedirs(CONFIG.log_dir, exist_ok=True)
_proposals_file = os.path.join(CONFIG.log_dir, "proposals.jsonl")


# ===== read-only tools =====

def get_account() -> dict:
    """Account balance, equity, buying power, day trade count."""
    return _broker.get_account()


def get_positions() -> list:
    """Current positions with unrealized P&L."""
    return _broker.get_positions()


def get_quote(symbol: str) -> dict:
    """Latest bid/ask for a symbol."""
    return _broker.get_quote(symbol.upper())


def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 30) -> list:
    """Historical OHLCV bars. timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day."""
    return _broker.get_bars(symbol.upper(), timeframe, min(limit, 100))


def get_news(symbol: str, limit: int = 5, days_back: int = 7) -> list:
    """Recent news headlines for a symbol. Use this to understand WHY a stock is moving."""
    return _broker.get_news(symbol.upper(), limit=limit, days_back=days_back)


def get_recent_proposals(limit: int = 10) -> list:
    """Read the most recent N proposals this bot has made (across all cycles).
    Use this to see your own history — what setups you've taken, what got
    rejected by the risk layer, and what symbols you've already proposed on.
    Helps avoid re-proposing the same trade or contradicting your prior reasoning.
    """
    if not os.path.exists(_proposals_file):
        return []
    rows = []
    with open(_proposals_file) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "update" in entry:
                # execution update record — fold into the matching proposal if needed
                continue
            rows.append({
                "timestamp":     entry.get("timestamp"),
                "symbol":        entry.get("symbol"),
                "side":          entry.get("side"),
                "qty":           entry.get("qty"),
                "reason":        (entry.get("reason") or "")[:200],
                "risk_approved": entry.get("risk_approved"),
                "risk_message":  entry.get("risk_message"),
                "status":        entry.get("status"),
                "executed":      entry.get("executed"),
            })
    return rows[-max(1, min(limit, 50)):]


def get_market_regime() -> dict:
    """Assess the BROAD MARKET regime using SPY versus its 50- and 200-day moving
    averages. Call this at the START of every cycle. The regime should shape how
    aggressive you are: in a bearish regime most strategies lose simply by being
    fully invested while the market falls — so favor 'no trade' or much smaller size.
    """
    bars = _broker.get_bars("SPY", "1Day", limit=220)
    closes = [b["close"] for b in bars]
    if len(closes) < 60:
        return {"regime": "unknown", "note": "insufficient SPY history"}

    price = closes[-1]
    ma50 = sum(closes[-50:]) / 50
    long_window = closes[-200:] if len(closes) >= 200 else closes
    ma200 = sum(long_window) / len(long_window)
    mom20 = (price / closes[-21] - 1) * 100 if len(closes) >= 21 else 0.0

    if price > ma50 > ma200:
        regime = "bullish"
        guidance = "Broad uptrend — normal swing setups are reasonable."
    elif price < ma50 < ma200:
        regime = "bearish"
        guidance = "Broad downtrend — be very selective or stand aside; favor 'no trade'."
    else:
        regime = "neutral"
        guidance = "Mixed/choppy market — take only the cleanest setups, consider smaller size."

    return {
        "regime": regime,
        "spy_price": round(price, 2),
        "spy_ma50": round(ma50, 2),
        "spy_ma200": round(ma200, 2),
        "spy_20d_momentum_pct": round(mom20, 2),
        "guidance": guidance,
    }


def get_volatility(symbol: str, risk_budget_usd: float = 150.0) -> dict:
    """Measure a symbol's volatility (14-day ATR) and suggest a volatility-aware
    stop price, take-profit price, and share count so that EACH trade risks
    roughly the same dollar amount regardless of how jumpy the stock is.

    Call this before a buy and use the suggested values directly in propose_trade.
    """
    symbol = symbol.upper()
    bars = _broker.get_bars(symbol, "1Day", limit=30)
    if len(bars) < 15:
        return {"symbol": symbol, "error": "insufficient history for ATR"}

    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-14:]) / min(14, len(trs))
    price = bars[-1]["close"]
    atr_pct = atr / price * 100 if price > 0 else 0.0

    # Stop = 2x ATR below entry, clamped into the risk layer's 3-15% band.
    stop_distance = min(max(2 * atr, price * 0.03), price * 0.15)
    suggested_stop   = round(price - stop_distance, 2)
    suggested_target = round(price + 2 * stop_distance, 2)   # 2:1 reward:risk
    suggested_qty    = int(risk_budget_usd / stop_distance) if stop_distance > 0 else 0

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "atr_14d": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "suggested_stop_price": suggested_stop,
        "suggested_take_profit_price": suggested_target,
        "suggested_qty": max(suggested_qty, 0),
        "note": (f"Sized so the trade risks about ${risk_budget_usd:.0f} if stopped out. "
                 "Stop = 2x ATR, clamped to the 3-15% band. Jumpier stocks get fewer "
                 "shares; calmer stocks get more. These values already satisfy the risk layer."),
    }


# ===== the only write tool =====

def propose_trade(symbol: str, side: str, qty: int, reason: str,
                  stop_price: float = None, take_profit_price: float = None) -> dict:
    """
    Propose a trade. Always passes through risk_layer first.

    BUY orders MUST include stop_price and take_profit_price — they are submitted as
    bracket orders so the stop-loss and take-profit are enforced by the broker itself.
    SELL orders (closing an existing position) are plain market orders.

    Either queued for human review or auto-executed depending on CONFIG.auto_execute_proposals.
    """
    symbol = symbol.upper()
    side = side.lower()

    # A buy with no stop/target is not allowed — bounce it back so the model retries.
    if side == "buy" and (stop_price is None or take_profit_price is None):
        return {
            "accepted": False,
            "reason": ("buy proposals MUST include numeric stop_price and take_profit_price. "
                       "Re-call propose_trade with both so the position has automatic exit protection."),
        }

    risk = _risk.check_order(symbol, qty, side,
                             stop_price=stop_price, take_profit_price=take_profit_price)

    proposal = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "reason": reason,
        "stop_price": stop_price,
        "take_profit_price": take_profit_price,
        "risk_approved": risk.approved,
        "risk_message": risk.reason,
        "status": "rejected" if not risk.approved else "pending",
        "executed": False,
    }

    with open(_proposals_file, "a") as f:
        f.write(json.dumps(proposal) + "\n")

    if not risk.approved:
        return {"accepted": False, "reason": risk.reason}

    if CONFIG.auto_execute_proposals:
        try:
            if side == "buy":
                order = _broker.submit_bracket_order(symbol, qty, "buy",
                                                     stop_price, take_profit_price)
            else:
                order = _broker.submit_order(symbol, qty, side)
            update = {**proposal, "status": "executed", "executed": True, "order": order}
            with open(_proposals_file, "a") as f:
                f.write(json.dumps({"update": update}) + "\n")
            return {"accepted": True, "executed": True, "order": order}
        except Exception as e:
            return {"accepted": True, "executed": False, "error": str(e)}

    return {
        "accepted": True,
        "executed": False,
        "message": "queued for human review. run `python review.py` to approve.",
    }


# ===== pipeline handoff tools =====

def select_candidate(symbol: str, rationale: str) -> dict:
    """SCOUT stage: lock in the single best candidate for this cycle. Records the
    pick; the Risk Manager stage then specs and submits the actual trade."""
    symbol = symbol.upper()
    entry = {"timestamp": datetime.now().isoformat(), "symbol": symbol, "rationale": rationale}
    with open(os.path.join(CONFIG.log_dir, "picks.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return {"recorded": True, "symbol": symbol,
            "message": f"{symbol} locked in as this cycle's pick; handed to the Risk Manager."}


def write_journal(note: str) -> dict:
    """POSITION MANAGER stage: append a short review note to the trade journal."""
    entry = {"timestamp": datetime.now().isoformat(), "note": note}
    with open(os.path.join(CONFIG.log_dir, "journal.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return {"recorded": True, "message": "journal entry saved"}


# ===== schema + dispatch =====

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_account",
            "description": "Get account balance, equity, buying power, day trade count.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": "List currently held positions with unrealized P&L.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Get latest bid/ask quote for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bars",
            "description": "Get historical OHLCV bars for technical analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol":    {"type": "string"},
                    "timeframe": {"type": "string", "enum": ["1Min", "5Min", "15Min", "1Hour", "1Day"]},
                    "limit":     {"type": "integer", "description": "number of bars (max 100)"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": (
                "Recent news headlines for a symbol. Use this BEFORE proposing a trade — "
                "the chart pattern alone is not enough; you need to understand WHY the stock is moving "
                "(earnings, M&A, analyst upgrade, sector news, macro event). "
                "Returns up to 'limit' headlines from the past 'days_back' days."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol":    {"type": "string"},
                    "limit":     {"type": "integer", "description": "max headlines to return (default 5, max 50)"},
                    "days_back": {"type": "integer", "description": "how many days of history to search (default 7)"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_proposals",
            "description": (
                "Look back at your own recent trade proposals (across cycles). "
                "Useful to: (a) avoid re-proposing a trade you already made, "
                "(b) see which of your past ideas got rejected by the risk layer and why, "
                "(c) maintain consistency in your reasoning over time. "
                "Call this near the start of a cycle to refresh your memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "number of recent proposals to return (default 10, max 50)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_regime",
            "description": (
                "Assess the broad market regime (bullish / neutral / bearish) using SPY "
                "vs its 50- and 200-day moving averages. Call this FIRST every cycle — "
                "in a bearish regime you should mostly stand aside."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_volatility",
            "description": (
                "Measure a stock's volatility (14-day ATR) and get a suggested stop price, "
                "take-profit price, and share count sized so the trade risks a constant dollar "
                "amount. Call this before a buy and use the suggested values in propose_trade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol":          {"type": "string"},
                    "risk_budget_usd": {"type": "number", "description": "dollars to risk if stopped out (default 150)"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_trade",
            "description": (
                "Propose a trade. Passes through risk checks. "
                "REQUIRED first: get_account, get_positions, get_quote, get_bars(1Day,30), get_news. "
                "For a BUY you MUST also pass stop_price and take_profit_price as numbers — the order is "
                "submitted as a bracket order so the stop-loss and take-profit are enforced automatically "
                "by the broker, even when the bot is offline. The risk layer requires the stop to be 3-15% "
                "below entry and the reward:risk ratio to be at least 1.5:1."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side":   {"type": "string", "enum": ["buy", "sell"]},
                    "qty":    {"type": "integer"},
                    "reason": {"type": "string", "description": "Setup name, entry $, stop $ (with %), target $ (with %), and a one-line rationale referencing news/chart context."},
                    "stop_price":        {"type": "number", "description": "Stop-loss price. REQUIRED for buys. Must be 3-15% below entry."},
                    "take_profit_price": {"type": "number", "description": "Take-profit price. REQUIRED for buys. Must give at least 1.5:1 reward-to-risk."},
                },
                "required": ["symbol", "side", "qty", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_candidate",
            "description": (
                "SCOUT ONLY. Lock in the single best long swing-trade candidate for this cycle. "
                "Call this exactly once, when you have chosen. If no candidate is good enough, "
                "do NOT call it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol":    {"type": "string"},
                    "rationale": {"type": "string", "description": "Why this is the best setup: trend, technical read, news context."},
                },
                "required": ["symbol", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_journal",
            "description": (
                "POSITION MANAGER ONLY. Save a 1-3 sentence review of how the portfolio is doing "
                "and any lesson worth remembering from recent trades."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string"},
                },
                "required": ["note"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_account":          get_account,
    "get_positions":        get_positions,
    "get_quote":            get_quote,
    "get_bars":             get_bars,
    "get_news":             get_news,
    "get_recent_proposals": get_recent_proposals,
    "get_market_regime":    get_market_regime,
    "get_volatility":       get_volatility,
    "propose_trade":        propose_trade,
    "select_candidate":     select_candidate,
    "write_journal":        write_journal,
}


def execute_tool(name: str, arguments: dict) -> dict:
    if name not in TOOL_FUNCTIONS:
        return {"error": f"unknown tool: {name}"}
    try:
        return {"result": TOOL_FUNCTIONS[name](**arguments)}
    except TypeError as e:
        return {"error": f"bad arguments to {name}: {e}"}
    except Exception as e:
        return {"error": f"tool {name} failed: {e}"}
