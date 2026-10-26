# CAP-001 — AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE

A capability spike, not an alpha run. It builds the deterministic shell of the V3
paradigm (timestamped snapshot contract, immutable decision record, evaluator
primitives) without claiming edge, without trading and without releasing the freeze.

## What was built

- MarketSnapshot contract: 12 fields
- deterministic TradingView MCP payload -> snapshot adapter (read-only tools only)
- immutable decision record with a sealed hash and tamper detection
- evaluator primitives: incremental edge vs 4 baselines, hit rate, expectancy,
  profit factor, max drawdown, Brier calibration

## What was NOT done

- new strategy
- new signal
- new backtest
- parameter tuning
- broker integration
- paper run
- live order
- credentials
- research daemon
- scheduled alpha search
- create RFC-045
- edit ECONOMIC_STATE.json

## G_TV_CONTEXT

- status: NOT_VERIFIED
- reason: no TradingView account, subscription or OAuth authorization is available, so the snapshot is built from a synthetic fixture and cannot be certified as real
- blocking requirements:
  - TradingView Essential or above subscription
  - OAuth 2.1 authorization of the official MCP server in an LLM client
  - explicit user authorization to use the account for this experiment

## Snapshot (synthetic fixture)

| field | value |
| --- | --- |
| asset | BINANCE:BTCUSDT |
| timestamp | 1767225600 |
| multi_timeframe | 1h, 4h, 1D |
| market_regime | trend_up_low_volatility |
| freshness | FRESH |
| usable | True |
| evidence items | 6 |

## Immutable decision record

- llm_invoked: False
- illustrative record: True
- record verified: True
- hash changes when the decision is altered: True
- tampered indices detected: [0]

## Budget before G3

| limit | value |
| --- | --- |
| MAX_AI_AGENTS | 2 |
| MAX_TRADINGVIEW_CONNECTORS | 1 |
| MAX_SHADOW_ENGINES | 1 |
| MAX_EVALUATORS | 1 |

## Next step

Authorize a TradingView account so G_TV_CONTEXT can be evaluated against real data.
Until then the gate stays NOT_VERIFIED and no RFC is created.
