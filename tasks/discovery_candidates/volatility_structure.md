# Strategy Candidate: volatility_structure

strategy_id: volatility_structure
version: 0.1
family: volatility_structure

economic_rationale: |
  Utilize structural volatility changes (term-structure, realized vs implied)
  to trade variance and directional hedges sensitive to volatility regimes.

assets: [BTCUSDT, ETHUSDT]
timeframe: [1h, 4h]
direction_policy: both

required_market_data: realized_volatility, implied_volatility, options_synopsis, candles

signal_definition: structural shift detector (fingerprint to be filled)

invalidation: missing volatility surface data

entry: next-bar after signal
exit: regime reversion or stop/take

cost_model: canonical ExecutionCostModel

regime_hypothesis: effective when volatility term-structure is informative

expected_failure_regimes: sudden shocks, data-less regimes

minimum_sample: 80 independent regime events

acceptance_criteria: net expectancy positive, sensitivity to costs measured

data_window: 24 months PIT data

dataset_fingerprint: TBD

config_sha256: TBD
