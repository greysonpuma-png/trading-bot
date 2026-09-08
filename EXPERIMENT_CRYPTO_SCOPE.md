# Exp6 scoping — crypto framework

_Scoping document, 2026-09-08. Nothing is built or pre-registered yet; this
exists to make the design decisions explicit before any code is written.
Probes below were run against the live Alpaca API, not assumed._

## Why crypto, specifically

Not because crypto is exciting — because **the equity dataset is spent.** Six
configurations across three frameworks have now been evaluated on the same 39
symbols of Alpaca daily bars, plus a live forward test. Every further backtest on
that data is curve-fitting by another name; the Donchian precedent (train −0.61%
→ holdout −16.88%) is what that looks like in practice.

Crypto is the cheapest source of **genuinely untouched data** reachable from the
existing infrastructure. It is a real holdout by construction. The secondary
argument — that crypto is less efficient than US large caps — was much truer in
2019 than it is in 2026 and should not be leaned on.

## What the probes found

**Universe.** 73 tradable crypto assets on Alpaca, 36 of them USD pairs.

**History is uneven and this constrains the universe.** Daily bars start
2021-01-01 at the earliest:

| Pairs | Bars | Usable? |
|---|---|---|
| BTC, ETH, LINK, UNI, DOGE, BCH, LTC | 2,077 (full 2021-01 →) | Yes |
| AAVE (1,882), AVAX (1,756), SOL (1,659) | partial 2021 | Yes, with a later start |
| DOT (1,118), PAXG (1,106), XRP (982) | ~3 years | Marginal |
| ADA (208), FIL (205) | <1 year | No |

**Volatility runs 44–96% annualized** (BTC 44%, ETH 64%, SOL 67%, UNI 96%)
against SPY's ~15–18%. That is 3–5× and it changes what "beat the benchmark"
should even mean — see *Benchmark* below.

**Liquidity is a flag.** Median daily dollar volume on Alpaca's own venue reads
~$95K for BTC and under $10K for most alts. Whether that reflects Alpaca's book
or a units convention in the `volume` field needs confirming, but either way
paper fills will be more optimistic than a thin book would deliver. Records as a
known distortion of any paper result.

**PAXG reports 172% annualized volatility.** It is a gold-backed token and should
sit near 15%. That is a data-quality problem, not a market fact — exclude it, and
treat it as a reminder to sanity-check the feed rather than trust it.

## The blocker: crypto has no broker-side exit protection

**Alpaca crypto supports market, limit, and stop-limit orders only. No trailing
stops. No bracket orders.**

This is the load-bearing constraint of the entire project. Since day one the
safety guarantee has been that every position's exit lives at the broker and
survives the bot process, the host, or the model provider dying. Neither exit
style currently implemented is available for crypto.

What is still possible, in descending order of safety:

1. **Static stop-limit at entry.** Survives bot death. Does not ratchet up, so it
   locks in a floor but never protects gains.
2. **Bot-ratcheted stop-limit.** Place a stop-limit at entry, then cancel-and-replace
   it higher on each cycle as price rises — a trailing stop emulated in software.
   Degrades gracefully: if the bot dies, the last stop it set remains standing.
   This is the recommended design.
3. **Bot-managed exits with no standing order.** Rejected. This re-introduces
   exactly the failure mode fixed on 2026-09-08 and offers no protection during an
   outage.

**Residual risk that cannot be engineered away:** a stop-*limit* can be skipped
entirely in a fast gap — price trades through the limit and no fill occurs. Crypto
gaps harder than equities and does so at 3am. A stop-*market* would solve this and
is not offered. Any crypto result carries this exposure, and it is materially worse
than the equities setup.

## What ports and what breaks

