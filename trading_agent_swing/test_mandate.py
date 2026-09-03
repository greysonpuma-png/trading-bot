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
