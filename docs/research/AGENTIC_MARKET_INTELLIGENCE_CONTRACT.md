# AGENTIC MARKET INTELLIGENCE CONTRACT (CAP-001)

- spike: CAP-001 — AGENTIC MARKET INTELLIGENCE CAPABILITY SPIKE
- governance framing: CAPABILITY_SPIKE_OUTSIDE_ALPHA_FREEZE
- alpha research freeze: ACTIVE (unchanged by this spike)
- next alpha RFC allowed: NO (unchanged by this spike)
- alpha claimed: NONE

## MarketSnapshot contract

| field | meaning |
| --- | --- |
| timestamp | unix seconds UTC of the snapshot |
| asset | EXCHANGE:TICKER, e.g. BINANCE:BTCUSDT |
| price_state | last, change_pct, bar_interval, bar_count |
| multi_timeframe | one entry per interval (technicals are single-interval per call) |
| technical_state | RSI/MACD/ADX/momentum/SMA/EMA + Recommend aggregate |
| relative_strength | symbol vs reference |
| volume_state | last volume and its ratio to the trailing average |
| market_regime | analyst-supplied regime label (non-deterministic domain) |
| news | symbol headlines (title, published, provider, urgency) |
| macro_events | calendar events (name, country, when, importance, actual) |
| evidence | mechanically collected evidence items with their MCP source |
| data_freshness | snapshot_at, source timestamps, age_seconds, level, degraded |

## Authority

| subject | authority |
| --- | --- |
| tradingview | INTELLIGENCE_SOURCE |
| historical_bars | OUR_DATASETS |
| fills | BROKER_OR_EXCHANGE |
| pnl | PORTFOLIO_ACCOUNTING |

## Determinism split

Non-deterministic (the agent owns these):

- market_interpretation
- regime_interpretation
- opportunity_detection
- news_context_reasoning
- evidence_weighting
- trade_thesis
- no_trade_judgment
- confidence

Deterministic (never delegated to an LLM):

- max_risk
- max_exposure
- position_sizing
- capital_allocation_limits
- stop_constraints
- fees
- accounting
- pnl
- reconciliation
- execution_permissions

## Real MCP constraints

| constraint | detail |
| --- | --- |
| auth | OAuth 2.1 against a paid TradingView account (Essential or above); no API key |
| transport | streamable HTTP MCP, consumed by an LLM client (Claude / ChatGPT / Codex) |
| rate_limit | ~100 requests per minute per user |
| get_ohlcv_max_bars | 5000 |
| get_technicals_rating | single timeframe per call; multi_timeframe must be composed |
| run_screener_max_rows | 1000 |
| create_alert | simple price conditions only; multi-condition and indicator alerts rejected |
| webhooks | cannot be configured through MCP (2FA not available); set up on tradingview.com |

## Gate status

- G_TV_CONTEXT = NOT_VERIFIED
- every later gate = NOT_STARTED

## Snapshot produced in this spike

- source: SYNTHETIC_FIXTURE
- usable: True
- freshness: FRESH
- evidence items: 6
