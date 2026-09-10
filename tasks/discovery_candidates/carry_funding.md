# Strategy Candidate: carry_funding

strategy_id: carry_funding
version: 0.1
family: carry_funding

economic_rationale: |
  Capture funding-rate carry opportunities in futures/perp vs funding costs,
  harvesting predictable funding differentials when costs offset expected
  carrying costs and slippage.

assets: [BTCUSDT, ETHUSDT]
timeframe: [1h, 4h]
direction_policy: long_only|short_only|both  # specify

required_market_data: funding_rates, perp_mark_price, index_price, candles

signal_definition: explicit formula and threshold (fingerprint to be filled)

invalidation: funding_rate_reversal; spread widening > X; missing funding data

entry: next-bar open after signal
exit: funding convergence or stop_loss/take_profit

cost_model: canonical ExecutionCostModel (document SHA256)

regime_hypothesis: works during stable funding regimes, thin volatility

expected_failure_regimes: shocks, funding spikes, sudden liquidity loss

minimum_sample: 90 independent opportunities

acceptance_criteria: net expectancy > 0; PF > 1.2; p(Sharpe>0)>0.5; no large cost sensitivity

data_window: 12 months PIT data; dataset fp: TBD

dataset_fingerprint: TBD

config_sha256: TBD
