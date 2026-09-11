# H6 FAILED-MEMORY COLLISION REVIEW — OI-FULL-HISTORY-FREEZE-01 (Track L)

Computed **after** dataset freeze (`OI_FULL_HISTORY_DATASET_SHA256 = 16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`) and **before** any performance inspection. Register read in full: `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (12 terminal entries).

## Candidate 1 — M-B: OI position-stock dynamics

| Field | Assessment |
| --- | --- |
| MECHANISM | Position-stock (open interest) expansion/contraction conditioning of 1h decisions: trade only when price movement is/ is not accompanied by OI participation, per classic OI-price quadrants |
| NEW_INFORMATION_USED | `sum_open_interest` / `sum_open_interest_value` (5m) — **absent from every failed experiment's information set** (all 12 failures are price/volume/funding/flow-derived; none read OI) |
| FAILED_FAMILY_COLLISION | **Low.** H1 (#10): transition *labels* on 1h OHLCV — different variable and family; H3 (#11): BTC↔ETH spread reversion — different mechanism and asset pair; H5 (#12): 1h order-flow *aggregates* (OHLCV-family taker fields) — closest analogue, but trade-flow quantity vs position-stock quantity are distinct market variables; momentum/trend/breakout/MR/carry (#1–#9): different variables entirely |
| WHY_DISTINCT | OI is a **stock** of outstanding contracts; every failed family conditions on *flows* (price change, volume, funding basis, taker imbalance) or derived *states*. Conditioning direction on participation stock is a new information axis for this program |
| WHY_NOT_PARAMETER_RETRY | No prior OI experiment exists to re-parameterize; the conditioning variable itself is new (not a re-rolling of H5's z-threshold or H1's labels); follow-up uses PIT rolling distributions, not hand-tuned constants |
| EXPECTED_COST_PROFILE | Favourable **by design**: hourly decisions, OI-conditioned (expected coarser than ~6.5 qualifying transitions/day of H1); prereg requires min-hours-between-decisions and a gross-edge ≥ cost-hurdle statement |
| EXPECTED_FREQUENCY | Moderate (OI quadrant conditions persist for hours–days); target event count sized by prereg `minimum_N` with per-hour independence caps |
| PIT_FEASIBILITY | High — OI is observation-time data (`data_time <= decision_time` enforced by frozen dataset helpers); daily exclusion via validity ledger uses same-day information only |

## Candidate 2 — DEFERRED: event-level trade-flow imbalance (M-A)

| Field | Assessment |
| --- | --- |
| MECHANISM | Sub-hour aggressive-flow imbalance from aggTrades |
| NEW_INFORMATION_USED | Event-level direction/size (genuinely new resolution) |
| FAILED_FAMILY_COLLISION | **High** — H5 (#12) already tested flow-imbalance continuation at 1h; event-level variants remain in the same mechanism family; explicit re-entry would require a documented mechanism change against #12 |
| WHY_NOT_PARAMETER_RETRY | A sub-hour re-roll of H5's imbalance would be exactly the prohibited parameter retry pattern |
| EXPECTED_COST_PROFILE | Severe: taker fees × high turnover (H5 already cost-thin at 40 bps RT) |
| PIT_FEASIBILITY | High, but full-history storage (~101 GB) needs `COST_REVIEW_REQUIRED` |
| DECISION | **DEFERRED** — not selected for H6; requires its own cost-hurdle prereg design and documented differentiation from #12 |

## Verdict

- `H6_FAILED_MEMORY_COLLISION_REVIEW = PASS`
- No candidate repeats a failed family's mechanism, information set, or parameterization. M-B carries genuinely new information; M-A is deferred with reasons recorded (never silently dropped).
