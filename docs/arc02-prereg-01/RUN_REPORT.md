# ARC-02 BUILDER RUN REPORT

* **hypothesis_id:** `ARC-02-BTC-ALT-LEAD-LAG-01`
* **checkpoint:** `ARC02-PREREG-001`
* **builder:** deepseek-v4-flash (DeepSeek) — **BUILDER, not independent verifier**
* **FINAL_STATUS:** `PENDING_INDEPENDENT_PREREG_VERIFICATION`
* **REALITY_CHECK_STATE:** `ARC02_PREREG_FROZEN`
* **BASE_COMMIT:** `e7f470d`
* **DATA_AUTHORITY_COMMIT:** `31cb53a`
* **PREREG_COMMIT:** `3ebf5f5`
* **SPEC_HASH:** `ef5d7619…afc40`
* **MANIFEST_HASH:** `62b1a8d5…1ff8b`

## 1. Reality check (from repository evidence, not summaries)

| Fact | Evidence |
| --- | --- |
| The ARC-02 worktree/branch existed at the frozen base | `.research/arc02-candidate-design-01` on `research/arc02-candidate-design-01` @ `e7f470d` |
| No committed ARC-02 definition existed | `git log --all --grep=ARC02/ARC-02 -i` → empty |
| The prior candidate design was untracked and DRAFT | `docs/arc02-candidate-design-01/` (`DRAFT_NOT_PREREGISTERED`, `data_authority: PENDING`) |
| Prior draft data was 2024-only | `data/raw/binance_usdm/arc02/**`, `data/processed/arc02_ohlcv_5m/**`, dataset `2a91ed26…ceed` |
| No ARC-02 economics had ever been observed | no execution artifacts anywhere; draft `performance_observed: false` |
| State determined | `ARC02_PREREG_IN_PROGRESS` → advanced to `ARC02_PREREG_FROZEN`; **`ARC02_ECONOMICS_ALREADY_OBSERVED` is false** |

No second primary discovery was created, because none existed. No protected component
(H1/H3/H5/H6/ARC-01/ARC-03/Risk/PaperBroker/StrategyRouter/Critic/MetaRanker/Shadow/
Confirmation/live runtime) was modified, and no unrelated worktree was merged.

## 2. Data authority (reuse-first, zero downloads)

Audit result: the certified **ARC-03 5m Binance USD-M kline authority** (`ARC03-DATA-001`:
237 provider-CHECKSUM-verified archives, 2020-09-14 → 2026-08-31) is `REUSABLE` for ARC-02,
proved by **partition SHA256 equality**, not asserted. The 2024-only draft inventory was
classified `REUSABLE_WITH_LIMITATION` and **superseded** (a broader official authority was
reusable without contamination). Consequence: the **full common causal history** is used, not
a convenient 2024 window.

* ARC-02 projection (`t, ct, o, c`) dataset:
  `03f227d0ae18efdc8e3d84831283c4e3f7a333bf0fea8b944f55a9144cc164d5`
* rows: BTC 701,280 · ETH 701,280 · SOL 627,180; common window
  `2020-09-14T07:00:00Z → 2026-08-31T23:55:00Z`
* `h, l, v, qv, n, tb, tq` are dropped → H5 order-flow and ARC-03 participation fields are
  **structurally unreachable**
* funding reused byte-identically (cashflow leg only; never a signal)
* `A_B_DETERMINISM = PASS` (independent subprocess, different output root, identical digest)
* `MUTATION_SENSITIVITY = PASS` (TEMP-copy mutation changes the fingerprint; canonical
  authority untouched)
* `PORTABILITY = PASS` (explicit absolute `ARC02_DATA_ROOT`; wrong root and empty root both
  fail closed)
* `PYTHON_IMPORT_AUTHORITY = PASS` (module resolves inside the audited worktree)

## 3. Verification evidence

| Check | Result |
| --- | --- |
| PIT adversarial battery | **39/39 PASS** (`ARC02_PIT_INDEPENDENT_TESTS.json`) |
| Exact-strict boundaries (z == 3.0, ratio == 0.5) | PASS — both rejected |
| Future-mutation invariance / past-mutation detectability | PASS |
| Portable data-authority verifier | 13/14 → 14/14 after the freeze commit (CLEAN_WORKTREE) |
| Spec validator | **16/16 PASS** (`ARC02_SPEC_VALIDATION.json`) |
| Unit tests | `tests/unit/research/test_arc02_prereg.py` + `test_arc02_data_authority.py` all pass |
| `POST_FREEZE_ARTIFACT_DRIFT` | 0 |
| `CLEAN_WORKTREE_VERIFICATION` | PASS (fresh detached worktree at the prereg commit) |
| `ARC02_BACKTESTS` / `ARC02_EXECUTIONS` / `ARC02_PERFORMANCE_OBSERVED` | 0 / 0 / false |
| `FALSE_SUCCESS` | 0 |

## 4. Deviations from the draft (recorded, not hidden)

* `minimum_observations` 144 → **288** (all references required; fail closed).
* exit anchor "that bar's close" → **the open of the bar 5 minutes after entry** (consistent
  open-anchored clock-arithmetic execution).
* funding `EXCLUDED_WITH_LIMITATION` → **frozen and charged** (a 5-minute hold can straddle a
  settlement).
* control set → the four executable controls (DIRECTION, TIMING, LEADER, NULL).

Every deviation is justified by mechanism, statistical convention, cadence or governance — none
by returns. There are no ARC-02 returns.

## 5. Defects and limitations

**Defects: none outstanding.** During the build, one PIT check ("misaligned slot") was found to
be mis-specified (it asserted a fail-closed reason for a slot that legitimately carries a later
signal); it was replaced with a correct leader-bar-absent check. One builder-side script defect
(the mutation test originally never read the mutated file) was found and fixed before the
authority artifacts were produced. Both were builder-internal and are recorded here rather than
hidden.

**Limitations:** see `ARC02_SPEC_V1.json#limitations` and `ARC02_RESUME_STATE.json#limitations`.

## 6. Next

`ARC02_INDEPENDENT_PREREG_VERIFICATION` (independent verifier; `ARC02_PREREG_VERIFICATION_PACKAGE.json`
lists exactly what to check and the adversarial attacks to attempt). No economics may run before
that verification passes.
