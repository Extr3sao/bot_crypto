# RFC-049 DISCOVERY 2 — FINAL REPORT

> Mandatory final report of the Phase B execution instructed by the operator. It separates
> **IMPLEMENTED / TESTED / EXECUTED / VERIFIED / CERTIFIED** and invents nothing: every
> number below exists in the linked artifacts, and every non-executed control is named.

## 1. HEAD and commits

- **HEAD at run start and end** (checkout not moved): `2d113a0ae82f38123eabe0385ab47bb7991b15ad`,
  branch `main`. Every artifact records this head.
- **Commits made by this phase**: none. The artifacts in §2 are complete in the working tree but
  **uncommitted** — committing is the operator's call, so `git status` (not `git log`) is the
  authority on their state: `M tasks/decisions.md`, `M data/rfc049/admission/INDEPENDENT_VERIFICATION.json`
  (DEF-01 re-run only), and the new untracked `data/rfc049/discovery2/`, `scripts/rfc049c_*.py`,
  `tests/unit/research/test_rfc049c_discovery2.py`.
- **Historical artifacts not rewritten**: Phase A (`BASELINE_AUDIT`, `PREREGISTRATION_MANIFEST`,
  `DATA_EXPOSURE_AUDIT`, `ECONOMIC_RESULTS` = NOT_RUN, `ROBUSTNESS_REPORT` = NOT_RUN) and all
  `data/rfc049/admission/*` evidence (except the verifier's own re-run artifact, DEF-01) are
  byte-identical to their commits. The specs and vendor snapshots were inputs and were verified
  by hash at every run.

## 2. Files written or modified

| file | kind |
| --- | --- |
| `data/rfc049/discovery2/DISCOVERY2_EXECUTION_PLAN.md` | prerregistration, written **before** any economic computation |
| `data/rfc049/discovery2/CAMPAIGN_AUTHORIZATION.json` | governance decision record (ADR-0025) |
| `data/rfc049/discovery2/DISCOVERY2_STATISTICAL_ELIGIBILITY.json` | FASE 2 synthesis |
| `data/rfc049/discovery2/ECONOMIC_RESULTS.json` + `trades/*.json` | FASE 3 results and ledgers |
| `data/rfc049/discovery2/FILTER_ABLATION.{md,json}` | FASE 4 diagnostic |
| `data/rfc049/discovery2/ACTIVE_STRATEGY_STATUS.{md,json}` | FASE 5 audit |
| `data/rfc049/discovery2/INDEPENDENT_VERIFICATION.json` | FASE 6 verdict |
| `data/rfc049/discovery2/RUN_REPORT.{md,json}` | this phase's run record |
| `data/rfc049/discovery2/CAMPAIGN_CLOSURE.{md,json}` | governance closure of the campaign + the sealed-OOS resolution (ADR-0026) |
| `data/rfc049/discovery2/FINAL_REPORT.md` | this document |
| `scripts/rfc049c_engine.py`, `rfc049c_verify.py`, `rfc049c_ablation.py`, `rfc049c_active_audit.py` | builder, verifier, ablation, audit |
| `tests/unit/research/test_rfc049c_discovery2.py` | 15 contract tests |
| `tasks/decisions.md` | ADR-0025 appended |
| `data/rfc049/admission/INDEPENDENT_VERIFICATION.json` | verifier re-run only (DEF-01 correction) |

Nothing outside these paths was staged or modified; the worktree's pre-existing changes
owned by other lanes were left untouched.

## 3. Tests executed and results

| command | exit | result |
| --- | ---: | --- |
| `python scripts/rfc049b_verify.py` | 0 | PASS 66/0, 12 controls, FALSE_SUCCESS 0 |
| `python scripts/rfc049c_engine.py --trades` | 0 | 28/28 checks (hashes, grid, costs, counts, PIT) |
| `python scripts/rfc049c_verify.py` | 0 | **PASS 37/37, 8/8 controls DETECTED, FALSE_SUCCESS 0** |
| `python scripts/rfc049c_ablation.py` | 0 | base reproduces the trend comparator exactly |
| `python scripts/rfc049c_active_audit.py` | 0 | 5/5 checks |
| `python -m pytest tests/unit/research -q` | 0 | **1703 passed** (incl. 15 new) |

`TEST_TARGET == RUNTIME_TARGET`: the cost plane is the frozen runtime library
(`trading_bot.research.microstructure.cost_model_v3`), used by the engine and re-derived by
the verifier; `BUILDER != VERIFIER`: the verifier shares no code with the builder and never
imports it (asserted in tests).

## 4. Experiments executed and pending

**Executed (offline, RESEARCH_EXPOSED):** DEV/VAL economic runs of both frozen candidates on
BTC and the ETH replication; the robustness battery (1.5x stress, sub-window sign stability,
LCB block sensitivity, incremental tests vs buy-and-hold, 200-day trend baseline and each
other; BH/Holm across the two hypotheses); the four-arm filter ablation; the ACTIVE audit.

**Pending by contract (not executed, not bypassed):** the sealed forward OOS opening — since
ADR-0026 `CANCELLED_NOT_OPENED`, retired unread with the closed candidates — paper promotion
(separate gate), live trading (disabled), and any new hypothesis for higher-frequency
strategies (a new budget and a new authorization would be required; none was created).

## 5. State of H-049-001 and H-049-002

- **Both: `CANDIDATE_REJECTED` at the DEV/VAL stage** (policy §6: a candidate that fails a
  stage is closed at that stage). The registered `failed_criteria` in `ECONOMIC_RESULTS.json`
  are, for H-049-001: `lcb_95_net_expectancy_positive:validation`,
  `max_drawdown_le_0.25:development`, `max_drawdown_le_0.25:validation`,
  `single_trade_share_le_0.4:validation`, `incremental_over_buy_and_hold_positive:validation`,
  `incremental_over_200d_trend_baseline_positive:validation`; for H-049-002:
  `lcb_95_net_expectancy_positive:validation`, `max_drawdown_le_0.25:validation`,
  `single_trade_share_le_0.4:development`, `incremental_over_buy_and_hold_positive:validation`,
  `incremental_over_200d_trend_baseline_positive:validation`. In other words: on the
  validation partition both fail the one-sided LCB, the drawdown limit and both incremental
  tests; the single-trade concentration limit fails on validation for H-049-001 and on
  development for H-049-002. Separately, as **robustness flags** (not acceptance criteria),
  H-049-001 carries `PARTIAL_SIGN_STABILITY:development` and `SIGN_UNSTABLE:validation`, and
  H-049-002 carries `PARTIAL_SIGN_STABILITY:validation`.
- **Technical validity was never the problem**: PIT violations 0, input semantics verified in
  RFC-049B, rules reproduced exactly (14/9/23 and 26/22/48 round trips).
- No threshold, rule, partition or cost was changed; no re-tune, no refill.

## 6. Observed economic result (RESEARCH_EXPOSED; not confirmatory)

Both candidates made a large net result in 2019–2023 (H-049-001 +39,427 bps / 14 trips,
compounded +1,035%, LCB +659 bps; H-049-002 +40,176 bps / 26 trips, compounded +1,286%, LCB
+380 bps) and **decayed to non-confirmatory in 2024–2026**: raw sums stay positive for BTC
(+624 and +1,632 bps) but compounding turns negative for H-049-001 (−1.1%), the LCBs are
negative (−620 / −294 bps), drawdowns breach the 25% limit (27.9% / 35.2%) and both lose to
buy-and-hold (−9,788 / −9,281 bps) and to the 200-day trend machine (−761 / −254 bps). The
ETH replication turns **negative** in validation for both. Under the frozen acceptance list,
neither candidate can pass; **profitability is not verified and no PASS is emittable**.

## 7. OOS eligibility

At the measured turnover the sealed OOS gate is unreachable inside its frozen 24-month
window: **H-049-001 expects 5.9 round trips (81.0 months to 20); H-049-002 expects 12.4
(38.8 months to 20)**; both are `INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION`. Promotion as
independent strategies is stopped for both; the 20-trip floor was not lowered. With both
candidates closed at DEV/VAL, the sealed opening is moot: **resolved by ADR-0026 as
`CANCELLED_NOT_OPENED`** — the window is never read and the single licensed inspection is
retired unused rather than spent on a candidate that can no longer be promoted. See
[CAMPAIGN_CLOSURE.md](CAMPAIGN_CLOSURE.md).

## 8. ACTIVE status and real operation frequency

Real frequency: **0 operations/day**. 24 strategies, 0 admitted (`PAPER_ACTIVE = 0`), 0
paper-executable on 5m/15m/1h, 0 proposals, 0 authorizations, 0 fills; every cycle ends
`NO_TRADE_STRATEGIC` by construction. The 3-operations/day objective is assessed
`NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE`: at 23.35 bps per round trip it would cost
~255.7% of stake per year in costs, and the best measured family gross edge is 8.91 bps/trade.
No operation is forced to satisfy a quota. The low-frequency liquidity line (2.96–6.18 trips
per year) stands separate; the operator label `R6 P2 QUALITY` has no artifact in the
repository and is recorded as such.

## 9. Blockers and open defects

- **Open (governance)**: decision on cancelling the moot sealed-OOS opening; any future
  campaign needs a new explicit authorization and a new hypothesis budget.
- **Open (evidence)**: none blocking. The vendor revision risk for forward data and the nine
  RFC-049B defects remain as recorded; `RFC049C-DEF-01` (stale hashes in RFC-049B's verifier
  artifact) was corrected in this phase by the re-run.
- **Assumptions recorded**: macro availability modelled at the declared minimum lag
  (Wednesday + 1 day; real releases are later; cutoff is ~3.5 days after — no look-ahead
  possible at this cadence); bootstrap block length mapped 7 days → 1 trip for these
  multi-week rules, with 2/3-trip sensitivity reported (no sign flip).

## 10. FALSE_SUCCESS

**0** — 66+28+37 builder/verifier checks with 20 negative controls (12 + 8) all detected; no
result was manufactured, no file faked, no threshold moved after seeing results.

## 11. Next RFC / work package based on the evidence

1. ~~**Close RFC-049 Discovery 2 with a negative result**~~ — **done by ADR-0026**: the campaign
   is closed in the terminal state `DISCOVERY_CAMPAIGN_FAILED`, both candidates are closed at
   DEV/VAL with promotion stopped, and the moot sealed OOS opening is resolved as
   `CANCELLED_NOT_OPENED` (recorded in [CAMPAIGN_CLOSURE.md](CAMPAIGN_CLOSURE.md)).
2. **Default route**: wait for qualified external evidence (the pre-existing default); do not
   reopen the closed families and do not refill the hypothesis budget.
3. **If internal discovery continues, it must be a new campaign** with a new budget and an
   explicit authorization whose entry condition is mechanical: a mechanism whose
   turnover-adjusted gross edge is expected to clear **23.35 bps per round trip** at its own
   cadence. The evidence here says the intraday families (24 tested) do not; the liquidity
   line decays into the trend proxy it was supposed to augment. No such hypothesis is
   proposed or created by this report.

## 12. Evidence index

`ECONOMIC_RESULTS.json` (metrics, incrementals, BH/Holm) · `trades/*.json` (ledgers) ·
`DISCOVERY2_STATISTICAL_ELIGIBILITY.json` · `FILTER_ABLATION.{md,json}` ·
`ACTIVE_STRATEGY_STATUS.{md,json}` · `DISCOVERY2_EXECUTION_PLAN.md` (frozen before the run) ·
`CAMPAIGN_AUTHORIZATION.json` · `INDEPENDENT_VERIFICATION.json` · `RUN_REPORT.{md,json}`.

```text
CURRENT_HEAD              = 2d113a0 (unchanged; artifacts complete but uncommitted)
HYPOTHESIS_001            = CANDIDATE_REJECTED at DEV/VAL (frozen criteria; details in ECONOMIC_RESULTS)
HYPOTHESIS_002            = CANDIDATE_REJECTED at DEV/VAL
SEALED_OOS                = CANCELLED_NOT_OPENED (ADR-0026; retired unused, never read)
PAPER_PROMOTION           = NOT_AUTHORIZED
LIVE_TRADING              = DISABLED
TRADES_AUTHORIZED         = 0
OOS_OPENED                = FALSE
PROFITABILITY_VERIFIED    = FALSE
FALSE_SUCCESS             = 0
INDEPENDENT_VERIFICATION  = PASS (37/37, 8/8 controls)
CAMPAIGN_STATE            = DISCOVERY_CAMPAIGN_FAILED (declared CLOSED by ADR-0026)
HYPOTHESIS_BUDGET         = EXHAUSTED_NO_REFILL
NEXT_CAMPAIGN             = NOT_AUTHORIZED
NEXT_GATE                 = none: the campaign is closed; any new work needs a new authorization and a new budget
```
