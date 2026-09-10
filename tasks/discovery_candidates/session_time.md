# Strategy Candidate: session_time

strategy_id: session_time
version: 0.1
family: session_time

economic_rationale: |
  Exploit intra-day session-specific liquidity and volatility cycles (e.g.
  open/close, funding windows) to capture short-lived predictable moves.

assets: [BTCUSDT, ETHUSDT]
timeframe: [1m, 5m, 15m]
direction_policy: both

required_market_data: candles, trade_ticks, session_calendar

signal_definition: session-aware volatility/volume spike detector

invalidation: session holiday, missing ticks

entry: immediate next-tick/next-bar
exit: short holding period or stop_loss/take_profit

cost_model: canonical ExecutionCostModel

regime_hypothesis: works in regular session patterns; fails in global shocks

minimum_sample: 200 session opportunities

acceptance_criteria: frequency contribution, net expectancy > 0

data_window: 6 months PIT data

dataset_fingerprint: TBD

config_sha256: TBD
