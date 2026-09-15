# ARC03_PREREGISTRATION.md

> **ARC-03 — Participation-shock reversal.**
> One preregistration, one primary discovery. Frozen before any economic observation.
>
> `ARC03_BACKTESTS = 0`
> `ARC03_EXECUTIONS = 0`
> `ARC03_PERFORMANCE_OBSERVED = false`
> `FALSE_SUCCESS = 0`
>
> **Final state of this checkpoint: `PENDING_INDEPENDENT_PREREG_VERIFICATION`.**
> DeepSeek is the BUILDER. DeepSeek may perform a **BUILDER_CROSSCHECK** and may **not**
> claim independent verification. This document is not a certification.

---

## 1. Identity

| Field | Value |
| --- | --- |
| `hypothesis_id` | `ARC-03-PARTICIPATION-SHOCK-REVERSAL-01` |
| checkpoint | `ARC03-PREREG-001` |
| ARU identity | `ARC-03` — *Participation shock reversal*, class `EXPERIMENT`, `PIT_SAFE_EASY` |
| market | Binance USD-M USDT-margined perpetual |
| assets | `BTCUSDT`, `ETHUSDT`, `SOLUSDT` |
| data authority | `docs/arc03-data-authority-01/ARC03_DATA_AUTHORITY.json` (commit `8668a31`) |
| dataset fingerprint | `1a6ad11712ce436ce9d413d6b53162d66996778cd98643ef7c3eb746a54745ef` |
| common causal window | `2020-09-14T07:00:00Z` → `2026-08-31T23:55:00Z` (closed, on 5m bar-open times) |
| mechanism authority | `ARC03_MECHANISM_AUTHORITY.md` |
| spec | `ARC03_SPEC_V1.json` |
| manifest | `ARC03_MANIFEST_V1.json` |

## 2. The claim

> When a completed 5m bar records a **participation record** (volume strictly greater than
> the same 5m slot on each of the previous 30 calendar days), **and** an **excursion record**
> against the same reference set, **and** closes against its own push having given back
> **strictly more than half** of that bar's range, then the next 60 minutes contain a
> reversal in the direction of the rejected push.

**Who pays:** the urgent liquidity takers who crossed the book to move price at the extreme
and failed to hold it. This is the frozen ARU claim, not an inference from outcomes.

**Direction (contrarian to the rejected push):** up-push rejected → **SHORT**;
down-push rejected → **LONG**.

**What ARC-03 is not:** not a generic mean-reversion pattern (an abnormal participation
record is required), not a volatility trade (the range is the excursion that must be given
back, not a tradable state), not H5 (H5 is *with* the aggressive flow on 1h bars using
taker-side order-flow imbalance; ARC-03 is *against* the failing push on 5m bars using base
volume only), not carry, not OI, not regime, not cross-asset.

## 3. Frozen implementation (no implicit parameter anywhere)

| Element | Frozen value | Basis |
| --- | --- | --- |
| decision cadence | one decision per **completed 5m bar**, per asset | the signal is a property of one bar; its close is the first instant it is complete |
| participation field | `volume` (`v`, base units) | ARU: *"5m volume"* |
| participation shock | `v(t) > max{ v(t − 86400000·j) : j = 1..30 }` | ARU: *"fixed abnormal-volume percentile"* = 100th percentile of a 30-sample **same-slot** reference set |
| reference requirement | all **30** same-slot references present, else fail closed | no synthesis, no partial admission |
| excursion record | `high − low > max{ range(ref) }` over the same 30 references | the price response must be *disproportionate*, not merely present |
| exhaustion | `body > 0 ∧ (high − close) > range/2` → **SHORT**; `body < 0 ∧ (close − low) > range/2` → **LONG** | strict majority retracement — the push failed to hold |
| price context | `PRICE_CONTEXT = NONE` beyond the OHLC that *is* the definition | no unforced filter added |
| entry | **OPEN of the first 5m bar with `open_time > decision_time`** | strictly causal; same-bar entry impossible |
| exit | **OPEN of the bar at `entry_open + 12 · 5m`** | one primary horizon: 60 minutes |
| holding | exactly **12 bars = 60 minutes** | transient flow absorption |
| STOP / TP | `NONE` / `NONE` | no optimisation surface |
| COOLDOWN | `NONE` | no parameter |
| overlap | `SKIP` while a position is open; no queue, no pyramiding; assets independent, max 1 per asset | one position per asset |
| costs | primary round trip **10 bps**; frozen scenarios `0 / 10 / 20 / 40` on an **identical** trade set | program standard |
| funding | **applicable as CASHFLOW only**: 60-minute holds can straddle settlements, so `sum(−direction_sign · funding_rate)` over certified settlements in `(entry, exit]` | declared ex ante; funding is never a signal input |

