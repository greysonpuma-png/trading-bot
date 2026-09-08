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

---

## RESULT — baseline (2026-09-08)

Params: lookback 90d, top 3, weekly rebalance, BTC>100d MA regime gate.

| Window | Return | Benchmark | Alpha | Sharpe | Bench Sharpe | ΔSharpe |
|---|---|---|---|---|---|---|
| 2021-04 → 2022-04 | +538.11% | +39.99% | +498.12% | +2.89 | +0.85 | **+2.04** |
| 2022-04 → 2023-04 | −43.59% | −56.15% | +12.56% | −1.17 | −0.54 | −0.62 |
| 2023-04 → 2024-04 | +108.06% | +171.75% | −63.68% | +1.52 | +2.10 | −0.59 |

**Sharpe: 1/3 windows. Rule required 2/3. FAILS — does not advance to holdout.**

Average raw alpha was **+149%** and 2/3 windows were positive on return. On a
raw-return lens this passes comfortably and advances. On the pre-registered
risk-adjusted lens it fails. Same data, opposite verdict — decided entirely by a
choice made before any number existed. Nearly all of the raw alpha comes from a
single window (2021 alt season, +498%); the other two windows have worse
risk-adjusted returns than simply holding the ten assets.

One genuine positive: drawdowns were materially better in 2 of 3 windows
(28.2% vs 62.2%, 47.1% vs 70.9%). The BTC regime gate is doing real work.

---

## PRE-REGISTRATION — Hypothesis 1 (written 2026-09-08, BEFORE running)

**The diagnostic.** Window 3 is the informative failure: the strategy returned
+108% against a +172% benchmark. If the momentum signal had any predictive
value, holding the strongest 3 should beat the average of all 10. It did not —
**the ranking performed worse than random.** That is the signature of reversal,
not continuation: assets with the strongest trailing 90-day returns
subsequently underperformed their peers.

**Hypothesis.** The 90-day lookback is too slow for crypto's cycle. It ranks on
moves that have already largely played out, so the strategy systematically buys
exhausted trends near their turning point. If momentum operates at a faster
horizon in this asset class, a **30-day lookback** should rank better and improve
risk-adjusted returns, with the largest improvement in window 3 where the slow
signal was most clearly anti-predictive.

**Single variable changed:** `--lookback 30`. Top-K, rebalance period, regime
gate, universe, and windows all unchanged.

**Refutation condition, fixed in advance:** the same bar as the baseline —
beat the equal-weight benchmark on Sharpe in **at least 2 of 3 train windows**.
Anything less refutes the hypothesis and the crypto framework is closed. A
result that improves raw alpha but not Sharpe does **not** count as support;
that is the exact confusion this benchmark was chosen to prevent.

**Budget:** this is comparison #2 on the train set. Regardless of outcome,
no further parameter search will be run on these windows — the
multiple-comparisons ratchet is what turned Donchian's train −0.61% into a
holdout −16.88%, and three or four more comparisons would put this framework in
the same position.

## RESULT — Hypothesis 1: REFUTED (2026-09-08)

Params: lookback **30d** (single variable changed), top 3, weekly, regime gate on.

| Window | Return | Benchmark | Alpha | Sharpe | Bench Sharpe | ΔSharpe |
|---|---|---|---|---|---|---|
| 2021-04 → 2022-04 | +266.76% | +39.99% | +226.76% | +1.99 | +0.85 | +1.14 |
| 2022-04 → 2023-04 | −42.28% | −56.15% | +13.86% | −0.86 | −0.54 | −0.31 |
| 2023-04 → 2024-04 | +88.54% | +171.75% | −83.20% | +1.35 | +2.10 | **−0.76** |

**Sharpe: 1/3 windows. Rule required 2/3. REFUTED.**

| | baseline (90d) | H1 (30d) |
|---|---|---|
| Sharpe wins | 1/3 | 1/3 |
| Avg ΔSharpe | +0.28 | **+0.02** |
| Window 3 ΔSharpe | −0.59 | **−0.76** |
| Avg raw alpha | +149% | +52% |

The refutation is unusually clean because the hypothesis was *directional*: it
predicted the largest improvement in window 3, where the slow signal appeared
anti-predictive. Window 3 got **worse**. Every headline metric moved the wrong
way. There is no reading of this that supports the claim.

**What it rules out.** Shortening the ranking horizon does not recover the
signal. If anything the comparison hints the opposite — the 90-day baseline had
the better average ΔSharpe — but chasing that would be comparison #3, which the
pre-registration explicitly ruled out. **Budget honored: no further parameter
search on these windows.** Holdout (2024-04→2026-04) remains untouched and can
still validate some future, genuinely different framework.

## STATUS: Exp6 CLOSED — crypto cross-sectional momentum refuted

Fourth backtested framework to fail out-of-sample discipline, and the fifth
negative result overall counting the live forward test. The equity data was
spent; the crypto data was fresh, and the answer came back the same.

---

## Honest prior

Three frameworks and one live forward test have failed. Crypto momentum is among
the most heavily traded systematic strategies in existence and is not an
undiscovered corner. Fresh data raises the odds above "guaranteed curve-fit"; it
does not make them good. The value of running this is a clean answer and the
practice of getting one — the same thing the project has produced four times now.
