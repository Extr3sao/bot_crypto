# Strategy Candidate: regime_transition_defense

strategy_id: regime_transition_defense
version: 0.1
family: regime_transition_defense

economic_rationale: |
  Offer defensive exposures that protect portfolio during regime transitions
  (trend reversal, correlation fusion, shocks) by entering hedging/defensive
  positions conditioned on regime-detection signals.

assets: [BTCUSDT, ETHUSDT]
timeframe: [1h, 4h]
direction_policy: defensive/hedge

required_market_data: candles, correlation_matrix, volatility, stress_indicators

signal_definition: regime transition detector (fingerprint to be filled)

invalidation: delayed correlation data, false-positive regime flips

entry: hedging trades on detected transitions
exit: regime stabilization or stop/take

cost_model: canonical ExecutionCostModel

regime_hypothesis: activates during transitional regimes (FUSED_CORRELATION, TRANSITION, RANGE)

expected_failure_regimes: prolonged trending markets without transitions

minimum_sample: 60 regime events

acceptance_criteria: reduces drawdown during transitions; positive expectancy when conditioned

data_window: 24 months PIT data

dataset_fingerprint: TBD

config_sha256: TBD
