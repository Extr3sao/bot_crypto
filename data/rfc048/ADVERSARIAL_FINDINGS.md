# RFC-048V — Adversarial Findings

- Falsifier: `RFC048V-FALSIFIER-v1` · head `081201f1eeaf` · prefix `19b1a0b`
- Random search: seed `20261010` x 4000 scenarios
- Verdict: **PASS — no false approval survived; every invariant held under the counterexamples, the catalogue replay, the randomized search, the numeric-root liquidation cross-check and the concurrency probes.** · FALSE_SUCCESS = 0

## Invariants

| invariant | status |
| --- | --- |
| `I1_APPROVED_RISK_LE_BUDGET` | HELD |
| `I2_MARGIN_LE_AVAILABLE` | HELD |
| `I3_NOTIONAL_LE_MAX_ALLOWED` | HELD |
| `I4_DATA_ORDER` | HELD |
| `I5_UNKNOWN_CRITICAL_INPUT` | HELD |
| `I6_UNSUPPORTED_CONTRACT` | HELD |
| `I7_LIQUIDATION_KNOWN_AND_SAFE` | HELD |
| `I8_LIVE_ROUTE_BLOCKED` | HELD |
| `I9_NO_ORDER_AUTHORISED` | HELD |
| `I10_ROUNDING_REDUCES` | HELD |

## Defects found and fixed

### DEF-048V-01 — non-finite numbers were not validated: NaN mark and NaN leverage reached approvals (HIGH, FIXED)

- Cause: every limit used `<=` style comparisons and NaN satisfies none of them; the engine had no finiteness gate
- Fix: engine._validate_numbers refuses any non-finite or impossible input as DATA_INVALID/INVALID_NUMERIC_INPUT; the ledger refuses non-finite amounts; cost and margin models guard their own arithmetic
- Counterexample: `NaN mark_price -> REDUCE_SIMULATED_SIZE (pre-fix)`
- Regression tests: `test_non_finite_proposal_fields_are_refused`, `test_non_finite_snapshot_state_is_refused`, `test_non_finite_open_position_is_refused`, `test_non_finite_mark_is_not_silently_treated_as_present`

### DEF-048V-02 — hostile numbers raised instead of refusing (NaN reached int()) (HIGH, FIXED)

- Cause: round_quantity_down() and the funding-settlement conversion called int() on unvalidated floats
- Fix: quantity rounding returns 0 for non-finite input (a refusal), the numeric gate rejects the request before any arithmetic, and depth levels that are not readable make the impact unknown
- Counterexample: `NaN spread/horizon/stop/equity -> ValueError (pre-fix)`
- Regression tests: `test_non_finite_spread_is_refused`, `test_hostile_input_matrix_never_raises`

### DEF-048V-03 — a repeated decision id reserved its margin twice (MEDIUM, FIXED)

- Cause: MarginLedger.try_reserve appended a grant per call, with no identity
- Fix: a grant for the same decision id is re-confirmed instead of counted again; a larger request for the same id is SHARED_COLLATERAL_CONFLICT
- Counterexample: `two evaluations of decision DUP-1 reserved 165 USDT for one decision`
- Regression tests: `test_repeated_decision_id_is_idempotent`

### DEF-048V-04 — the aggregate margin-utilization ceiling could be exceeded by concurrent decisions (MEDIUM, FIXED)

- Cause: the ceiling was enforced against each decision's snapshot, not against the live reservation, so two approvals could pass 50% together
- Fix: the engine hands the ceiling to the ledger, which enforces it atomically under the same lock as the reservation (MARGIN_UTILIZATION_LIMIT)
- Counterexample: `two sequential decisions on a stale snapshot left 660 USDT reserved on 1000 USDT of equity (66%) with a 50% policy ceiling`
- Regression tests: `test_aggregate_margin_utilization_holds_under_concurrency`

### DEF-048V-05 — a non-finite reservation poisoned the ledger for every later decision (MEDIUM, FIXED)

- Cause: try_reserve accepted NaN and made reserved/free NaN
- Fix: the ledger refuses non-finite amounts and non-finite equity
- Counterexample: `try_reserve(NaN) -> (True, nan); free became nan`
- Regression tests: `test_ledger_refuses_non_finite_amounts`

### DEF-048V-06 — an unmodelable stress scenario was silently treated as no stress (MEDIUM, FIXED)

- Cause: a NaN stress path produced a NaN liquidation price and every comparison against NaN is False, so the path was skipped
- Fix: the engine rejects non-finite stress parameters as DATA_INVALID and the margin model refuses a stress it cannot evaluate (LIQUIDATION_RISK_UNKNOWN)
- Counterexample: `StressScenario(adverse_move_pct=NaN) -> REDUCE_SIMULATED_SIZE (pre-fix)`
- Regression tests: `test_unmodelable_stress_is_refused_by_the_engine`, `test_unmodelable_stress_blocks_the_margin_model_directly`

