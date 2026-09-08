"""
Exp5 mean-reversion mandate tests: the entry screen predicate, the exit-signal
predicate, and the risk layer's 1-entry-per-day cadence cap. No network.
Run: python -m pytest test_mandate.py
"""
import json

import pytest

from config import CONFIG
from risk_layer import RiskLayer
from screener import meanrev_entry_setup
from tools import reversion_exit_signal
from test_risk_layer import FakeBroker


@pytest.fixture
def meanrev_mode():
    """Flip CONFIG into meanrev mode for one test, then restore."""
    prev = CONFIG.strategy_mode
    CONFIG.strategy_mode = "meanrev"
    yield
    CONFIG.strategy_mode = prev


def _risk_with_proposals(tmp_path, broker, proposal_rows):
    risk = RiskLayer(broker)
    risk.daily_pnl_file = str(tmp_path / "daily_pnl.json")
    risk.proposals_file = str(tmp_path / "proposals.jsonl")
    with open(risk.proposals_file, "w") as f:
        for row in proposal_rows:
            f.write(json.dumps(row) + "\n")
    return risk


def _executed_buy(ts):
    return {"update": {"timestamp": ts, "symbol": "SPY", "side": "buy",
                       "qty": 1, "executed": True, "status": "executed"}}


# ── entry predicate ──────────────────────────────────────────────────────────

def test_entry_requires_long_term_uptrend():
    ok, why = meanrev_entry_setup(price=90.0, ma_long=100.0, rsi=20.0, pct_above_fast=-8.0)
    assert not ok and "200-day" in why


def test_entry_oversold_by_rsi():
    ok, why = meanrev_entry_setup(price=110.0, ma_long=100.0,
                                  rsi=CONFIG.meanrev_rsi_entry, pct_above_fast=0.0)
    assert ok and "RSI" in why


def test_entry_oversold_by_dip():
    ok, why = meanrev_entry_setup(price=110.0, ma_long=100.0, rsi=50.0,
                                  pct_above_fast=CONFIG.meanrev_dip_entry_pct)
    assert ok and "20MA" in why


def test_entry_rejects_not_oversold():
    ok, _ = meanrev_entry_setup(price=110.0, ma_long=100.0, rsi=50.0, pct_above_fast=1.0)
    assert not ok


# ── exit predicate ───────────────────────────────────────────────────────────

def test_exit_on_rsi():
    sig, why = reversion_exit_signal(rsi=CONFIG.meanrev_rsi_exit, gain_pct=0.0)
    assert sig and "RSI" in why


def test_exit_on_gain():
    sig, why = reversion_exit_signal(rsi=50.0, gain_pct=CONFIG.meanrev_gain_exit_pct)
    assert sig and "gain" in why


def test_no_exit_when_neither_target_hit():
    sig, _ = reversion_exit_signal(rsi=50.0, gain_pct=1.0)
    assert not sig


def test_no_exit_with_missing_rsi_and_loss():
    sig, _ = reversion_exit_signal(rsi=None, gain_pct=-3.0)
    assert not sig


# ── exit-rule attribution (feeds exit_analysis.py) ───────────────────────────

def test_classify_gain_only():
    from tools import classify_exit_rule
    assert classify_exit_rule(rsi=50.0, gain_pct=CONFIG.meanrev_gain_exit_pct) == "gain"


def test_classify_rsi_only():
    from tools import classify_exit_rule
    assert classify_exit_rule(rsi=CONFIG.meanrev_rsi_exit, gain_pct=0.0) == "rsi"


def test_classify_both():
    from tools import classify_exit_rule
    assert classify_exit_rule(rsi=CONFIG.meanrev_rsi_exit,
                              gain_pct=CONFIG.meanrev_gain_exit_pct) == "both"


def test_classify_none_when_no_signal():
    from tools import classify_exit_rule
    assert classify_exit_rule(rsi=50.0, gain_pct=1.0) is None


def test_classification_agrees_with_the_mandate():
    """Attribution must never disagree with the rule that actually governs
    trading — a classified exit implies a signal, and vice versa."""
    from tools import classify_exit_rule, reversion_exit_signal
    for rsi in (None, 20.0, 59.9, 60.0, 80.0):
        for gain in (None, -5.0, 5.9, 6.0, 20.0):
            signal, _ = reversion_exit_signal(rsi, gain)
            assert signal == (classify_exit_rule(rsi, gain) is not None), (rsi, gain)


