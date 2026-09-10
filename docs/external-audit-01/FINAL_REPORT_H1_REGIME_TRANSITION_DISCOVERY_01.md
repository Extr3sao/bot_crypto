# FINAL REPORT — H1-REGIME-TRANSITION-DISCOVERY-01 + POC02-R2 DIAGNOSTIC CONTINUATION

Date: 2026-09-10 · Branch: `feat/ma-2-specialist-opportunity-swarm`

## Headline

**H1 = DISCOVERY_FAIL.** The preregistered regime-transition defensive hypothesis was
executed exactly once against the frozen window and produced **zero gross edge**
(−0.003 R) and **negative net expectancy** (−0.128 R) on N=10,193 trades.
Checkpoint status: **PASS** (governance held; one evidence-timeline anomaly is
documented forensically, not repaired away).

## Final report block (required fields)

| Field | Value |
| --- | --- |
| **CHECKPOINT** | H1-REGIME-TRANSITION-DISCOVERY-01 |
| **PREREG_COMMIT** | `3ad054d84bb32aa54b4c04bffb66a14bf8b7ada9` (2026-09-10T10:28:57Z) |
| **H1_SPEC_SHA256** | `8baaff7dea28a346c9754eb408f537aaee24978b9dce279d213942863e5fc701` (verified byte-identical: working tree == prereg commit) |
| **H1_CONFIG_SHA256 / H1_PROTOCOL_SHA256** | same as spec (config, protocol and cost model are embedded in the frozen spec; declared in `H1_PREREG_HASHES.json`) |
| **H1_EXECUTION_COMMIT** | `4c6ed5e0dbcc9491de2d2c382491940dc8e1a30f` (2026-09-10T13:01:13+02:00) — contains artifacts + POST_RUN_FILL fill |
| **PREREG_ORDERING** | **PASS** — prereg `3ad054d` < economic execution (2026-09-10T11:32Z) < execution commit `4c6ed5e`. No post-hoc ordering repair was performed. |
| **H1_EXECUTIONS** | **1 economic** (11:16Z→11:32Z, code state `b9e2760`). One pre-result crash (constructor kwarg, no output consumed) + one deterministic `--replay` (11:42Z, verification only). |
| **H1_RESULT** | **DISCOVERY_FAIL** |
| **H1_N** | 10,193 (BTC 3,519 · ETH 3,546 · SOL 3,128) |
| **H1_NET_EXPECTANCY** | −0.1275 R (gross −0.0030 R) |
| **H1_PF** | 0.833 net (0.995 gross) |
| **H1_SHARPE** | −0.0665 |
| **H1_SHARPE_CI** | [−0.0876, −0.0445] — CI entirely below 0 |
| **H1_P_SHARPE_GT_0** | 0.0 |
| **H1_PERMUTATION_P** | 1.0 |
| **H1_MAX_DD** | 1,300.6 R (MC DD95 = 1,627.8 R) |
| **H1_HALVES** | [−1, −1] — uniformly negative |
| **H1_THIRDS** | [−1, −1, −1] — uniformly negative |
| **H1_WALK_FORWARD** | last-third net R = −0.0884 (degrades forward) |
| **H1_ROBUSTNESS** | FAIL — no robustness to achieve; mechanism carries zero gross edge even before costs |
| **H1_COSTS** | included: 10 bps RT frozen; cost drag 0.1245 R; slippage sensitivity net R: 5 bps → +0.059, 10 bps → −0.128, 20 bps → −0.128 (sign flips with cost, confirming a cost-dominated, edge-less mechanism) |
| **H1_OPPORTUNITIES_PER_DAY** | raw 11.94 · qualifying 6.51 |
| **H1_INCREMENTAL_OPPORTUNITIES** | 0.99/day |
| **H1_NO_SIGNAL_OPPORTUNITIES** | 13,272 transitions with no tradeable signal (accounting field `no_trade_opportunities`) |
| **H1_ORTHOGONALITY** | trade-time overlap 0.849 · daily PnL correlation 0.232 (2,308 common days) · regime activation overlap not redundant |
| **H1_REDUNDANT** | false (fail is economic, not redundancy) |
| **PAPER_PROMOTIONS** | 0 |
| **R2_STATUS** | ACTIVE (11 cycles; heartbeat 2026-09-10T11:28:51Z; untouched this checkpoint) |
| **R2_CLASSIFICATION** | DIAGNOSTIC_CAMPAIGN · DEGRADED_OBSERVATIONAL_CAMPAIGN · INVALID_FOR_PERFORMANCE_CERTIFICATION — retained unchanged |
| **SHADOW_CAPTURES** | 11 (R2 campaign state; 10 at checkpoint open) |
| **SHADOW_RESOLVED** | 0 (earliest maturity 2026-09-11T21:15Z; nothing resolved early) |
| **SHADOW_POLICY_CONCLUSION** | INSUFFICIENT_SAMPLE |
| **CONFIRMATION_CONSUMED** | false (`CONF-EDGE-002-001`, window closes 2026-09-22, no peeking) |
| **CONFIRMATION_EXECUTIONS** | 0 |
| **RISK_CHANGED** | 0 |
| **CURRENT_CAMPAIGN_CHANGED** | 0 |
| **LIVE_CALLS** | 0 (also REAL_BROKER=0, PRIVATE_EXCHANGE=0, SHADOW_PAPERBROKER=0) |
| **FALSE_SUCCESS** | 0 |
| **HERMETIC_REGRESSION** | PASS — 1210 passed / 0 failed (`scripts/run_regression_hermetic.py`; host-env run 1157 passed / 1 pre-existing env-dependent failure in untouched `test_settings.py`) |
| **STATUS** | **PASS** |

