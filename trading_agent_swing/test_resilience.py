"""
Tests for the anti-hang protections (added 2026-06-23 after a 3rd silent hang).

Two independent layers:
  1. main.py SIGALRM cycle watchdog — a hard per-cycle deadline that interrupts
     ANY hang (network, file I/O, sleep-wedged socket) and lets the loop recover.
  2. broker._force_session_timeout — injects a per-request timeout into alpaca-py's
     requests Session, which otherwise has none and blocks forever.

Run with:  python -m pytest test_resilience.py -v
"""
import signal
import time

import pytest

import main


# ─── Layer 1: SIGALRM cycle watchdog ─────────────────────────────────────────

def test_sigalrm_interrupts_a_hang():
    """A cycle that blocks past the deadline must raise CycleTimeout, not hang."""
    main_timeout = main.CYCLE_TIMEOUT_SECONDS
    main.CYCLE_TIMEOUT_SECONDS = 1
    signal.signal(signal.SIGALRM, main._on_cycle_alarm)
    try:
        signal.alarm(main.CYCLE_TIMEOUT_SECONDS)
        start = time.monotonic()
        with pytest.raises(main.CycleTimeout):
            time.sleep(30)                       # simulate a wedged call
        elapsed = time.monotonic() - start
        assert elapsed < 5, "alarm should fire in ~1s, not let the sleep run"
    finally:
        signal.alarm(0)
        main.CYCLE_TIMEOUT_SECONDS = main_timeout


def test_alarm_disarms_cleanly():
    """signal.alarm(0) must cancel a pending alarm so a fast cycle isn't killed late."""
    signal.signal(signal.SIGALRM, main._on_cycle_alarm)
    signal.alarm(2)
    signal.alarm(0)          # disarm immediately, as the loop's finally: does
    time.sleep(2.5)          # if the alarm were still armed this would raise
    # reaching here without CycleTimeout means disarm worked
    assert True


# ─── Layer 2: per-request timeout injection ──────────────────────────────────

def test_force_session_timeout_injects_default():
    """A wrapped session must add a timeout when the caller omits one."""
    from broker import _force_session_timeout, ALPACA_REQUEST_TIMEOUT

    class FakeSession:
        def __init__(self):
            self.last_kwargs = None
        def request(self, *args, **kwargs):
            self.last_kwargs = kwargs
            return "ok"

    s = FakeSession()
    _force_session_timeout(s)
    s.request("GET", "http://example.com")
    assert s.last_kwargs["timeout"] == (ALPACA_REQUEST_TIMEOUT, ALPACA_REQUEST_TIMEOUT)


def test_force_session_timeout_respects_explicit():
    """If a caller passes its own timeout, the wrapper must not override it."""
    from broker import _force_session_timeout

    class FakeSession:
        def __init__(self):
            self.last_kwargs = None
        def request(self, *args, **kwargs):
            self.last_kwargs = kwargs
            return "ok"

    s = FakeSession()
    _force_session_timeout(s)
    s.request("GET", "http://example.com", timeout=5)
    assert s.last_kwargs["timeout"] == 5


# ─── Intra-cycle cache (efficiency, must stay behavior-neutral) ──────────────

def test_cycle_cache_dedups_identical_calls():
    """Identical cached-tool calls within a cycle hit the underlying source once."""
    import tools

    hits = {"n": 0}

    @tools._cycle_cached
    def fake_fetch(symbol):
        hits["n"] += 1
        return {"symbol": symbol}

    tools.clear_cycle_cache()
    fake_fetch("SPY"); fake_fetch("SPY"); fake_fetch("SPY")
    assert hits["n"] == 1, "3 identical calls should fetch once"
    fake_fetch("AAPL")
    assert hits["n"] == 2, "a different arg should fetch again"


def test_cycle_cache_clears_between_cycles():
    """clear_cycle_cache() must force a fresh fetch — no stale data across cycles."""
    import tools

    hits = {"n": 0}

    @tools._cycle_cached
    def fake_fetch(symbol):
        hits["n"] += 1
        return {"symbol": symbol}

    tools.clear_cycle_cache()
    fake_fetch("SPY")
    tools.clear_cycle_cache()
    fake_fetch("SPY")
    assert hits["n"] == 2, "after clear, the same call must fetch again"
