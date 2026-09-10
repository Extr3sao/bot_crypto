# Strategy Candidate: liquidity_flow

strategy_id: liquidity_flow
version: 0.1
family: liquidity_flow

economic_rationale: |
  Detect and ride liquidity flows (large market participant footprints,
  taker/initiated trade clusters) that transiently move price and create
  exploitable micro-trends.

assets: [BTCUSDT, ETHUSDT, SOLUSDT]
timeframe: [1m, 5m]
direction_policy: both

required_market_data: trade_ticks, orderbook_snapshots, public_liquidity_metrics

signal_definition: footprint detection / flow clustering

invalidation: delayed ticks, exchange outages

entry: next-bar or immediate micro-execution
exit: flow exhaustion or stop_loss/take_profit

cost_model: canonical ExecutionCostModel

regime_hypothesis: effective in low-to-moderate volatility with clear liquidity players

expected_failure_regimes: shocks, fragmented liquidity

minimum_sample: 150 events

acceptance_criteria: net expectancy > 0; robustness under slippage

data_window: 6-12 months PIT data

dataset_fingerprint: TBD

config_sha256: TBD