## Governance acceptance (GOV / H1 / R2 / CONF)

- **GOV-01** PASS — previous checkpoint state committed (`b9ddc35`) before the H1
  execution commit; note the economic *simulation* itself pre-dated this checkpoint
  session and its artifacts are committed as-found (Gate 0 premise that artifacts were
  staged was stale: nothing was staged; committed sequence below).
- **GOV-02** PASS — spec hash frozen; working-tree `H1_SPEC.json` sha256 verified equal
  to the prereg-commit value; runner refuses any other hash.
- **GOV-03** PASS — `3ad054d` (10:28:57Z) < economic execution (11:32Z) < `4c6ed5e`.
- **H1-01** PIT safe (unit-proven: states use only the window ending at the decision bar).
- **H1-02** future-mutation invariant — `test_future_mutation_causality_transitions_and_states_byte_identical` (20/20 H1 unit tests pass).
- **H1-03** exactly one economic experiment (exactly-once marker; replay flagged technical only).
- **H1-04** costs included (10 bps RT frozen, sensitivity 5/20 pre-declared).
- **H1-05** robustness — measured; failed.
- **H1-06** temporal stability — measured; halves/thirds uniformly negative.
- **H1-07** regime-conditioned — full transition-label breakdown committed (e.g. NORMAL→CORRECTION: N=675, net −0.248 R).
- **H1-08** orthogonality measured (B2 committed).
- **H1-09** frequency contribution measured (B3 committed).
- **H1-10** no retuning — only pre-result changes were a pre-evaluation window-end constant alignment to the frozen spec (documented in execution log before any result existed).
- **H1-11** no promotion — DISCOVERY_FAIL is terminal for this spec; no confirmation, no holdout, no paper.
- **R2-01/02/03/04** PASS — campaign unchanged, diagnostic classification retained, shadow mature-only (0 resolved), paper contamination 0.
- **CONF-01** PASS — confirmation lock untouched, window never read.

## B1 — Why it failed (mechanism)

- The transition **state** alone carries no directional edge: gross expectancy ≈ 0
  (−0.003 R) before costs. Costs (−0.125 R drag) then make net expectancy negative.
- The dominant leg is SHORT-on-correction/shock (N=10,058, net −0.129 R): fading
  shocks short inside the structural 2020→2026 uptrend is mechanically adverse.
- The LONG leg is marginal and underpowered (N=135, net +0.018 R, PF 1.028).
- Highest-frequency labels dominate the loss: NORMAL→SHOCK (N=4,552, net −0.141 R),
  BULL|TREND→NEUTRAL|TREND (N=161, net −0.281 R), BULL|RANGE→NEUTRAL|RANGE
  (N=127, net −0.281 R). Isolated positive cells (e.g. NORMAL→HIGH, N=11;
  BULL|RANGE→NEUTRAL|TRANSITION, N=20, perm p=0.043) are small-N leads only —
  **not** confirmations and **not** re-run invitations under failed-memory rules.

## Evidence-timeline anomaly (documented, not repaired)

On-disk mtimes show `H1_RESULT.json` (11:32:13Z) *earlier* than
`H1_EXECUTION_MARKER.json` (11:42:29Z), although the marker is written before the
result in the economic path. Forensic explanation (recorded in
`H1_EXECUTION_LOG.md`): a later `--replay` invocation reproduced the economic
result byte-for-byte, but the replay path erroneously re-wrote the exactly-once
marker and re-appended the crash note — corrupting the marker's timestamp.
Both side effects are governance-fixed in the checkpoint commit and can never
recur (marker/attempt notes are now economic-run-only; the replay determinism
compare no longer short-circuits on `POST_RUN_FILL`). The replay was deterministic
verification, not a second economic experiment. No timestamps or metrics were
rewritten to "repair" this.

## Commit chain

1. `b9e2760` — frozen evaluation core + exactly-once runner (pre-existing, pre-result)
2. `b9ddc35` — **checkpoint commit (Gate 0)**: R2 evidence, dataset (169,724 raw rows), H1 result artifacts, failed-memory #10, dashboard lab entry, runner replay-path governance fixes
3. `4c6ed5e` — **execution commit**: POST_RUN_FILL + provenance/forensic note

## NEXT

- H1 = DISCOVERY_FAIL → do **NOT** prepare a confirmation protocol for this spec.
- Next hypothesis selection must use REGIME_COVERAGE_GAP_REPORT + FAILED_RESEARCH_MEMORY
  #1–#10: H2 (vol term-structure gate) is **blocked** by mechanism overlap with #10;
  H4 remains cost-blocked (#9); H3 (relative-value) is the top unblocked IDEA but
  weak on cost realism. No automatic execution of H2/H3/H4 in this checkpoint.
- CONTINUE_DIAGNOSTIC_R2 (do not restart if healthy) · MATURE_SHADOW
  (earliest 2026-09-11T21:15Z; first aggregate Risk diagnostic only at ≥25 mature)
  · CONFIRMATION_WAIT (window closes 2026-09-22).

## SIMILARITY_TO_FAILED_HYPOTHESES

H1 is **not** a re-run of any registered failure (legacy momentum/trend/breakout/MR,
volatility_structure #6, cross_sectional #7, carry_funding #8, session_time #9): it
conditioned entries on a PIT regime-transition state, a mechanism none of them used.
Its failure mode (zero gross edge + cost drag + structural SHORT-against-uptrend
adversity) is registered as #10, and H2's vol-gate premise is now explicitly blocked
by it. The small positive NORMAL→HIGH / TRANSITION cells must not be re-parameterized
into a new hypothesis without a mechanism change registered against #10.
