# EXP-ARP-007 — DECISION

- strategy: `STRAT-CAND-019-VARIANT-B`
- arm: `PROJECT_DERIVED_VARIANT` — source attribution NONE
- NOT a source-faithful test of STRAT-CAND-019 (BLOCKED_NEEDS_SPEC).
- params: `{"atr_period": 14, "max_hold_days": 3, "stop_atr": 1.0}`

## Stage results

- DEV: **PASS**
- COST: **REJECT_COSTS**
- VALIDATION: **NOT_REACHED**
- ROBUSTNESS: **NOT_REACHED**

## FINAL: **REJECT_COSTS**

OOS opened: `False`

## DEV metrics (combined)

- trades: 153
- gross expectancy: 0.776 bps
- cost: 23.559 bps · net expectancy: -22.783 bps
- win rate: 0.5163 · profit factor: 0.8137
- max drawdown: 5335.504 bps
- top1 positive-net share: 0.039
- capture ratio (captured/available): 0.0039

## COST_MODEL_V3 stress (DEV)

- 0.5x: net -11.004 bps (gross 0.776)
- 1.0x: net -22.783 bps (gross 0.776)
- 1.25x: net -28.673 bps (gross 0.776)
- 1.5x: net -34.563 bps (gross 0.776)
- 2.0x: net -46.342 bps (gross 0.776)