| Component | Status |
|---|---|
| `agent.py`, 3-stage pipeline | **Ports.** Venue-agnostic. |
| `screener.py` indicators | **Ports.** SMA/RSI/MACD math is asset-agnostic. |
| `risk_layer.py` checks 1, 2, 4, 5, 6, 7, 8 | **Port.** Whitelist, qty sanity, daily loss, position cap, max positions, no-shorting, buying power. |
| Check 3 — `market_hours_only` | **Breaks.** Crypto is 24/7; `is_market_open()` returns False outside equity hours and would block every order. Needs a crypto branch. |
| Check 9 — sector concentration | **Breaks.** No sector map for crypto. Needs a replacement concentration model — correlation-based, or simply a cap on non-BTC/ETH exposure, since alts are near-perfectly correlated in drawdowns. |
| Check 10 — exit protection | **Rewritten.** Validates a stop-limit distance instead of a trail percent. |
| Fractional quantities | **Breaks.** BTC at ~$78K against a $7,500 position cap means every order is fractional. `qty` is typed `int` throughout `propose_trade` and the risk layer; `max_order_qty` (200) becomes meaningless. |
| `broker.py` | **Extended.** Crypto uses `CryptoHistoricalDataClient` and different order requests. |

## Design decisions that need your call

**1. Benchmark.** In equities this was SPY buy-and-hold and the question was clean.
Crypto is harder, and the choice determines what "profitable" means:
- *Equal-weight buy-and-hold of the same universe* — the honest primary. Answers
  "does the strategy add anything over just owning these?"
- *BTC buy-and-hold* — brutal secondary reference. BTC has beaten nearly everything.
- Recommendation: **primary = equal-weight universe, and judge risk-adjusted first.**
  At 3–5× SPY's volatility, raw return comparisons are dominated by beta. A strategy
  capturing 70% of the return at 40% of the volatility is genuinely valuable and a
  raw-alpha lens would call it a failure.

**2. Cadence and cost.** Crypto trades 24/7. At the current hourly cycle that is
~24 cycles/day against ~7 today — roughly 3.4× the model spend, taking all-in cost
from ~$6.83 to ~$14/month. A 3-hourly cycle keeps it near current cost and still
suits a multi-day swing horizon. Recommendation: **3-hourly.**

**3. Universe size.** Recommend the 7 full-history pairs (BTC, ETH, LINK, UNI,
DOGE, BCH, LTC) plus SOL, AVAX, AAVE with a mid-2021 start — 10 pairs. Small enough
to screen cheaply, large enough for cross-sectional selection.

## Proposed pre-registration (not yet committed)

Matching the established convention exactly — 1-year windows, train for hypothesis
development, holdout touched **once**:

- **Train:** 2021-01→2022-01, 2022-01→2023-01, 2023-01→2024-01
  (captures the 2021 bull, the 2022 bear, and the 2023 recovery)
- **Holdout:** 2024-01→2025-01, 2025-01→2026-01 — untouched until a candidate is final

**Hypothesis to test first:** cross-sectional momentum. Rank the universe by
trailing N-day return, hold the top K, rebalance on a fixed schedule. This is
structurally different from every framework tested so far — the three equity
frameworks were time-series signals asking "is this symbol a buy?"; this asks
"which of these is strongest right now?" Momentum has historically been more
persistent in crypto than in large-cap equities. Sector rotation was a distant
cousin and failed, which is honest evidence against, though it was applied to 11
highly-correlated sector ETFs rather than a genuinely dispersed universe.

**Decision rule, to be fixed before the first backtest runs:** a candidate advances
to holdout only if it beats equal-weight buy-and-hold on train **risk-adjusted**
(Sharpe) in at least 2 of 3 windows. Holdout is evaluated once. If holdout fails,
the framework is refuted and the result is recorded — same as the previous three.

## Honest prior

Three frameworks and one live forward test have failed. Crypto momentum is among
the most heavily traded systematic strategies in existence and is not an
undiscovered corner. Fresh data raises the odds above "guaranteed curve-fit"; it
does not make them good. The value of running this is a clean answer and the
practice of getting one — the same thing the project has produced four times now.
