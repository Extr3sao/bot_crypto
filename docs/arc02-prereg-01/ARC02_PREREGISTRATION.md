# ARC-02 PREREGISTRATION — BTC → ALT LEAD-LAG

* **hypothesis_id:** `ARC-02-BTC-ALT-LEAD-LAG-01`
* **checkpoint:** `ARC02-PREREG-001`
* **status:** `PREREGISTERED_NOT_EXECUTED`
* **builder:** deepseek-v4-flash (DeepSeek) — **BUILDER, not independent verifier**
* **final builder state:** `PENDING_INDEPENDENT_PREREG_VERIFICATION`
* **economics at freeze:** `ARC02_BACKTESTS = 0`, `ARC02_EXECUTIONS = 0`,
  `ARC02_PERFORMANCE_OBSERVED = false`, `FALSE_SUCCESS = 0`

> One preregistration → one primary discovery. No threshold, lookback, ratio, holding-period,
> asset or cost change is permitted after a failure under this hypothesis id.

## 1. Mechanism

A sufficiently unusual **completed** BTC 5m move, together with a follower (ETH/SOL) that has
moved in the SAME direction but has not yet responded proportionally, predicts follower
continuation in the shock direction.

```
BTC_SHOCK(t) AND SAME_SIGN(t) AND FOLLOWER_UNDERREACTION(t)
    -> LONG follower  if r_btc(t) > 0
    -> SHORT follower if r_btc(t) < 0
```

Who pays: latency-constrained and segmented participants who reprice the follower only after
the leader has already moved. See `ARC02_MECHANISM_AUTHORITY.md`.

## 2. Frozen primitives

| Primitive | Frozen definition |
| --- | --- |
| leader return | `r_btc(t) = ln(close_btc(t) / close_btc(t − 300000 ms))` |
| trailing scale | `s(t) = median(|r_btc(t − j·300000)| : j = 1..288)` — 288 references, **all required**; even-count median = mean of the two central order statistics; **no location estimator** |
| shock statistic | `z(t) = r_btc(t) / s(t)` |
| `BTC_SHOCK(t)` | `abs(z(t)) > 3.0` (**strict**) |
| follower return | `r_f(t) = ln(close_f(t) / close_f(t − 300000 ms))` |
| `SAME_SIGN(t)` | `r_btc(t) · r_f(t) > 0` (both strictly non-zero) |
| `FOLLOWER_UNDERREACTION(t)` | `abs(r_f(t)) < 0.5 · abs(r_btc(t))` (**strict**) |
| decision time | `max(leader close, follower close)` at the aligned slot |
| entry | **open** of the next 5m follower bar (`open_time > decision_time`) |
| exit | **open** of the follower bar 5 minutes after entry (1-bar hold) |
| stop / take-profit / cooldown | NONE |
| overlap | SKIP; re-entry only after the previous exit; ≤ 1 position per follower, ≤ 2 overall; BTC never traded |
| costs | primary `10 bps` round trip; scenarios `0/10/20/40 bps` on the **identical** trade set |
| funding | cashflow only, over `(entry, exit]`, on the traded follower; never a signal |
| returns | `NET = GROSS + FUNDING − COST`, with the ex-funding leg reported separately |

Fail-closed outcomes are first-class and deterministic; the precedence order is frozen in
`ARC02_SPEC_V1.json#signal_rules.deterministic_no_signal_precedence`.

## 3. Data authority (reuse-first)

* **Reused, not downloaded:** the certified ARC-03 5m Binance USD-M kline authority
  (dataset `1a6ad117…45ef`), proved byte-identical by partition SHA256 equality.
* **ARC-02 projection** (`t, ct, o, c` only) — dataset
  `03f227d0ae18efdc8e3d84831283c4e3f7a333bf0fea8b944f55a9144cc164d5`.
* **Common causal window:** `2020-09-14T07:00:00Z` → `2026-08-31T23:55:00Z` (full reusable
  history; span 2177.7083333333335 days, a frozen constant).
* Zero credentials, zero cost, zero downloads. Raw 237 archives CHECKSUM-verified.
* `h, l, v, qv, n, tb, tq` are **absent from the projection**: ARC-02 structurally cannot read
  the H5 order-flow family or the ARC-03 participation field.
* Determinism: A/B identical digests (independent subprocess, different output root);
  mutation sensitivity PASS on a TEMP copy with the canonical authority untouched.
* Portability: `ARC02_DATA_ROOT` explicit absolute root; wrong root and empty root both fail
  closed; no machine-specific absolute path participates in dataset identity.

## 4. Statistical gates G1–G11 (frozen)