### 3.1 Deterministic NO_SIGNAL precedence

```
OUTSIDE_COMMON_WINDOW
REFERENCE_HISTORY_INCOMPLETE
NO_PARTICIPATION_SHOCK
NO_EXCURSION_RECORD
NO_EXHAUSTION
POSITION_ALREADY_OPEN
INSUFFICIENT_FORWARD_PRICE_DATA
```

First satisfied reason wins. `NO_SIGNAL` is a first-class, counted, reported outcome.

### 3.2 Accounting identity

```
NET = GROSS + FUNDING − COST
NET_EX_FUNDING = GROSS − COST
```

`G3` uses `GROSS − COST` with **zero** funding contribution, so ARC-03 cannot pass merely by
mechanically collecting funding carry.

## 4. Critical discovery gates

`G1` sample (`N ≥ 120`, each asset `≥ 40`) · `G2` net expectancy `> 0` @10 bps ·
`G3` ex-funding expectancy `> 0` · `G4` profit factor `≥ 1.15` · `G5` annualized Sharpe
`≥ 0.50` · `G6` bootstrap 95% lower bound of the mean net return `> 0` (10,000 draws, seed
`20260915`) · `G7` one-sided sign-flip permutation `p ≤ 0.05` (10,000 draws, seed
`20260915`) · `G8` temporal stability (both halves `> 0`, `≥ 3/4` quartiles `> 0`) ·
`G9` asset stability (`≥ 2/3` assets positive) · `G10` concentration (asset `≤ 60%`,
UTC-entry-month `≤ 40%`, single trade `≤ 25%`) · `G11` cost sensitivity (`> 0` @20 bps and
`≥ 0` @40 bps).

**All gates are required.** No single metric is sufficient. Full computational semantics are
frozen in `ARC03_STATISTICAL_GATES.json`.

ARC-01 was admitted only because its estimator conventions could be back-solved from a
pre-existing repository module. ARC-03 does not rely on that: every convention (ddof,
annualization factor, window span, bootstrap statistic / resampling unit / index formula /
seed, permutation statistic / sidedness / p-value formula / seed, split boundaries,
concentration attribution and its zero-denominator behaviour) is stated in full in the gates
file and is reproducible from the frozen spec alone.

## 5. Falsification controls

| Control | Definition | Purpose |
| --- | --- | --- |
| `DIRECTION_CONTROL` | identical primary signal set, direction reversed (with the push) | is the contrarian direction load-bearing? |
| `TIMING_CONTROL` | identical primary signal set, entry displaced `+12` bars (+60 min) | is the edge specific to the shock's immediate aftermath? |
| `PARTICIPATION_CONTROL` | participation condition **removed**; only excursion record + exhaustion | does the abnormal-participation condition add anything at all? |
| `NULL_CONTROL` | deterministic sign flip of realized net returns, seed `20260915` | would a mechanical sign artifact satisfy the gate set? |

Controls are **not** alternate strategies, are **never promotable**, and cannot change the
primary thresholds or trade set. **If any required control satisfies ALL critical gates, the
mechanism is not identified and the outcome is `DISCOVERY_FAIL`.**

The `TIMING_CONTROL` is deliberately one-sided: advancing the entry would violate the PIT
contract, so a symmetric negative displacement is not admissible.

## 6. Kill rule

```
ONE PREREGISTRATION  →  ONE PRIMARY DISCOVERY
```

If any required critical gate fails, or the sample is insufficient, or a control satisfies
all gates:

```
ARC03 = DISCOVERY_FAIL   (terminal)
```

No threshold retuning. No lookback retuning. No holding-period retuning. No asset deletion.
No rerun under this `hypothesis_id`. Any variant requires a **NEW_HYPOTHESIS_ID** and a
**NEW_PREREGISTRATION**.

## 7. Orthogonality and stage ordering

The ARU records `collision = MEDIUM with H5` and a kill rule of *"net ≤ 0 or collision with
H5"*. Primary discovery must remain performance-blind, so orthogonality is **staged after**
discovery: it is evaluated in `ARC03_ROBUSTNESS_OOS_01` (authorized only after
`DISCOVERY_PASS`) with frozen thresholds (`|daily PnL correlation| ≤ 0.5`, trade-time
Jaccard `≤ 0.5`). Failing the H5 check is a **FAIL-class outcome for ARC-03**, never a
redesign prompt, and ARC-03's parameters remain frozen throughout.

