# H6 FAILED-MEMORY COLLISION REVIEW V2 — OI-DATASET-REFREEZE-02 (Track L V2)

Computed **after** dataset V2 freeze (`OI_FULL_HISTORY_DATASET_SHA256_V2 = 16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`) and **before** any performance inspection. Register read in full: `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (12 terminal entries).

## Candidate 1 — M-B: OI position-stock dynamics (SELECTED — H6-OI-CONFIRMED-CONTINUATION-02)

| Field | Assessment |
| --- | --- |
| MECHANISM | Position-stock (open interest) expansion conditioning of 1h decisions: trade only when price movement is accompanied by **qualifying OI expansion** (`delta_oi > 0 AND robust_z_oi >= 1.0` with `robust_z = (delta_oi - rolling_median) / (1.4826 * MAD)` over trailing 720h, min 336 obs, MAD==0 ⇒ NO_TRADE); contraction hours yield NO_TRADE — expansion-only continuation |
| NEW_INFORMATION_USED | `sum_open_interest` / `sum_open_interest_value` (5m) — **absent from every failed experiment's information set** (all 12 failures are price/volume/funding/flow-derived; none read OI) |
| FAILED_FAMILY_COLLISION | **Low.** H1 (#10): transition *labels* on 1h OHLCV — different variable and family; H3 (#11): BTC↔ETH spread reversion — different mechanism and asset pair; H5 (#12): 1h order-flow *aggregates* (OHLCV-family taker fields) — closest analogue, but trade-flow quantity vs position-stock quantity are distinct market variables; momentum/trend/breakout/MR/carry (#1–#9): different variables entirely |
| WHY_DISTINCT | OI is a **stock** of outstanding contracts; every failed family conditions on *flows* (price change, volume, funding basis, taker imbalance) or derived *states*. Conditioning direction on participation stock is a new information axis for this program |
| WHY_NOT_PARAMETER_RETRY | No prior OI experiment exists to re-parameterize; the conditioning variable itself is new (not a re-rolling of H5's z-threshold or H1's labels); follow-up uses PIT rolling distributions, not hand-tuned constants |
| EXPECTED_COST_PROFILE | Favourable **by design**: hourly decisions, OI-conditioned (expected coarser than ~6.5 qualifying transitions/day of H1); prereg enforces **NO cooldown** (one decision per completed asset-hour) and **`BASE_TOTAL_ROUND_TRIP_COST_BPS=10` TOTAL RT**; gross reporting mandatory |
| EXPECTED_FREQUENCY | Moderate (OI quadrant expansion persistence); target event count sized by prereg `minimum_N` per spec (30 per-asset / 100 pooled) |
| PIT_FEASIBILITY | High — OI is observation-time data (`oi_time <= decision_time` enforced by V2 causal helpers in `src/trading_bot/research/oi_dataset_v2.py`); **archive-day validity is forensic-only** and **MUST NOT** gate trading decisions; same-day future data never influences eligibility at T (PIT adversarial tests in `PIT_CAUSALITY_V2_REPORT.json`) |
| NORMALIZATION | `median / (1.4826 * MAD)` over trailing 720h (defined in `H6_SPEC_V2.json`); rolling std is NOT used |
| EXPANSION/CONTRACTION | Expansion-only (`z >= 1` with `delta_oi > 0` qualifies; contraction ⇒ NO_TRADE; contraction-reversal would be a separate prereg) |
| DECISION_SPACING | **NO COOLDOWN** — `ONE_DECISION_PER_COMPLETED_ASSET_HOUR` as in `H6_SPEC_V2.json` |

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

## Funding policy (canonical alignment)

`FUNDING_DISCOVERY_ACCOUNTING = EXCLUDED_WITH_LIMITATION` with `funding_materiality_gate_before_promotion = true` (same as `H6_SPEC_V2.json`). No funding P&L is silently embedded in the discovery evaluation; promotion requires an explicit funding materiality audit.

## Verdict

- `H6_FAILED_MEMORY_COLLISION_REVIEW_V2 = PASS`
- No candidate repeats a failed family's mechanism, information set, or parameterization. M-B carries genuinely new information; M-A is deferred with reasons recorded (never silently dropped).
- This V2 review uses the **same** collision analysis as V1 but corrects three textual contradictions that appeared in the V1 supporting artifacts (reviewed by external consistency audit): this V2 text uses `H6_SPEC_V2`'s canonical `BASE_TOTAL_ROUND_TRIP_COST_BPS=10` (not 12 bps), `median/(1.4826*MAD)` (not rolling std), and documents `ARCHIVE_DAY_VALIDITY = forensic only` / `ONE_DECISION_PER_COMPLETED_ASSET_HOUR` explicitly to match `H6_SPEC_V2.json`.