| Gate | Requirement |
| --- | --- |
| G1 sample | `N ≥ 120` AND `min(N_ETH, N_SOL) ≥ 40` |
| G2 net expectancy | `mean(net @10bps) > 0` |
| G3 ex-funding expectancy | `mean(gross − cost @10bps) > 0` |
| G4 profit factor | `PF ≥ 1.15` |
| G5 Sharpe | annualized `≥ 0.50` (ddof 1, `sqrt(trades_per_year)`, frozen window span) |
| G6 bootstrap | 95% percentile CI lower bound `> 0` (10 000 draws, seed 20260915) |
| G7 permutation | one-sided sign-flip `p ≤ 0.05` (10 000 draws, seed 20260915, mean statistic) |
| G8 temporal stability | both halves `> 0` AND `≥ 3 of 4` quartiles `> 0` |
| G9 follower stability | **BOTH** followers' mean `> 0` (adapted 2-of-2 rule, see rationale) |
| G10 concentration | follower share `≤ 0.70`, month share `≤ 0.40`, single trade `≤ 0.25` |
| G11 cost sensitivity | `mean @20bps > 0` AND `mean @40bps ≥ 0` |

Every estimator convention (ddof, annualization, bootstrap statistic/unit/replacement/draws/
seed/CI formula, permutation statistic/tail/p-value formula, split semantics, UTC attribution,
non-positive denominator behaviour) is stated in `ARC02_STATISTICAL_GATES.json`.

**Pass = G1…G11 all pass AND no control satisfies all critical gates.**

## 5. Controls (frozen, executable, never promotable)

| Control | Executable definition |
| --- | --- |
| `DIRECTION_CONTROL` | same signal set and timestamps; reverse the follower direction sign only |
| `TIMING_CONTROL` | same signal set; displace entry/exit by `+1` bar (+5 min, the causal direction only) |
| `LEADER_CONTROL` | leader driver series displaced `288` bars (24 h): contemporaneous leader information destroyed, every follower execution semantic unchanged |
| `NULL_CONTROL` | `random.Random(20260915)` sign flip of realized net returns (`hash()` forbidden) |

A control satisfying ALL critical gates ⇒ `MECHANISM_NOT_IDENTIFIED` ⇒ `DISCOVERY_FAIL`.

## 6. Robustness (frozen, NOT executed)

Time splits, follower splits, regimes, cost curve, lookback neighbourhood {144, 288, 576, 864},
threshold neighbourhood {2.5, 3.0, 3.5, 4.0}, ratio neighbourhood {0.33, 0.50, 0.67, 0.80},
holding neighbourhood {1, 3, 6, 12}, leave-one-follower-out, walk-forward (no refit),
concentration. A robustness cell can never replace the primary cell.

## 7. Kill rule

Any critical gate failure, insufficient sample, or a control passing all gates ⇒
`ARC02 = DISCOVERY_FAIL` (terminal). Forbidden afterwards: threshold/lookback/ratio/holding
retune, asset deletion, cost reduction, a second economic attempt under the same hypothesis id.
A variant requires a **NEW_HYPOTHESIS_ID** and a **NEW_PREREGISTRATION**.

## 8. Collision review

`ARC02_FAILED_MEMORY_COLLISION_REVIEW.md` — H1 LOW, H3 **MEDIUM** (shared assets, opposite
directional logic), H5 LOW, H6 LOW, ARC-01 LOW, ARC-03 LOW. The H3 overlap is documented, is
**not** resolved by tuning, and H3 is frozen as a mandatory orthogonality comparator at the
later authorized stage. No failed outcome was used to choose any ARC-02 number.

## 9. Limitations

See `ARC02_SPEC_V1.json#limitations`. The material ones: the prior ARC-02 definition was
`DRAFT_ONLY` (so definitions are re-frozen rather than preserved), the first 289 slots produce
no decisions (incomplete leader history, fail closed), the last two slots produce no trades
(frozen forward guard), funding is charged on the entry notional, no gate covers drawdown, and
N is a discovery-time unknown.

## 10. Artifact index

| Artifact | Purpose |
| --- | --- |
| `ARC02_SPEC_V1.json` | the frozen spec (single source of truth) |
| `ARC02_MANIFEST_V1.json` | artifact digests + economic guards at freeze |
| `ARC02_STATISTICAL_GATES.json` | G1–G11 + every estimator convention |
| `ARC02_CONTROL_PLAN.json` | the four falsification controls |
| `ARC02_PIT_CONTRACT.json` | 15 PIT clauses |
| `ARC02_ROBUSTNESS_PLAN.json` | frozen, unexecuted robustness cells |
| `ARC02_MECHANISM_AUTHORITY.md` | mechanism contract |
| `ARC02_SELECTION_RATIONALE.md` | why each number, and what was NOT chosen |
| `ARC02_FAILED_MEMORY_COLLISION_REVIEW.md` | collision analysis |
| `ARC02_PREREG_VERIFICATION_PACKAGE.json` | everything the independent verifier needs |
| `ARC02_RESUME_STATE.json` | durable state handoff |
| `ARC02_PREREG_COMMIT_POINTER.json` | the prereg commit SHA |
| `RUN_REPORT.json` / `RUN_REPORT.md` | builder-phase report |
| `../arc02-data-authority-01/*` | data authority, PIT battery, portable verification |

## 11. Next step

`ARC02_INDEPENDENT_PREREG_VERIFICATION` — performed by an independent verifier, never by this
builder. The builder stops here.
