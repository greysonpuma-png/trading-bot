"""
Tests for risk_layer.py — the file the LLM cannot bypass.

Every test feeds the risk layer a proposal it MUST reject (or one it must
approve) using a FakeBroker, so no network calls and no real account are
involved. Run with:

    python -m pytest test_risk_layer.py -v

If any of these fail after a change to risk_layer.py or config.py, a safety
check has regressed — do not run the bot until they pass again.
"""
import json
from datetime import date

import pytest

from config import CONFIG
from risk_layer import RiskLayer


# ─── Fake broker — answers the four methods RiskLayer calls, no network ─────

class FakeBroker:
    def __init__(self, market_open=True, equity=100_000.0, buying_power=100_000.0,
                 ask=100.0, positions=None, quote_error=False):
        self.market_open  = market_open
        self.equity       = equity
        self.buying_power = buying_power
        self.ask          = ask
        self.positions    = positions or []
        self.quote_error  = quote_error

    def is_market_open(self):
        return self.market_open

    def get_account(self):
        return {
            "cash": self.equity,
            "equity": self.equity,
            "buying_power": self.buying_power,
            "daytrade_count": 0,
            "pattern_day_trader": False,
        }

    def get_quote(self, symbol):
        if self.quote_error:
            raise RuntimeError("simulated quote feed outage")
        return {
            "symbol": symbol,
            "bid": self.ask - 0.10,
            "ask": self.ask,
            "bid_size": 10,
            "ask_size": 10,
            "timestamp": None,
        }

    def get_positions(self):
        return self.positions


def make_risk(tmp_path, broker):
    """RiskLayer pointed at a temp daily-pnl file so tests never touch ./logs/."""
    risk = RiskLayer(broker)
    risk.daily_pnl_file = str(tmp_path / "daily_pnl.json")
    return risk


# A bracket that satisfies check 10 at entry=$100: 6% stop, 12% target, R:R 2.0
GOOD_STOP   = 94.0
GOOD_TARGET = 112.0


# ─── Check 1: symbol whitelist ───────────────────────────────────────────────

def test_rejects_symbol_not_in_whitelist(tmp_path):
    risk = make_risk(tmp_path, FakeBroker())
    result = risk.check_order("GME", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "whitelist" in result.reason


# ─── Check 2: sane quantity ──────────────────────────────────────────────────

def test_rejects_zero_qty(tmp_path):
    risk = make_risk(tmp_path, FakeBroker())
    result = risk.check_order("SPY", 0, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "positive" in result.reason


def test_rejects_qty_over_max(tmp_path):
    risk = make_risk(tmp_path, FakeBroker())
    result = risk.check_order("SPY", CONFIG.max_order_qty + 1, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "max_order_qty" in result.reason


# ─── Check 3: market hours ───────────────────────────────────────────────────

def test_rejects_when_market_closed(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(market_open=False))
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "closed" in result.reason


# ─── Check 4: daily loss circuit breaker ─────────────────────────────────────

def test_rejects_after_daily_loss_limit(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(equity=100_000.0))
    # Simulate "we started today $600 higher than we are now" — past the $500 limit
    with open(risk.daily_pnl_file, "w") as f:
        json.dump({"date": date.today().isoformat(),
                   "starting_equity": 100_000.0 + CONFIG.max_daily_loss_usd + 100}, f)
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "halted" in result.reason


# ─── Check 5: per-position dollar cap ────────────────────────────────────────

def test_rejects_position_over_dollar_cap(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    too_many = int(CONFIG.max_position_size_usd / 100.0) + 1   # $100/share → 26 shares = $2600
    result = risk.check_order("SPY", too_many, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "max_position_size_usd" in result.reason


def test_rejects_when_quote_unavailable(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(quote_error=True))
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "quote" in result.reason


# ─── Check 6: max concurrent positions ───────────────────────────────────────

def test_rejects_buy_at_max_open_positions(tmp_path):
    full_book = [{"symbol": s, "qty": 1.0} for s in
                 ["AAPL", "JPM", "WMT", "UNH", "CAT", "XOM", "DIS", "NFLX"][:CONFIG.max_open_positions]]
    risk = make_risk(tmp_path, FakeBroker(positions=full_book))
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "max_open_positions" in result.reason


# ─── Check 7: long-only (no shorting, no overselling) ────────────────────────

def test_rejects_sell_with_no_position(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(positions=[]))
    result = risk.check_order("SPY", 5, "sell")
    assert not result.approved
    assert "shorting disabled" in result.reason


def test_rejects_selling_more_than_owned(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(positions=[{"symbol": "SPY", "qty": 2.0}]))
    result = risk.check_order("SPY", 5, "sell")
    assert not result.approved
    assert "only" in result.reason


# ─── Check 8: buying power ───────────────────────────────────────────────────

def test_rejects_buy_exceeding_buying_power(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0, buying_power=300.0))
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)   # $500 > $300
    assert not result.approved
    assert "buying_power" in result.reason


# ─── Check 9: sector concentration cap ───────────────────────────────────────

def test_rejects_fourth_position_in_one_sector(tmp_path):
    three_tech = [{"symbol": s, "qty": 1.0} for s in ["AAPL", "MSFT", "NVDA"]]
    risk = make_risk(tmp_path, FakeBroker(positions=three_tech))
    result = risk.check_order("GOOGL", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert not result.approved
    assert "sector" in result.reason


def test_broad_index_etfs_exempt_from_sector_cap(tmp_path):
    three_broad = [{"symbol": s, "qty": 1.0} for s in ["SPY", "QQQ", "IWM"]]
    risk = make_risk(tmp_path, FakeBroker(positions=three_broad))
    result = risk.check_order("DIA", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert result.approved, result.reason


# ─── Check 10: bracket sanity ────────────────────────────────────────────────

def test_rejects_buy_without_bracket(tmp_path):
    risk = make_risk(tmp_path, FakeBroker())
    result = risk.check_order("SPY", 5, "buy")
    assert not result.approved
    assert "require both" in result.reason


def test_rejects_stop_above_entry(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", stop_price=105.0, take_profit_price=112.0)
    assert not result.approved
    assert "BELOW entry" in result.reason


def test_rejects_target_below_entry(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", stop_price=94.0, take_profit_price=98.0)
    assert not result.approved
    assert "ABOVE entry" in result.reason


def test_rejects_stop_tighter_than_3pct(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", stop_price=99.0, take_profit_price=112.0)
    assert not result.approved
    assert "too tight" in result.reason


def test_rejects_stop_wider_than_15pct(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", stop_price=80.0, take_profit_price=140.0)
    assert not result.approved
    assert "too wide" in result.reason


def test_rejects_reward_risk_below_1_5(tmp_path):
    # 6% stop, 6% target → R:R 1.0
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", stop_price=94.0, take_profit_price=106.0)
    assert not result.approved
    assert "reward:risk" in result.reason


# ─── The happy path: a textbook order passes everything ──────────────────────

def test_approves_valid_order(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(ask=100.0))
    result = risk.check_order("SPY", 5, "buy", GOOD_STOP, GOOD_TARGET)
    assert result.approved
    assert result.reason == "approved"


def test_approves_valid_sell_of_owned_shares(tmp_path):
    risk = make_risk(tmp_path, FakeBroker(positions=[{"symbol": "SPY", "qty": 10.0}]))
    result = risk.check_order("SPY", 5, "sell")
    assert result.approved, result.reason
