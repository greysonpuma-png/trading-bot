"""
Risk layer. Every order proposal passes through here BEFORE going to the broker.

The LLM cannot bypass any of these checks — they run in Python, not in the prompt.
This is the most important file in the project. Read it carefully before changing.
"""
import json
import os
from dataclasses import dataclass
from datetime import date

from config import CONFIG
from broker import Broker


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str


class RiskLayer:
    def __init__(self, broker: Broker):
        self.broker = broker
        os.makedirs(CONFIG.log_dir, exist_ok=True)
        self.daily_pnl_file = os.path.join(CONFIG.log_dir, "daily_pnl.json")

    def check_order(self, symbol: str, qty: int, side: str,
                    stop_price: float = None, take_profit_price: float = None) -> RiskCheckResult:
        symbol = symbol.upper()
        side = side.lower()

        # 1. Symbol whitelist
        if CONFIG.allowed_symbols and symbol not in CONFIG.allowed_symbols:
            return RiskCheckResult(False, f"{symbol} not in allowed_symbols whitelist")

        # 2. Sane qty
        if qty <= 0:
            return RiskCheckResult(False, "qty must be positive")
        if qty > CONFIG.max_order_qty:
            return RiskCheckResult(False, f"qty {qty} exceeds max_order_qty {CONFIG.max_order_qty}")

        # 3. Market open
        if CONFIG.market_hours_only and not self.broker.is_market_open():
            return RiskCheckResult(False, "market is closed")

        # 4. Daily loss circuit breaker
        account = self.broker.get_account()
        today_pnl = self._compute_daily_pnl(account["equity"])
        if today_pnl <= -CONFIG.max_daily_loss_usd:
            return RiskCheckResult(
                False,
                f"daily loss ${today_pnl:.2f} hit limit of ${CONFIG.max_daily_loss_usd}. trading halted for the day."
            )

        # 5. Position dollar-size cap, PER SYMBOL: what we already hold in this
        #    symbol plus the new order must stay under the cap. Without counting
        #    the existing holding, repeat picks of the same symbol stack past the
        #    cap one order at a time (JNJ reached ~4.7x the cap this way).
        try:
            quote = self.broker.get_quote(symbol)
            est_value = quote["ask"] * qty
        except Exception as e:
            return RiskCheckResult(False, f"could not fetch quote: {e}")

        positions = self.broker.get_positions()
        existing = {p["symbol"]: p for p in positions}

        if side == "buy":
            held_value = float(existing.get(symbol, {}).get("market_value", 0.0))
            if est_value + held_value > CONFIG.max_position_size_usd:
                return RiskCheckResult(
                    False,
                    f"order ${est_value:.2f} + existing {symbol} position ${held_value:.2f} "
                    f"exceeds max_position_size_usd ${CONFIG.max_position_size_usd}"
                )

        # 6. Max concurrent positions
        if side == "buy" and symbol not in existing and len(positions) >= CONFIG.max_open_positions:
            return RiskCheckResult(
                False,
                f"already at max_open_positions ({CONFIG.max_open_positions})"
            )

        # 7. Can't sell what we don't own (no shorting in this template)
        if side == "sell":
            if symbol not in existing:
                return RiskCheckResult(False, f"cannot sell {symbol} — no position held (shorting disabled)")
            if float(existing[symbol]["qty"]) < qty:
                return RiskCheckResult(
                    False,
                    f"cannot sell {qty} of {symbol} — only {existing[symbol]['qty']} owned"
                )

        # 8. Buying power
        if side == "buy" and est_value > account["buying_power"]:
            return RiskCheckResult(
                False,
                f"order value ${est_value:.2f} exceeds buying_power ${account['buying_power']:.2f}"
            )

        # 9. Sector concentration — don't pile into one correlated sector.
        #    Broad index ETFs are diversified by nature and exempt from this cap.
        if side == "buy" and symbol not in existing:
            sector = CONFIG.sector_map.get(symbol)
            if sector and sector != "broad_index":
                same_sector = sum(
                    1 for p in positions
                    if CONFIG.sector_map.get(p["symbol"]) == sector
                )
                if same_sector >= CONFIG.max_positions_per_sector:
                    return RiskCheckResult(
                        False,
                        f"already holding {same_sector} '{sector}' position(s); "
                        f"max_positions_per_sector is {CONFIG.max_positions_per_sector}. "
                        f"Choose a different sector to stay diversified."
                    )

        # 10. Exit-protection sanity — for buys, validate whatever exit mechanism
        #    this configuration uses. The model cannot sneak through an unprotected
        #    position in either mode.
        if side == "buy" and CONFIG.exit_style == "trailing":
            # Trailing mode: protection is a server-side trailing stop attached
            # after fill. Validate the trail distance like a stop distance —
            # 3-15%, same band as bracket stops. No target to validate.
            tp = CONFIG.trail_percent
            if not (3.0 <= tp <= 15.0):
                return RiskCheckResult(
                    False,
                    f"trail_percent {tp}% outside the 3-15% band — fix TRAIL_PERCENT in .env"
                )
        elif side == "buy":
            if stop_price is None or take_profit_price is None:
                return RiskCheckResult(False, "buy orders require both stop_price and take_profit_price")
            entry = quote["ask"]
            if stop_price >= entry:
                return RiskCheckResult(False, f"stop ${stop_price:.2f} must be BELOW entry ${entry:.2f}")
            if take_profit_price <= entry:
                return RiskCheckResult(False, f"target ${take_profit_price:.2f} must be ABOVE entry ${entry:.2f}")
            stop_pct = (entry - stop_price) / entry * 100.0
            if stop_pct < 3.0:
                return RiskCheckResult(
                    False,
                    f"stop too tight: {stop_pct:.2f}% below entry. Swing trades need a 3-15% stop — "
                    f"a 0.3% stop is day-trade noise and will get shaken out."
                )
            if stop_pct > 15.0:
                return RiskCheckResult(
                    False,
                    f"stop too wide: {stop_pct:.2f}% below entry. Cap is 15% to limit per-trade loss."
                )
            risk_per_share = entry - stop_price
            reward_per_share = take_profit_price - entry
            rr = reward_per_share / risk_per_share if risk_per_share > 0 else 0
            if rr < 1.5:
                return RiskCheckResult(
                    False,
                    f"reward:risk only {rr:.2f}:1. Need at least 1.5:1 — widen the target or tighten the stop."
                )

        return RiskCheckResult(True, "approved")

    def _compute_daily_pnl(self, current_equity: float) -> float:
        """Snapshot equity at first call each day, then return current - snapshot."""
        today = date.today().isoformat()
        data = {}
        if os.path.exists(self.daily_pnl_file):
            with open(self.daily_pnl_file) as f:
                data = json.load(f)

        if data.get("date") != today:
            data = {"date": today, "starting_equity": current_equity}
            with open(self.daily_pnl_file, "w") as f:
                json.dump(data, f)
            return 0.0

        return current_equity - data["starting_equity"]
