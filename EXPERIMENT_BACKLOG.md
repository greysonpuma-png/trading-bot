# Experiment backlog — ideas parked until the forward-test read (~Sept 3, 2026)

Rules of this file (the whole point):
- Nothing here touches the live bot before the September forward-test read.
- Each idea gets a written hypothesis BEFORE any code, and one shot at
  validation. No peeking, no iterating on the result.
- Backtest holdout windows are SPENT for both tested frameworks. New ideas
  can only be validated on forward data (A/B or sequential forward tests) —
  which is slow. That's the price of the earlier experiments; budget for it.
- Prior probability check: three frameworks and several exit/entry variants
  all failed out-of-sample. Any new idea should say why it's different in
  kind, not just plausible-sounding. "More information for the LLM" is not
  an edge thesis — the LLM mostly ratifies the screener's pick; returns come
  from the mechanical rules (screen, size, exit).

---

## Candidate: earnings-date filter (risk hygiene, not alpha)
**Idea:** skip new entries within N days of the stock's earnings date;
Position Manager flags positions with earnings inside the stop horizon.
**Why it might be different in kind:** it doesn't claim edge — it removes a
known binary-gap risk that trailing stops can't protect against (gaps blow
through stops). Judged on drawdown/variance, not alpha.
**Cost/effort:** needs an earnings-calendar data source (Alpaca doesn't
provide one; free options are flaky). Medium.

## Candidate: fix Position Manager iteration budget (execution quality)
**Known issue:** with 8 positions, the PM stage regularly hits its 12-LLM-
iteration cap, so later positions get reviewed shallowly or not at all
(observed "hit max iterations" 10+ times in logs, 2026-07-08).
**Classification:** bug fix, not strategy — but it still changes live
behavior, so it waits for Sept and gets its own regime note when applied.
**Sketch:** batch positions (review 3-4 per sub-call) or raise max_iters
for the PM stage only.

## Candidate: 13F "whale overlap" tilt
**Idea:** Scout sees which whitelist symbols top 13F filers added/hold
(see `whale_watch/`).
**Honest prior: weak.** 13F data is 45-135 days stale from 5-30yr-horizon
investors; academic cloning results only work as multi-year buy-and-hold.
Wrong timeframe for a swing bot. Parked here mostly so it's not re-litigated
from scratch each time it comes up.

## Candidate: news-sentiment gate
**Idea:** score get_news() headlines (positive/negative) and block entries on
net-negative sentiment.
**Honest prior: weak-to-medium.** Headline sentiment is one of the most
arbitraged signals in existence; retail-grade scoring of free headlines is
noise-prone. Would need a pre-registered forward A/B to claim anything.

## Candidate: relative-strength ranking among screener candidates
**Idea:** when the screener returns multiple candidates, rank by 3-month
relative strength vs SPY instead of letting the LLM choose.
**Honest prior: medium.** Momentum ranking has real academic support, BUT
framework #3 (sector rotation = momentum ranking on ETFs) was our worst
train result. This variant differs (stock-level, within already-screened
setups). Cheap to implement; still needs forward validation.

---

Add new ideas below with the same format: idea, why different in kind,
honest prior, cost. Resist the urge to implement anything early — the
September read is worth more than any of these.
