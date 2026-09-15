# ARC-01 — Independent Preregistration Verification

**FINAL_VERDICT: `PASS_INDEPENDENT_PREREG_VERIFICATION`**

| Field | Value |
| --- | --- |
| Verifier worktree | `.research/arc01-prereg-verifier-01` |
| Verifier branch | `audit/arc01-prereg-verification-01` |
| Target prereg commit | `fa15fb4f300815f56bf14e503d1a147cb73f27a6` |
| Data authority commit | `6e42dd9d4c19800925fd555999686d1e2b4ef47e` |
| Spec SHA256 | `89b8590c…c0b313` (matched) |
| Manifest SHA256 | `d698e3d8…85df5e` (matched) |
| Builder role | `PENDING_INDEPENDENT_PREREG_VERIFICATION` |
| FALSE_SUCCESS | **0** |
| ARC01_BACKTESTS / EXECUTIONS / PERFORMANCE_OBSERVED | `0 / 0 / false` |

The verifier is an **independent context**: it did not design or freeze ARC-01, it read
only, it repaired no builder artifact, and it executed **no economics** (no returns, PnL,
Sharpe, Sortino, profit factor, expectancy or win rate on real data).

---

## 1. Git / freeze authority — PASS

* The worktree was created from **exactly** `fa15fb4…`; no builder untracked files were consumed.
* Both `fa15fb4…` (prereg) and `6e42dd9…` (data authority) exist and the prereg is a descendant of the data authority commit.
* Spec and manifest SHA256 were **independently recomputed** and match the declared values; blob OIDs recorded in `ARC01_GIT_AUTHORITY.json`.
* The frozen artifact set is internally consistent; no post-freeze mutation is required to interpret the economics.

## 2. Data authority binding — PASS

Rehashed from the **actual shared data**, not from builder summaries:

| Binding | Result |
| --- | --- |
| Dataset SHA256 `5f4845f5…3b62ec` | match |
| BTC / ETH / SOL funding partition SHA256 | all match |
| OI V2 dataset fingerprint, ledger SHA256, manifest SHA256 | all recomputed, all match |
| Price V2 per-asset SHA256 | all recomputed, all match |

## 3. Performance contamination — PASS

`ARC01_BACKTESTS = 0`, `ARC01_EXECUTIONS = 0`, `ARC01_PERFORMANCE_OBSERVED = false`.
Nine ARC-01 commits exist; **all** are `ARC01-DATA-*` or `ARC01-PREREG-*`. The prereg commit
is purely additive (17 files) and contains **no** PnL/result/trade-log/backtest artifact.
The economic vocabulary found in the ARC-01 code is a *forbidden-vocabulary deny list* and
gate identifiers — no computation. No pre-prereg economic observation exists.

## 4. Spec completeness — PASS

All required economic fields are present and explicit; `STOP = NONE` and `COOLDOWN = NONE`
are frozen; no hidden runtime default was found (`ARC01_SPEC_COMPLETENESS_AUDIT.json`).

## 5. Decision cadence & entry/exit — PASS

* Decisions are **one per certified funding settlement instant**, read from the frozen
  authority. SOL's historical schedule is confirmed present (`{8h: 6551, 2h: 99, 4h: 2}`),
  so **no 8h assumption** is baked in and no decision is fabricated or skipped.
* Entry is the **next 1h bar OPEN strictly after `decision_time`**; an exact-hour settlement
  does **not** enter on the same bar. Independently verified on aligned and millisecond-jittered
  settlements.
* Exit is the 1h bar OPEN at `entry + 72h`, unconditional, no stop/TP/invalidation exit.
* The last ~72h of the window are structurally censored (`INSUFFICIENT_FORWARD_PRICE_DATA`);
  this consults only the exit-anchor clock, never a price level.

## 6. The “72h = 9 settlements” attack — NON-BLOCKING DOCUMENTATION DEFECT

Attacked as instructed. Findings:

* The **executable** rule iterates every certified settlement in `(entry_time, exit_time]`
  (`funding_cashflow_return(direction_sign, settlement_rates)`); **no count is hardcoded**.
* Empirically, an exact 72h window contains **8 or 9** settlements for BTC/ETH (millisecond
  provider jitter at the exit anchor) and up to **~36** for SOL during its 2h regime.
* The prose (“72h spans 9 settlements”, “at least 9”, “applied 9 times”) is therefore
  **factually imprecise**. Because the execution rule is correct, this is recorded as
  `NON_BLOCKING_DOCUMENTATION_DEFECT` and **not** silently reconciled.

→ **Not a critical defect.**