Structurally, ARC-03 and H5 are opposite-signed on any shared window (against the failing
push vs with the aggressive flow) and never read a shared field (base volume vs taker-side
imbalance).

## 8. Robustness (frozen, NOT executed)

Reference-length grid `10/20/30/60` days, holding grid `6/12/24/36` bars, cost curve
`0/10/20/40` bps, time splits, asset splits and leave-one-out, causal volatility-regime
terciles, a fully reported parameter surface, and concentration re-analysis. **The primary
is always 30 days / 12 bars.** Robustness cannot select a better parameter set; a passing
neighbourhood cell when the primary fails is `POST_HOC_LEAD_ONLY` and cannot be promoted.
The out-of-sample protocol is deliberately not frozen here (a window split would change the
primary trade set) and must be frozen before execution in `ARC03_ROBUSTNESS_OOS_01`.

## 9. Failure memory

ARC-01 is recorded as immutable failed research memory:

| Field | Value |
| --- | --- |
| experiment | `ARC01_PRIMARY_DISCOVERY_01` |
| final | `DISCOVERY_FAIL` |
| state | `KILLED_FOR_THIS_HYPOTHESIS_ID` |
| result commit | `70c2849534f2119b84a73238009d13f967398436` |
| reason | positive net expectancy was explained by funding carry; ex-funding price expectancy negative; multiple critical gates failed |
| BTC-positive subcell | `POST_HOC_LEAD_ONLY` — do not adopt, do not retest as ARC-01 |

This memory may prevent rediscovering the same failed mechanism. It may **not** be used to
tune ARC-03: funding and open interest are not read at all by the ARC-03 signal.

## 10. Limitations (disclosed before observation)

1. The rule is parameter-free; the only length-like constant is the 30-day same-slot
   reference, frozen from the seasonality argument and probed only by the robustness plan.
2. The common window starts at SOL's admission (`2020-09-14`), so earlier BTC/ETH history is
   deliberately outside the evaluated window.
3. SOLUSDT `2022-02` and `2022-04` had provider archive gaps that were filled from official
   daily archives; the affected months are disclosed in `ARC03_DATA_QUALITY_LEDGER.jsonl`.
4. Provider schema change: monthly archives carry a header row from `2022-01` onward (SOL
   `2022-03` excepted); the normalizer detects it by exact match.
5. The last 60 minutes of the common window yields no trades (frozen forward-data guard).
6. Funding cashflow is charged on the entry notional (frozen `O(1e-4)` simplification).
7. A 60-minute hold creates many short-lived positions; aggregation is equal-weighted per
   trade and no portfolio-level risk overlay is frozen at discovery.
8. **No critical gate covers drawdown.** Drawdown is a diagnostic output only. This is
   disclosed rather than papered over: no drawdown threshold may be invented after seeing a
   result, and a promotion stage is free to require one.
9. `N` is a discovery-time unknown; `INSUFFICIENT_SAMPLE` is a possible terminal outcome.
10. The H5 collision check required by the ARU kill rule cannot be evaluated at the primary
    discovery stage without contaminating it, so it is frozen as an immediately following
    authorized gate.

## 11. Definition of done for this checkpoint

```
ARC03_SPEC_COMPLETE                          = PASS
DATA_AUTHORITY                               = PASS
PIT                                          = PASS
A_B_DETERMINISM                              = PASS
MUTATION_SENSITIVITY                         = PASS
PORTABLE_VERIFIER                            = PASS
CLEAN_WORKTREE_DATA_VERIFICATION             = PASS
ECONOMIC_PARAMETERS_FROZEN                   = true
STATISTICAL_GATES_FROZEN                     = true
CONTROL_PLAN_FROZEN                          = true
ROBUSTNESS_PLAN_FROZEN                       = true
KILL_RULE_FROZEN                             = true
PREREG_COMMIT_CREATED                        = true
POST_FREEZE_ARTIFACT_DRIFT                   = 0
ARC03_BACKTESTS = 0   ARC03_EXECUTIONS = 0   ARC03_PERFORMANCE_OBSERVED = false
FALSE_SUCCESS                                = 0
NEXT = ARC03_INDEPENDENT_PREREG_VERIFICATION
```