# ── cadence cap (risk layer) ─────────────────────────────────────────────────

def test_cadence_blocks_second_buy_of_day(tmp_path, meanrev_mode):
    from datetime import datetime
    risk = _risk_with_proposals(tmp_path, FakeBroker(),
                                [_executed_buy(datetime.now().isoformat())])
    res = risk.check_order("SPY", 1, "buy")
    assert not res.approved
    assert "per day" in res.reason


def test_cadence_allows_first_buy_of_day(tmp_path, meanrev_mode):
    risk = _risk_with_proposals(tmp_path, FakeBroker(),
                                [_executed_buy("2020-01-01T10:00:00")])  # old entry
    res = risk.check_order("SPY", 1, "buy",
                           stop_price=94.0, take_profit_price=112.0)
    assert res.approved, res.reason


def test_cadence_never_blocks_sells(tmp_path, meanrev_mode):
    from datetime import datetime
    broker = FakeBroker(positions=[{"symbol": "SPY", "qty": 10, "market_value": 1000.0,
                                    "unrealized_plpc": 0.0}])
    risk = _risk_with_proposals(tmp_path, broker,
                                [_executed_buy(datetime.now().isoformat())])
    res = risk.check_order("SPY", 5, "sell")
    assert res.approved, res.reason


# ── sells must reclaim shares locked by protective stops ─────────────────────

class _FakeOrder:
    def __init__(self, symbol, side, oid, status="OrderStatus.NEW"):
        self.symbol, self.side, self.id, self.status = symbol, side, oid, status


class _FakeTrading:
    """Minimal stand-in for alpaca-py's TradingClient covering the sell path."""
    def __init__(self, orders):
        self.orders = list(orders)
        self.cancelled = []
        self.submitted = []

    def get_orders(self):
        return list(self.orders)

    def cancel_order_by_id(self, oid):
        self.cancelled.append(oid)
        self.orders = [o for o in self.orders if o.id != oid]

    def get_all_positions(self):
        return []          # position gone -> release loop exits immediately

    def submit_order(self, req):
        self.submitted.append(req)
        from types import SimpleNamespace
        return SimpleNamespace(id="new-order", symbol=req.symbol, qty=req.qty,
                               side=req.side, status=type("S", (), {"value": "accepted"})(),
                               submitted_at=None)


def _broker_with(trading):
    from broker import Broker
    b = Broker.__new__(Broker)      # skip __init__ (no network/credentials)
    b.trading = trading
    return b


def test_sell_cancels_protective_stop_first():
    """The 2026-09-08 bug: shares held by a trailing stop made every sell fail
    with 'insufficient qty available'. A sell must cancel that stop first."""
    from alpaca.trading.enums import OrderSide
    trading = _FakeTrading([_FakeOrder("JNJ", OrderSide.SELL, "stop-1"),
                            _FakeOrder("XLV", OrderSide.SELL, "stop-2")])
    b = _broker_with(trading)
    b.submit_order("JNJ", 50, "sell")
    assert trading.cancelled == ["stop-1"], "must cancel JNJ's stop, and only JNJ's"
    assert len(trading.submitted) == 1, "the market sell must still be submitted"


def test_buy_does_not_cancel_anything():
    from alpaca.trading.enums import OrderSide
    trading = _FakeTrading([_FakeOrder("JNJ", OrderSide.SELL, "stop-1")])
    b = _broker_with(trading)
    b.submit_order("JNJ", 5, "buy")
    assert trading.cancelled == [], "a buy must never cancel protective orders"


def test_sell_with_no_open_orders_still_submits():
    trading = _FakeTrading([])
    b = _broker_with(trading)
    b.submit_order("JNJ", 50, "sell")
    assert trading.cancelled == [] and len(trading.submitted) == 1


def test_cadence_ignored_in_pullback_mode(tmp_path):
    """In pullback mode the daily-entry cap must not apply — regardless of what
    STRATEGY_MODE the ambient .env sets, so force it for this test."""
    from datetime import datetime
    prev = CONFIG.strategy_mode
    CONFIG.strategy_mode = "pullback"
    try:
        risk = _risk_with_proposals(tmp_path, FakeBroker(),
                                    [_executed_buy(datetime.now().isoformat())])
        res = risk.check_order("SPY", 1, "buy",
                               stop_price=94.0, take_profit_price=112.0)
        assert res.approved, res.reason
    finally:
        CONFIG.strategy_mode = prev
