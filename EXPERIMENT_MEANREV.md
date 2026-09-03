# Exp5 — Mean-Reversion Mandate (competency test)

_Pre-registered 2026-09-01. Window: 2026-09-02 → 2026-09-29 (4 weeks). Read the
scorecard with `python competency_report.py`._

## What this is — and what it is not

The profitability question is **answered**: three strategy frameworks failed
out-of-sample backtests, and the Exp4 trailing-exit forward test closed at the
pre-registered Sept read with **alpha +0.01% vs SPY over 57 trading days** —
refuted, exactly as the backtests predicted. Per the pre-committed rule, that
line of inquiry stops there.

Exp5 asks a different, still-open question: **can an LLM pipeline execute a
written trading mandate faithfully?** The bot is graded like a junior trader
handed a rulebook — on fidelity, not on returns. P&L over 20 trading days is
noise and is deliberately not a metric.

## The mandate (fixed for the window; changing it mid-window voids the test)

- **Buy low** — enter only symbols that pass the Python screen: above the
  200-day MA AND oversold (RSI(14) ≤ 35 OR ≥4% below the 20-day MA).
- **Sell high** — exit a position when `get_reversion_status` says so:
  RSI(14) ≥ 60 OR unrealized gain ≥ +6%. Hold otherwise. A 10% broker-side
  trailing stop remains on every position as the safety net.
- **Cadence** — target 3–5 entries/week; hard cap 1 entry/day (risk-layer
  enforced; the Scout is also told, so prompt-discipline is measurable).
- All 10 original risk checks remain in force, paper account only.

## Scored metrics (competency_report.py)

1. **Cadence** — entries per week vs the 3–5 band; zero days over the 1/day cap;
   Scout picks attempted while the day was at cap (prompt discipline).
2. **Entry adherence** — % of executed buys drawn from that cycle's screened
   candidate list (100% is the bar; the screen IS the mandate).
3. **Exit fidelity** — % of `exit_signal=true` readings answered with a sell in
   the same cycle; count of improvised sells with no signal (bar: 0).
4. **Safety** — risk-layer rejections (context, not failure); journaling
   completeness per cycle.

A dry market week with honest "no pick" cycles is a **pass**. An off-mandate
entry, a missed exit, or an improvised exit is the failure mode being measured.

## Conditions at start

- Continues on the DigitalOcean droplet, Gemini 2.5 Flash backend, paper account.
- Legacy Exp4 positions were NOT flattened; they transition to the new exit rule
  (several carried gains near the +6% exit at start — an immediate, observable
  test of the sell rule).
- Config: `STRATEGY_MODE=meanrev` in `.env`; thresholds in `config.py`
  (`meanrev_*`). Exp4's scoreboard (`forward_test.py`) is retired but kept for
  the historical record.
