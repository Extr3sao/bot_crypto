# FINAL REPORT — H3-PREREG-VERIFICATION-AND-DISCOVERY-01 + POC02-R2 SHADOW CONTINUATION

Date: 2026-09-10 · Branch: `feat/ma-2-specialist-opportunity-swarm`
Chain: prereg `83b3acd` → engine/runner pre-execution `4ea37b3` → economic execution 2026-09-10T20:16:48Z → execution commit `8059ee9`

## Headline

All mandatory authority gates passed (no prereg drift, cost engine proven,
PIT proven, synchronization perfect), so H3 was **executed exactly once** —
the first discovery hypothesis of the program to run on a fully verified
cost engine. Result: **DISCOVERY_FAIL (terminal)**. The mean-reversion
premise fails **before costs**: at |z| ≥ 2.5 dislocations the BTC↔ETH log
spread **continued** more often than it reverted (gross PF 0.492, win rate
0.313, both directions uniformly negative). The strategy was genuinely
orthogonal to everything in the universe — and that was worthless without a
mechanism. The "beta-neutral" label did not survive contact with the data
(DEF-H3-NEUTRALITY-001). STATUS: **PASS** (governance held; the failure is
the strategy's, not the process's).

## Required report block

| Field | Value |
| --- | --- |
| CHECKPOINT | H3-PREREG-VERIFICATION-AND-DISCOVERY-01 |
| PREREG_COMMIT | `83b3acde3dc4c45f9680ab9be2f0a72eeeddeb41` |
| SPEC_SHA256_VERIFIED | `90c566993b9cdd6b42b9eac5b482f8a96657728cbfd8c04a2df3567b23848d50` (working tree == blob at 83b3acd == expected) |
| PREREG_DRIFT | **false** |
| COST_ENGINE | **PASS** — 0/5/10/20/40 bps → net −0.3674/−0.3783/−0.3892/−0.4111/−0.4547 R; monotone non-increasing, COST ≥ 0, NET = GROSS − COST (≤1e-12), identical trade set across scenarios (linear absolute semantics anchored at 0 bps = gross) |
| MULTILEG_COST | **PASS** — 4 executions per round trip (BTC entry + ETH entry + BTC exit + ETH exit); `COST_PER_LEG` = 5 bps/side; `ROUND_TRIP_PAIR_COST` = 20 bps on traded notional; `COST_R_FORMULA` = 2·(side_bps/10000)·(1+β)/σ_spread |
| FUNDING_INCLUDED | **false** — `FUNDING_EXCLUDED_BY_PREREG` (spec `cost_model.funding = N/A`, declared ex ante, unchanged) |
| FUNDING_LIMITATION | None material: the failure is at the gross level (PF 0.492 < 1 with zero cost); funding cannot rescue a negative-gross mechanism. Recorded for any future promotion decision on a successor mechanism |
| PIT_BETA | **PASS** — trailing 336-bar OLS of Δln BTC on Δln ETH; β, mean, std, corr, z use only observations ≤ t; no full-window regression, no future normalization (unit-pinned) |
| FUTURE_MUTATION | **PASS** — adversarial test mutates ALL prices strictly after T (×1.5 BTC / ×0.7 ETH); features (β, spread, std, z) and all 118 entry decisions ≤ T byte-identical |
| SYNC_DATA | **PASS** — BTC_ROWS 58,633 · ETH_ROWS 58,633 · COMMON_ROWS 58,633 · MISSING_BTC 0 · MISSING_ETH 0 · MISALIGNED 0 · STALE 0 · identical timestamp sequences |
| BETA_NEUTRALITY | **FAIL as labeled** — MEAN_GROSS_EXPOSURE 1.656 · MEAN_ABS_NET_EXPOSURE 0.344 · MEAN_ABS_BETA_EXPOSURE 0.549 · P95 0.843 (per unit leg-A notional). The preregistered ≤0.10 average net-exposure bar was NOT achieved → **DEF-H3-NEUTRALITY-001** registered; H3 must not be described as beta-neutral. Does not change the (already terminal) result |
| H3_EXECUTIONS | **1 economic** (2026-09-10T20:16:48Z, marker written before result; ordering 83b3acd < execution < 8059ee9). One pre-result crash (comprehension bug) before any output was written, documented in H3_EXECUTION_LOG.md. No replay performed |
| H3_RESULT | **DISCOVERY_FAIL** |
| H3_N | 243 (SPREAD_SHORT 109 · SPREAD_LONG 134) |
| H3_GROSS_EXPECTANCY | −0.3674 R |
| H3_NET_EXPECTANCY | −0.3783 R (cost drag 0.0109 R — structural failure, not cost-driven) |
| H3_PF_GROSS / H3_PF_NET | 0.492 / 0.482 |
| H3_SHARPE | −0.2266 |
| H3_SHARPE_CI | [−0.3902, −0.0868] — entirely below 0 |
| H3_P_SHARPE_GT_0 | 0.001 |
| H3_PERMUTATION_P | 1.0 |
| H3_MAX_DD | 110.9 R (MC DD95 134.6 R) |
| H3_WALK_FORWARD | last-third net R = −0.1894 (degrades forward) |
| H3_HALVES / H3_THIRDS | [−1, −1] / [−1, −1, −1] — uniformly negative |
| H3_ROBUSTNESS | FAIL — preregistered set only (cost sensitivity, halves/thirds, walk-forward, MC, direction stability); no sweep, no new thresholds, no alternate lookback/pair/timeframe |
| H3_OPPORTUNITIES_PER_DAY | 243 trades / 2,411 days ≈ 0.10 qualifying/day (sparse by design — the cost-attack choice; did not help because gross edge is negative) |
| H3_ORTHOGONALITY | trade-time overlap 0.490 vs ROC(24) proxy · 0.391 vs H1-BTC replay; daily PnL correlation **0.009** vs proxy · **−0.035** vs H1 |
| H3_REDUNDANT | **false** (redundancy rule 0.6/0.7 did not fire) — orthogonal AND edge-less |
| PAPER_PROMOTIONS | 0 |
| R2_STATUS | ACTIVE — POC-02-R2-direction-arbitration-01, unchanged; DIAGNOSTIC / DEGRADED / INVALID_FOR_PERFORMANCE_CERTIFICATION retained |
| SHADOW_CAPTURES / RESOLVED | 11 / 0 (mature-only; first maturity 2026-09-11T21:15Z) |
| SHADOW_POLICY_CONCLUSION | INSUFFICIENT_SAMPLE |
| CONFIRMATION_CONSUMED / EXECUTIONS | false (`CONF-EDGE-002-001`, closes 2026-09-22, no early inspection) / 0 |
| RISK_CHANGED | 0 |
| LIVE_CALLS / FALSE_SUCCESS | 0 / 0 |
| HERMETIC_REGRESSION | PASS — **1217 passed / 0 failed** (1211 + 6 new H3 invariant tests) |
| STATUS | **PASS** |

