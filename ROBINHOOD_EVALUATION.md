# Robinhood Agentic Trading — architectural evaluation

_September 2026. Evaluation only; no capital was deployed and no adapter has been
built. Companion to `EXPERIMENT_MEANREV.md`._

## Summary

Robinhood [opened its platform to third-party AI agents in May 2026](https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/),
exposing a hosted MCP server at `agent.robinhood.com/mcp/trading` and a dedicated
agentic account isolated from the user's primary portfolio.

**Finding: the migration is architecturally cheap and financially unjustified.**
Porting this bot would touch exactly one file. But Robinhood has no paper trading,
so connecting to it means real capital — and this bot's strategy returned
**+0.01% alpha over 57 trading days** and was refuted under its own pre-registered
rule on 2026-09-01. Building the adapter is worthwhile as an engineering exercise;
funding the account is not.

## What would port

| Component | Verdict |
|---|---|
| `risk_layer.py` | **Unchanged.** All 10 checks are broker-agnostic — they operate on symbols, quantities, and dollar values. Nothing in the file knows what a broker is. |
| `agent.py`, `screener.py`, `tools.py` | **Unchanged.** The pipeline talks to a `Broker` object, never to an API. Mandate, prompts, and screening are venue-independent. |
| `broker.py` | **Rewritten as an MCP client.** This is the whole migration: one adapter implementing the same nine methods against MCP tool calls instead of the Alpaca SDK. |
| Test suite | **Mostly ports.** 57 tests, most using `FakeBroker` with no network. The Alpaca-specific sell-path tests need Robinhood equivalents. |

The separation between `broker.py` and everything above it means a venue change is
a single-adapter change. That was an early design decision and it holds up under a
migration it was never planned for.

## Open questions that must be answered before any adapter work

1. **Server-side trailing stops — load-bearing.** Every position's safety depends on
   a broker-side stop that survives the bot process dying. Robinhood's published agent
   docs do not confirm server-side trailing stop support. If absent, exits would live
   only in the bot, and the entire safety model collapses. This is a hard blocker, not
   a detail.
2. **Market data depth.** The screener needs 200 days of daily bars across 39 symbols.
   Alpaca supplies this. Whether the Robinhood MCP exposes equivalent history — or
   whether data would stay on Alpaca while execution moves — is undocumented.
3. **Order-type coverage.** The mandate needs market orders plus trailing stops, and
   the sell path needs order cancellation (see the 2026-09-08 fix, where shares held
   by their own protective stop blocked every sell).

## Why no capital

Robinhood has **no paper trading mode**. The "sandbox" framing in its agentic product
refers to a permissions boundary — an account the agent cannot reach past — not
simulated money.

Against the pre-committed bar for real money, written before any of this was built:

| Criterion | Status |
|---|---|
| 6+ months positive forward alpha vs SPY | **Failed** — +0.01% at the Sept 1 read, refuted |
| Validated out-of-sample | **Failed** — three frameworks failed walk-forward holdout |
| Loss budget affordable to lose entirely | Not established |
| Written stop rule agreed before funding | Not written |

Additional frictions: real fills add spread and slippage, which turn a zero-edge
strategy slightly negative; and under $25,000 the pattern-day-trader rule caps
activity at three day trades per five business days.

## Operating cost context

Current all-in cost is **~$6.83/month** ($4.00 droplet + ~$2.83 Gemini 2.5 Flash),
measured from production logs: 88 model round-trips per trading day, ~7.1M input and
~280K output tokens per month. Input tokens are 96% of model spend because each agent
loop iteration resends the full conversation. The Position Manager accounts for 59% of
calls, pulling bars and news for every open position each cycle — so cost scales with
positions held rather than trades made.

Migrating execution to Robinhood would not change this materially; the model and host
costs dominate and both are venue-independent.
