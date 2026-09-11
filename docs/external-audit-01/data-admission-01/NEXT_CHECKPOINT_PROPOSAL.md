# NEXT CHECKPOINT PROPOSAL — H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY

Prepared by: ALPHA-DATA-ADMISSION-01 · 2026-09-11 · **PREREG-ONLY — no H6 execution in the next checkpoint (`H6_EXECUTIONS = 0`)**

## 1. What the admitted data enables (and nothing else)

| Family | New information (data-level) | Mechanisms it can carry |
| --- | --- | --- |
| TRADE FLOW (aggTrades, `ADMIT_WITH_LIMITATIONS`) | event-level taker direction, per-trade size, burst intensity, intra-bar sequence | aggressive-flow imbalance at sub-hour resolution; trade-size distribution shifts; burst/absorption dynamics |
| OPEN INTEREST (5m metrics, `ADMIT`) | outstanding **position-stock** level and its 5m changes | position accumulation/liquidation pressure; OI-vs-price divergence; OI rotation across assets |

## 2. Failed-memory collision analysis (against `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md`, 12 terminal entries incl. H5)

- **H5 (terminal `DISCOVERY_FAIL`)** tested orderflow-imbalance predictiveness at **hourly** resolution against hourly OHLCV/takerBuyBaseVolume aggregates, overlapping a ROC(24h) proxy (corrected r ≈ 0.607; overlap 0.916). A trade-flow H6 at event/intra-bar resolution is **mechanically distinct** (event sequence + size distribution do not exist in the failed information set) but belongs to the **same mechanism family** (transaction-flow imbalance) → elevated collision risk with the H5 failure mechanism (momentum-family dependence + cost drag at higher turnover).
- All 12 failed entries are OHLCV/flow/relative-value derivatives on the **same price/volume information set** (CURRENT_INFORMATION_SET was declared `EXHAUSTED_FOR_NOW`, ADR-0033). None used position-stock (OI) state — that information did not exist in the repo before this checkpoint.

## 3. Candidate mechanisms scored (constraints, not preferences)

| Candidate | Expected frequency | Cost hurdle | PIT feasibility | Orthogonality vs failed mechanisms | Collision risk |
| --- | --- | --- | --- | --- | --- |
| M-A: event-level aggressive-flow imbalance | very high (1.8–1.8M trades/day/asset) | **severe** — taker fees × high turnover; full backfill ~101 GB | high (event-time PIT) | partial — same family as H5 | **high** |
| M-B: OI position-stock dynamics (5m) | 288 obs/day/asset | **low** — signal cadence controllable; archive ~66 MB | high (observation-time PIT, no interpolation) | **high** — position stock vs transaction flow/price | **low** |

## 4. Selected hypothesis (exactly one)

**SELECTED: M-B — OPEN-INTEREST POSITION-STOCK DYNAMICS (BTCUSDT, ETHUSDT, SOLUSDT; 5m native).**

Rationale: only mechanism enabled by genuinely **new** information (OI was absent from every failed experiment), lowest cost hurdle, full PIT feasibility, lowest failed-memory collision. M-A (trade flow) is explicitly **deferred**, not rejected: data is admitted and fingerprinted; it requires a cost-hurdle prereg design and a documented differentiation from the H5 failure mechanism before any execution.

## 5. Next checkpoint contract

- Name: `H6-HYPOTHESIS-SELECTION-AND-PREREG-ONLY`.
- Deliverables: H6 prereg spec + manifest (committed, hash-anchored) for M-B only; explicit `H6_EXECUTIONS = 0`; no backtest, no parameter search, no signal code.
- Prereg must freeze: OI field semantics (`sum_open_interest` = base-asset units; `sum_open_interest_value` = USDT), 5m cadence, PIT observation-time rule, dataset fingerprints from `data/processed/*/DATASET_MANIFEST.json`, and the sample-expansion plan (full OI archive backfill is ~66 MB — no cost review needed).

## 6. Parallel obligations (unchanged)

- `CONTINUE_R2_DIAGNOSTIC` — as previously scheduled.
- `MATURE_SHADOW` — resolve only captures with `maturity_time <= current UTC` (earliest 2026-09-11T21:15Z); mature-only, PIT rules.
- `CONFIRMATION_WAIT` — `CONF-EDGE-002-001` stays `consumed=false, executions=0` until 2026-09-22T00:00Z.