## 7. Funding cashflow accounting — PASS

* Information window (`<= decision_time`) and cashflow window (`(entry, exit]`) are strictly disjoint → no double counting.
* Sign semantics independently derived and confirmed against Binance USD-M: positive funding ⇒ LONG pays / SHORT receives; negative funding inverts. No sign error.
* Cashflow uses the same certified authority rows read at their settlement instants; no synthesized series.
* Entry-notional simplification is disclosed as a limitation.

## 8. Ex-funding gate independence — PASS

`NET = GROSS_PRICE_LEG + FUNDING_CASHFLOW − COST`; `G3_NET_EXPECTANCY_EX_FUNDING` removes the
funding term and is independent, so a carry-only result fails. No accidental inclusion of funding.

## 9. PIT — PASS

An independent adversarial battery (36 checks, all passing) proves:

* future mutation after `T` leaves the signal unchanged;
* past eligible-window mutation changes the robust state (no caching);
* OI/price/funding observations after `T` are rejected;
* stale (> 600 s) and non-positive OI references fail closed;
* conflicting/degenerate scales fail closed;
* no price/indicator token enters the decision functions.

One **documentation over-claim** is recorded: the PIT contract states that *any* eligible
mutation must move the state, which is false under a median/MAD estimator for a single
non-central point. This is a prose over-claim, not an execution defect.

## 10. NO_SIGNAL precedence — PASS

The 10 frozen reason codes resolve by deterministic first-match on simultaneous failures
(independently tested at each boundary).

## 11. Statistical gates reproducibility — PASS (pre-existing project authority)

Every gate freezes its metric, threshold, statistic, resample/draw count and seed. The only
unstated items are standard estimator conventions — resolved by **pre-existing** project
authority, `src/trading_bot/backtesting/stat_validation.py` (present at the data-authority
commit, predating the prereg):

* Sharpe `ddof = 1` with `periods_per_year = trades_per_year` → exactly the frozen G5 formula;
* percentile bootstrap index `floor(α·R)` → G6;
* one-sided sign-flip (`≥ observed`) → G7.

Corroborating project precedent: the repository's own accepted `H6_SPEC_V2` specifies its
permutation gate with **identical granularity** (“sign-flip permutation on hourly trade
returns, 10,000 draws, fixed seed 20260911”). Therefore:

* `CRITICAL_SPEC_INCOMPLETENESS = false`;
* classification `SPEC_COMPLETE_WITH_PRE_EXISTING_PROJECT_AUTHORITY`, with non-blocking
  conventions recorded (module not hash-bound; G10 month attribution unspecified).

## 12. Controls — PASS

All four controls are frozen and deterministic. The consequence of a control satisfying all
gates is frozen: `ARC01 = DISCOVERY_FAIL`. Minor omission: the gates `fail_semantics` does not
enumerate `TIMING_CONTROL`, but the control plan's general `evaluation_rule` covers every
control, so the operative consequence is unambiguous (recorded as a documentation defect).

## 13. Robustness — PASS

Primary parameters (`60d / 2.0 / 24h / 72h / NONE price / 10 bps / 3 assets`) are immutable.
The neighbourhood is `DIAGNOSTIC ONLY`; no clause permits promoting the best neighbour or
re-running the primary with modified parameters. No retuning is possible.

## 14. Orthogonality — PASS

The apparent builder-summary contradiction is **prose-only**. The frozen contract orders
primary discovery first, then orthogonality at a later authorized checkpoint, with ARC-01
parameters unchanged. No clause requires PnL before economics are permitted.

## 15. Drawdown gate — ACCEPTABLE DISCOVERY LIMITATION

No DD threshold was preregistered (disclosed as diagnostic only). ARC-01 is a discovery
prereg, not the live-promotion gate; the promotion decision remains with the project's
live-trading release gate. Recorded as a limitation that cannot become a gate post hoc.

## 16. Reused OI / price authority — PASS

Every reused OI and price digest reproduces byte-for-byte from the actual shared data. The
builder's worktree lacked the local `data/processed/oi_full_history_v2` directory
(`EXPECTED_ENVIRONMENT_DATA_ABSENCE`); the dependency itself is satisfied in the shared data
root and re-verified here.

## 17. FALSE_SUCCESS = 0

None of the invalidation conditions apply: no contamination, correct Git target, correct
imported checkout, hashes match, data authority matches, no hidden defaults, no ambiguity
affecting execution, controls have defined failure semantics, robustness cannot retune, PIT
is non-vacuous, and all reused authority is available and reproduced.

---

**NEXT = `ARC01_PRIMARY_DISCOVERY_01`**