## Mechanism post-mortem (why it failed)

- **Reversion premise refuted at gross level:** entries at |z| ≥ 2.5 against the
  336-bar mean were followed by spread continuation within the 48-bar horizon
  (gross PF 0.492; win rate 31.3%). Cost drag (0.011 R) is negligible relative to
  the −0.367 R gross expectancy — better execution could not save this.
- **Symmetric failure:** SPREAD_SHORT (fade BTC-rich) N=109, net −0.515 R;
  SPREAD_LONG (fade ETH-rich) N=134, net −0.267 R; halves/thirds uniformly
  negative in both — not a one-sided artifact.
- **Genuinely orthogonal, genuinely empty:** daily PnL correlation 0.009 vs the
  legacy momentum proxy and −0.035 vs H1 — the cross-asset family adds new
  exposure, but the trailing-z normalization carried no exploitable structure.
  Orthogonality is necessary, never sufficient.
- **Neutrality was a label, not a property:** beta-weighted sizing with a rolling
  β ≠ 1 leaves material net exposure (mean |net| 0.344). Registered as
  DEF-H3-NEUTRALITY-001; any successor must structurally meet the ≤0.10 bar or
  drop the market-neutral claim.

## Acceptance mapping

H3-01 ✓ · H3-02 ✓ (PREREG_DRIFT=false) · H3-03 ✓ · H3-04 ✓ · H3-05 ✓ (explicit ex-ante exclusion) ·
H3-06 ✓ · H3-07 ✓ · H3-08 ✓ · H3-09 ✓ (measured; gate failed → defect registered, label withdrawn) ·
H3-10 ✓ (exactly 1; pre-result crash documented, wrote nothing) · H3-11 ✓ (prereg robustness only) ·
H3-12 ✓ (prereg orthogonality only) · H3-13 ✓ (no retuning; zero post-result parameter changes) ·
H3-14 ✓ (PAPER_PROMOTIONS=0) · R2-01 ✓ · SH-01 ✓ · CONF-01 ✓ · LIVE_CALLS=0 · FALSE_SUCCESS=0.
Track M: `H1_REPORT_SEMANTICS.md` written (documentation-only; `H1_RESULT.json` untouched).

## NEXT

- H3 = DISCOVERY_FAIL → **WRITE FAILURE MEMORY** (done: FAILED_RESEARCH_MEMORY #11)
  → **RETURN TO REGIME GAP MAP** → select next ORTHOGONAL IDEA with a mechanism
  change registered against #11 (no re-parameterization; the small positive regime
  cells BULL|STRONG|LOW|TREND N=10 and BEAR|STRONG|LOW|TREND N=8 are
  POST_HOC_LEAD_ONLY · DO_NOT_RETEST_WITHOUT_NEW_EX_ANTE_HYPOTHESIS).
- H2 (vol term-structure gate) remains blocked by memory #10; H4 remains
  cost-blocked (#9). No automatic execution of any hypothesis.
- CONTINUE_R2_DIAGNOSTIC (no restart) · MATURE_SHADOW (first capture matures
  2026-09-11T21:15Z; aggregate Risk diagnostic only at ≥25 mature) ·
  CONFIRMATION_WAIT (≤ 2026-09-22).
