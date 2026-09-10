# Strategy Candidate: cross_sectional

strategy_id: cross_sectional
version: 0.1
family: cross_sectional

economic_rationale: |
  Exploit relative mispricings across correlated assets using a market-neutral
  stat-arb like approach conditioned on short-term mean reversion across the
  basket.

assets: [BTCUSDT, ETHUSDT, SOLUSDT]
timeframe: [5m, 1h]
direction_policy: market_neutral

required_market_data: candles, orderbook_snapshots, funding_rates

signal_definition: zscore spread across basket (fingerprint to be filled)

invalidation: structural correlation break, missing orderbook data

entry: next-bar execution
exit: zscore reversion or stop_loss/take_profit

cost_model: canonical ExecutionCostModel

regime_hypothesis: works during normal correlation regimes; fails during shocks

minimum_sample: 100 pairs/trades

acceptance_criteria: net positive expectancy, PF>1.1, statistical significance

data_window: 12 months PIT data

dataset_fingerprint: TBD

config_sha256: TBD
