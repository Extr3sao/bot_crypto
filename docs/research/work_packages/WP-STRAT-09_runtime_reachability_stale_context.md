# WP-STRAT-09 — Runtime reachability: the `stale_context` evaluation ceiling

- ORIGIN: WP-STRAT-08 §23 (next demonstrated bottleneck).
- BOTTLENECK CLASS: **runtime reachability** (priority 2 in the §23 ordering;
  priority 1 *correctness* had no demonstrated defect this WP).
- STATUS: PREPARED (not implemented). Do **not** start by changing any gate.
- EVIDENCE: WP-STRAT-08 SHADOW campaign `paper-strategy-lifecycle-shadow-02`
  (`traces.jsonl` sha256 `b3546f0f9a8596d580920a7ccadb6307e5aa4a66a1593c0c8359b7ae3b39b80f`).

## 1. Observation (measured, REAL_RUNTIME)

In a 2.0 h PAPER+SHADOW campaign at a 60 s cycle and a 5 m timeframe, **50 % of
asset-cycle evaluations (56 of 112 per asset; 168 of 336 overall) are rejected by
the router with `no_trade_reason = "stale_context"` before any strategy is
evaluated for alpha or edge.** The rejection is uniform across BTC/ETH/SOL and
across all six strategies, so it does not bias any one family.

Per-strategy funnel (336 cycles): 168 `stale`, 167 `no_alpha`, 1 `not_evaluated`.
`lifecycle_verdict = null` on the stale rows (`NOT_APPLIED`) — the router returns
before the lifecycle plane, which is why the campaign's
`lifecycle_NOT_APPLIED = 169` per strategy.

## 2. Root cause (traced to the PIT slice, not to a gate bug)

The router's freshness gate compares the decision clock against the newest bar in
the context:

- `RouterGates(timeframe="5m", freshness_grace_bars=1.5)` ⇒ budget
  `stale_after_ms() = 5 m × 1.5 = 450 000 ms` (`router_gates.py`,
  `stale_threshold_for_timeframe`).
- On the stale cycles the context's `timestamp` equals the decision clock, but
  `asset_context.data_quality.newest_bar_ts` (= `window_end_ts`) sits **one 5 m
  bar** behind. Example: decision `1790877494332`, newest sealed bar
  `1790877000000` ⇒ lag ≈ **494 s > 450 s** ⇒ rejected by ≈ 44 s.

So the provider simply has not yet exposed the just-closed bar on ~half of the
60 s cycles; the slice is one bar wide of the budget.

## 3. Why this matters (and why it is *not* a reason to loosen anything)

- It caps the **effective evaluation rate**: half the cycles never reach the
  alpha/edge/lifecycle stages. Any future "frequency" or "reachability" claim
  must account for this, or it will overstate how often a strategy was actually
  considered.
- It is **orthogonal to the WP-STRAT-08 verdict**: every strategy is non-admitted
  and net-negative regardless, so suppressing stale cycles neither created nor
  removed edge. It is a *throughput/observability* bottleneck, not an edge one.

**Hard constraint (WP-STRAT-08 §rules): raising `freshness_grace_bars` or any
staleness budget is a threshold loosening and is OUT OF SCOPE.** A wider gate
would admit older, less relevant context to *manufacture* more evaluations — that
is exactly the failure mode the rules forbid. This WP must reach the same
evaluation rate **without weakening the freshness gate**.

## 4. Candidate safe approaches (choose one after a design check)

1. **Cadence alignment (preferred).** Schedule the evaluation so the decision
   clock lands just after each bar *seal* (e.g. offset the cycle so the newest
   sealed bar is always available), rather than at a fixed 60 s phase. Same gate,
   same budget; the slice simply stops being one bar behind. Behaviour change in
   the *scheduler only*.
2. **Explicit lag observability.** Record `context_lag_ms` /
   `newest_bar_ts` directly on each trace row alongside `router_reason`, so the
   condition is auditable without re-deriving it from `asset_context`. (Partly
   available today via `asset_context.data_quality.newest_bar_ts`; promote it to a
   first-class, queryable field.)
3. **Bar-close-driven `no_alpha` accounting.** When a cycle is stale *and* the
   previous cycle for the same asset already evaluated the same sealed bar,
   record it as a duplicate/`stale_context` (already the case) and exclude it from
   the "considered" denominator in reporting, so throughput metrics are honest.

## 5. Acceptance criteria

- The 5 m freshness budget is **unchanged** (`stale_after_ms("5m") == 450000`);
  a diff to the budget is an automatic FAIL.
- On a fresh bounded PAPER+SHADOW campaign, the fraction of `stale_context`
  rejections falls because the *slice is fresh*, not because the *gate moved*.
- The trace carries an explicit, queryable context-lag field.
- Routing/lifecycle contract invariants (monotone restriction, fail-closed,
  determinism, `orders_created = 0` while nothing is admitted) still hold.

## 6. Tests

- `tests/unit/research/test_router_gates_freshness.py` — keep the per-timeframe
  budget tests; add a scheduler-phase test if option 1 is chosen.
- A new unit test that a decision clock placed just after a bar seal yields a
  fresh context (lag < budget) and that one placed 494 s after the last seal is
  stale — i.e. pin the *observed* boundary, not a loosened one.

## 7. Rollback

- Option 1: revert the scheduler phase offset → previous cadence.
- Option 2/3: revert to the current trace schema (additive fields only).

## 8. Non-goals / forbidden

- No `freshness_grace_bars` / `STALE_THRESHOLD_MS` change.
- No admission/size/leverage/risk change.
- No LIVE, no capital, no credentials.
- No re-labeling of a widened gate as "reachability".

## 9. Decision

`DEFER` implementation to a bounded follow-up WP. The observation is recorded now
(§23) because it is the only bottleneck demonstrated with real execution
evidence in WP-STRAT-08, and it must not be silently "fixed" by loosening the
gate.