### DEF-048V-07 — a non-finite funding observation could corrupt the funding term (LOW, FIXED)

- Cause: funding_context() trusted every row it could see
- Fix: only finite, timestamped observations are visible point-in-time; with no usable rate left, funding is UNKNOWN and the position is refused
- Counterexample: `all-NaN funding history with a settlement in the horizon (pre-fix: 0.0 cost)`
- Regression tests: `test_non_finite_funding_observation_makes_funding_unknown`

### DEF-048V-08 — the closed-form liquidation solve extrapolated the maintenance amount below its zero floor (MEDIUM, FIXED)

- Cause: the venue floors maintenance at max(notional*rate - cum, 0); the linear solve ignored the kink, so at the deepest bracket it returned a non-positive price and a 5 bps LARGER buffer than the true model (unsafe direction: it understated the liquidation price for a long)
- Fix: the solve is now piecewise: each linear branch is solved and the candidate inside its own domain is kept (the floored branch when the clamp binds)
- Counterexample: `LONG, notional 999999.99, 1x: builder returned liquidation_price=0.0 while the numeric root of the floored condition gives 41.25 (5.0 bps of overstated buffer)`
- Regression tests: `test_liquidation_respects_the_maintenance_floor`

## Counterexample replay (pre-fix behaviour → post-fix behaviour)

| case | pre-fix | post-fix | safe refusal |
| --- | --- | --- | --- |
| NaN mark price reached an approval | 19b1a0b: decision=REDUCE_SIMULATED_SIZE with mark_price=NaN (the marke | `DATA_INVALID` | True |
| infinite mark price reached an approval | 19b1a0b: decision=REDUCE_SIMULATED_SIZE with mark_price=inf | `DATA_INVALID` | True |
| NaN leverage produced an approval with a NaN margin | 19b1a0b: decision=REDUCE_SIMULATED_SIZE, required_margin=NaN (min(NaN, | `DATA_INVALID` | True |
| NaN spread reached int() and raised | 19b1a0b: ValueError('cannot convert float NaN to integer') | `DATA_INVALID` | True |
| NaN horizon reached int() and raised | 19b1a0b: ValueError('cannot convert float NaN to integer') | `DATA_INVALID` | True |
| NaN stop price reached int() and raised | 19b1a0b: ValueError('cannot convert float NaN to integer') | `DATA_INVALID` | True |
| NaN equity reached int() and raised | 19b1a0b: ValueError('cannot convert float NaN to integer') | `DATA_INVALID` | True |
| NaN stress scenario silently modelled as no stress | 19b1a0b: decision=REDUCE_SIMULATED_SIZE; the NaN path produced no brea | `DATA_INVALID` | True |
| NaN stress funding rate silently charged zero | 19b1a0b: decision=REDUCE_SIMULATED_SIZE with buffer 9874.5 bps | `DATA_INVALID` | True |
| NaN open-position notional defeated the exposure ceilings | 19b1a0b: NaN exposure made every cap comparison False | `DATA_INVALID` | True |
| NaN reservation poisoned the ledger | 19b1a0b: try_reserve(NaN) returned (True, nan); free became NaN | `try_reserve(NaN) -> ok=False, reason=INVALID_NUMERIC_INPUT` | True |
| a repeated decision id reserved twice | 19b1a0b: two reservations of 82.5 for the same decision id (165 total) | `duplicate reserve -> reserved=82.5` | True |

## Randomized search

| classification | count |
| --- | --- |
| AGREE | 3996 |
| CONSERVATIVE_DIVERGENCE | 4 |

False approvals: **0** · conservative divergences (engine stricter than the oracle) are recorded separately and are not defects.

## Liquidation cross-check

- 50 grid points (long/short x five notionals x five leverages)
- Worst closed-form vs numeric-root difference: **0.0000000006 bps**
- Mismatches beyond 0.01 bps: 0

## Portfolio concurrency

- `simultaneous_reserve`: OK — {"no_double_count": true, "solvent": true, "aggregate_utilization_respected": true, "refusals_name_the_ceiling": true}
- `cancel_then_reserve`: OK — {"release_restores_the_pool": true, "re_reserve_succeeds": true}
- `failed_reserve`: OK — {"refused": true, "pool_untouched": true, "reason_is_insufficient_margin": true}
- `retry_same_decision`: OK — {"counted_once": true, "finite": true, "released_back_to_zero": true}
- `snapshot_skew`: OK — {"ledger_equity_authoritative": true, "reserved_within_real_pool": true}
- `reserve_release_storm`: OK — {"reserved_matches_grants_minus_releases": true, "ceiling_holds": true, "pool_solvent": true, "no_exceptions": true}

## Catalogue cross-check

| classification | count |
| --- | --- |
| AGREE | 27 |
| CONSERVATIVE_DIVERGENCE | 4 |

_2026-10-10T09:29:39Z_
