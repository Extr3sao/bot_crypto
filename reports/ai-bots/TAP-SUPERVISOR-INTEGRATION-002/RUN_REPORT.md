# RUN REPORT — TAP-SUPERVISOR-INTEGRATION-002

**Branch:** `integ/supervisor-002`, worktree `C:/Users/GVLLFR0035/Downloads/ff-wt-integ002`
**Base:** `main` = `e67194e7` (unchanged; verified before and after)
**Source of truth:** `audit/supervisor-integration-001` @ `a8abd83e`
**Verdict:** `NOT_READY` — one risk-policy signature outstanding (G1/D). Everything else is closed.

---

## 1. What was done, in one paragraph

The 47-route slice of `TAP-SUPERVISOR-INTEGRATION-001` was migrated into an isolated branch
by copying **Git blobs**, never merging the lane: 35 new modules, 7 modified files, 2 configs,
`pyproject.toml`, a regenerated `uv.lock`, a narrowed `.gitignore`, and 37 tests. Every route
is recorded in [ROUTE_MANIFEST.json](ROUTE_MANIFEST.json) with its lane blob, SHA-256, origin
commit, state and reason. Two gates were closed with code and evidence (G2: verifiers on real
campaigns; G3: B1 forced deterministically), two blockers were investigated to root cause
(B3: fixed; `finished_without_locks`), and one was corrected rather than closed (B2: the
script does not exist in either tree). Two **real PAPER campaigns** were executed without
credentials: a 5-cycle supervisor campaign with a crash and a resume (`STOP_COMPLETED`, 0
locks, `live_orders 0`), and the lock campaign's **full contract** — 6 crash sites, 2 reclaim
races, 17 cycles, 6 recoveries, exit 0 — whose verifier returns PASS with 32/32 checks and
9/9 mutations detected. The independent checker re-derives both from the artefacts and
returns **9/9 PASS** with `false_success = 0`.

## 2. Commits

| Commit | Content |
| --- | --- |
| `f238b632` | `matplotlib` declared **and pinned**; lock consistency test (B3) |
| `537e4990` | 47-route slice + 37 tests + the verifier's G2 compatibility |
| `b489d488` | G1 contract/parity tests (`tests/unit/risk/test_risk_contract_014.py`) |
| `HEAD` (this delivery) | G2 completion (applicability pinned, fence floor), B1 tests, full-contract lock campaign + its independent claim, reports |

No commit merges, cherry-picks or rewrites a lane commit; `git rev-list --merges main..HEAD`
is empty. `main` was not touched.

## 3. Route manifest — 84 routes, all hashed

| Group | Count | What it is |
| --- | ---: | --- |
| `slice` | 47 | the audit's slice: 35 missing modules, 7 divergent files, 2 configs, lock/dependency/ignore |
| `verification-tests` | 37 | tests that pin the migrated code; selection rule is static (every `trading_bot` import resolves on the branch) |
| **total** | **84** | reproduced by `tools/route_manifest.py --check` → `{"check": "PASS", "routes": 84}` |

`--check` re-reads every file from disk and compares its SHA-256 with the lane blob. Four
paths are declared edits rather than copies, and each is listed in
`post_migration_edits` with its reason: `uv.lock` (regenerated), `.gitignore` (narrowed),
`scripts/paper_supervisor_verify.py` (G2), `test_def_run_016_integrity.py` (two tests load a
script outside the slice and are skipped with that reason).

**No main-side work is reverted:** the four commits between the merge base and `main` touch 66
paths, and **none** of them is one of the 87 route paths (`evidence/MAIN_ONLY_OVERLAP.txt`).

## 4. Tests — measured, with the exact numbers

| Suite | Result | Log |
| --- | --- | --- |
| `tests/unit/paper tests/unit/risk` on **`main`** | **6 failed, 170 passed** | `evidence/PYTEST_paper_risk_main_baseline.log` |
| `tests/unit/paper tests/unit/risk` on **this branch** | **2 failed, 220 passed** | `evidence/PYTEST_paper_risk_after_tests.log` |
| `tests/unit/ops` | **76 passed** | `evidence/PYTEST_ops.log` |
| `tests/unit/vision` | **17 failed, 311 passed, 1 skipped**, 23 min 44 s | `evidence/PYTEST_vision_verbose.log` |
| 6 migrated `tests/unit/research` files | **14 failed, 159 passed** | `evidence/PYTEST_research_migrated.log` |
| `tests/unit/risk/test_risk_contract_014.py` (new) | **46 passed** | §5 |
| `tests/unit/ops/test_lock_attribution_b1.py` (new) | **6 passed** | §7 |
| `tests/unit/test_dependency_lock_consistency.py` (new) | **3 passed** (3 failed against main's lock — negative control) | §8 |

**No test that passes on `main` fails here.** The 2 remaining reds are a subset of main's 6.

### The 33 remaining failures, by cause (none invented, none hidden)

* **15 × `test_minute_quote_feed.py` (14) / `test_subbar_execution.py` (1)** — `data/quote-feed-1m/`
  is a lane-only corpus; the manifest the tests read is not in `main`.
  `FileNotFoundError: data/quote-feed-1m/SOURCE_MANIFEST.json`.
* **1 × `test_def_run_016_integrity.py`** — loads `scripts/def_run_016_verify.py`, outside the
  slice. **Now skipped** with the reason (10 passed, 2 skipped in that file); the count above
  predates the skip.
* **1 × `test_closed_trade_cycle.py::test_two_identical_runs_write_the_same_ledger`** —
  failed in the full-suite order (`fila 1 (RUN) diverge entre dos corridas idénticas`) and
  **passes in isolation** (measured, 4.8 s). Test isolation defect, not a determinism claim:
  declared FLAKY.
* **14 × 6 research files** — 10 × `test_alpha15_causality.py` (the 1h corpora are lane-only,
  0 bars read), 1 × `test_campaign_runtime.py::...pid...` (main's
  `research/campaign_lock._pid_probe` does not guard Windows `SystemError` — a real
  portability gap of a module **outside** the slice), 1 × `test_campaign_supervisor.py`
  (expects `pythonw.exe`, the slice does not carry the registration script), 2 ×
  `test_rfc046_activation_and_campaign.py` (missing lane data/scripts).
* **2 × `test_futures_independent_verifier.py`** — pre-existing on `main`, root cause below.

## 5. G1 — risk contract

**The audit's attribution was wrong, and the correction is the finding.** On *unmodified*
`main`, `tests/unit/paper tests/unit/risk` is **6 failed / 170 passed**, including both
`test_futures_independent_verifier.py` failures. They are caused by stale hashes in
`data/rfc048/PROVENANCE.json` (6 of 7 sources disagree with the committed raw files; the
bracket ladder content is reproducible), not by `risk/manager.py`. Status: **OPEN,
PRE-EXISTING ON MAIN**, not fixed here — rewriting the recorded hashes would launder a
provenance chain that never existed. Details: [RISK_CONTRACT_DELTA.md](RISK_CONTRACT_DELTA.md).

What the slice *does* change, exhaustively, is in that same document. Three changes tighten
(no stop invented by the broker; unusable stop refused instead of clamped; stop inside its
round trip refusable, `OFF` by default), and **one loosens**: the weekly veto now lifts at UTC
Monday 00:00 instead of never. That is deliberate (`WP-EDGE-017F/P0.1`), threshold unchanged,
tested at the boundary, mid-week, with a backwards clock and across a state round-trip.

**G1 status: `OPEN_SIGNOFF`** — the anomaly preserves every limit and the parity test proves
the arithmetic is unchanged, but a policy gate that used to hold forever now releases. That
is the risk-manager's call, not mine.

## 6. G2 — verifiers that judge real campaigns

**Before:** the supervisor verifier crashed on a real campaign (`scenarios/SCENARIOS.json`
missing, a fixture-only file), and a missing-evidence check was indistinguishable from a
failed one.

**After** (`scripts/paper_supervisor_verify.py`): applicability is computed once from the
campaign under judgement; a check whose evidence is absent is `NOT_APPLICABLE` and excluded
from the verdict; a mutation that cannot run is neither `invalid` nor `detected`; a mutation
that deletes the evidence its check needs is counted as **detected**, because the campaign no
longer proves the property. No `SCENARIOS.json` is fabricated.

**Measured on the real campaign** (`evidence/REAL_CAMPAIGN_VERIFICATION.json`, exit 0):

| Field | Value |
| --- | --- |
| Verdict | **PASS** |
| Checks | all PASS; 2 not applicable (`corrupt_evidence_was_refused`, `budget_was_exhausted_not_exceeded` — no fixture scenarios in a real campaign) |
| Applicable mutations | **10**, all detected |
| Not applicable mutations | 2 (same reason) |
| `false_success` | **0** |

Two verifier weaknesses were found by the adversarial run itself and fixed: a fence sequence
of length 1 made `reclaim_fences_advance` vacuously true (a fence reset to 0 went undetected),
and recomputing applicability per mutant let a mutation delete its own target check. Both are
now pinned: the fence floor is ≥ 2, and applicability is fixed before mutation.

**Negative controls** (each one re-run, exit 1, right check false):

| Copy | Verdict | Failed checks |
| --- | --- | --- |
| absent directory | FAIL | 11 checks, incl. `seq_continuous` |
| `live_orders = 1` in the stream | FAIL | `no_live_orders`, `stream_chain_intact` |
| leftover lock | FAIL | `no_lock_remaining_now` |
| broken `prev_sha256` | FAIL | `stream_chain_intact` |

Fixture behaviour is preserved: `tests/unit/ops/test_paper_supervisor_verifier.py` **4 passed**.

**Lock verifier** (`paper_lock_campaign_verify.py`) accepts its own producer's schema and
judges all 33 checks on a real 3-cycle / 1-crash lock campaign — it no longer refuses with
`UNSUPPORTED_CAMPAIGN_SCHEMA`, because that refusal was aimed at a *supervisor* campaign. On
that short campaign it fails 3 checks that encode the campaign's minimum shape
(`at_least_five_recoveries`, `both_crash_sites_covered`, `concurrent_reclaim_has_one_winner`),
which is the correct verdict: a 1-crash campaign is not the campaign's own contract.

**The full contract, executed** (`evidence/LOCK_CAMPAIGN_FULL2/`, `..._stdout.log`, exit 0):
6 crash sites (5 `after_cycle`, 1 `before_cycle`), 2 reclaim races, **17 cycles**, 12 session
starts, 64 stream rows, chain `INTACT`.

| Field | Value |
| --- | --- |
| Verdict | **PASS** (exit 0) |
| Checks | **32/32 true** |
| Mutations | **9/9 applicable, 9 detected**, 0 invalid |
| `false_success` | **0** |
| Recoveries / reclaim rows | 6 / 6, fences `2 → 5 → 8 → 11 → 14 → 17` |
| Races | iterations 2 and 5, exactly **1** reclaimer each |
| Locks at end | **0**; `live_orders 0` in every row |

**Why the first attempt aborted at iteration 5 (`B5`, explained, not a defect).** That run
had been launched while this branch was still being committed to; the resume was refused with
`COMMIT_CHANGED` — the session pins the runtime identity at `SESSION_START` and will not
continue under a different commit. That is the provenance guard doing its job, and it is the
only cause: the same campaign, re-run against a frozen `HEAD`, completed 6/6 iterations with
exit 0. The aborted artefacts are kept as `evidence/LOCK_CAMPAIGN_FULL1_aborted_stdout.log`
so the refusal is auditable rather than deleted.

**G2 status: `CLOSED`** for both verifiers — the supervisor verifier on the real campaign and
the lock verifier on a full-contract 6-recovery campaign with races.

## 7. G3 / B1 — the lock window, forced

Root cause, by construction: the lock is created with `os.link(tmp, path)` so the record is
complete the instant the file exists. Where hard links are refused, the fallback is
`O_CREAT|O_EXCL` **then** `write`, and a crash between those two syscalls leaves an empty file.
`_normalise("")` → `{"unattributed": True, "reason": "EMPTY"}` → `LOCK_UNATTRIBUTED`, refused
and **not deleted** — which is exactly the historical symptom.

`tests/unit/ops/test_lock_attribution_b1.py` (6 passed) proves:

1. 200 acquisitions: every visible lock is already a complete record (`token`, `pid`), size > 0;
2. the fallback writes a complete record too;
3. **forcing** `os.link` to fail and `os.write` to fail leaves the empty lock — and the next
   writer refuses it with `LOCK_UNATTRIBUTED`, deleting nothing;
4. an empty or unparsable lock on disk is refused, unchanged;
5. `os.link` is available where the locks live on this host (skips with the reason otherwise).

**Status: `DIAGNOSED`.** The window is closed on filesystems with hard links (measured here)
and deliberately *refused*, not recovered, where it is not. It is not "fixed everywhere", and
the 8 earlier non-reproductions are explained: the race needs the fallback plus a crash inside
two adjacent syscalls.

## 8. B2, B3, `finished_without_locks`, the suite timeout

* **B3 — `uv sync --frozen` false success: FIXED.** Reproduced: `uv lock --check` exit 1,
  then `uv sync --frozen` exit **0** with `ModuleNotFoundError: matplotlib`. After
  `uv lock`: `--check` 0, `--frozen` 0, `matplotlib 3.11.2` importable. A test reads
  `pyproject.toml` and `uv.lock` directly (no `uv`, no network) and **fails against main's
  lock** (3/3), so the false success cannot come back silently.
* **B2 — `verify_claims.py` portability: `NOT_REAUDITED`.** The script does not exist in
  `main` **nor in the lane** (`git cat-file -e codepaper/supervisor-001:scripts/verify_claims.py`
  fails), so there is nothing here to audit. Declared, not converted to PASS.
* **`finished_without_locks = false`: `NOT_REPRODUCED`.** This run reports `true` and exit 0.
  The flag is `wait_for(...)`'s boolean, i.e. *"a poll saw RECOVERED/READY with no locks
  before the timeout"*, not a verdict: a child that releases its last lock after
  `finish_timeout_s` yields `false` while `final.locks` (computed later) is empty — the exact
  combination the audit saw. Recommended fix (not applied, to avoid changing a producer that
  worked here): re-evaluate after `supervisor_process.wait()` returns.
* **Full `tests/unit`: `NOT_TESTED`.** The measured subsets take 23 min 44 s (vision) plus
  3 min 09 s (6 research files); no full-suite run was attempted, and none is claimed.

## 9. The real PAPER campaign

`scripts/paper_supervisor_campaign.py run --crashes 1`, no credentials, public market data.

| Fact | Value | Where |
| --- | --- | --- |
| Supervisor | `STOP_COMPLETED`, exit 0 | `CAMPAIGN.json.final.result` |
| Cycles | `[1, 2, 3, 4, 5]` | stream + campaign |
| Crash episodes | 1 (`after_cycle`) → resume | `episodes/episode-01.json` |
| Final state | `RECOVERED` | `CAMPAIGN.json.final.state` |
| Chain | `INTACT`, 13 rows | independent recomputation |
| Locks at end | **0** | `session/**/*.lock` |
| `live_orders` | **0** in every row | stream |
| Campaign exit | **0**, `finished_without_locks: true` | `evidence/CAMPAIGN_stdout.log` |
| Verifier | PASS, 10/10, `false_success 0` | §6 |

## 10. Independent verification

`tools/independent_verify.py` imports **nothing** from `trading_bot` and nothing from the
verifier: it re-implements the canonical hash, re-hashes every route and artifact, parses the
pytest logs and checks Git state. Result: **9/9 PASS, 0 FAIL, 0 UNKNOWN, `false_success 0`**
(`evidence/INDEPENDENT_VERIFICATION.json`, exit 0). Two self-controls require a FAIL on a
tampered copy — `S1` on the supervisor campaign, `S2` on the lock campaign with one
iteration's `RECOVERY.json` deleted — and both do FAIL, so neither checker is blind.

Claims checked: `G1` branch/base/main immutability; `R1` 84 routes hashed and declared edits;
`C1` campaign facts recomputed; **`L1` the 6-iteration lock campaign re-walked from its own
stream** (17 cycles, 6 reclaims whose fences advance, 6 `SESSION_END`, 6 resumes at exit 0, no
`*.lock`, no live order, and the verifier's counts must equal the recounted ones); `V1`
verifier report truthfulness incl. artifact hashes; `V2` four negative controls; `S1`/`S2`
self-controls; `T1` log numbers match this report.

`L1` earned its keep on the first run: it **failed** on the committed campaign because the
check itself demanded strictly increasing fences for the four locks *inside* one reclaim,
while a single reclaim takes them all over at the same fence. The campaign was right and the
checker was wrong; the check was corrected to compare fences across reclaim rows and to reject
a reclaim that mixes fences. Recorded here because a verifier that is only ever right is a
verifier nobody has tested.

## 11. Limitations and open items

1. **G1/D needs risk-manager sign-off** (weekly veto now rolls). `OPEN_SIGNOFF`.
2. **B2 `NOT_REAUDITED`** — script absent from both trees.
4. **`finished_without_locks` `NOT_REPRODUCED`** — code path identified, producer unchanged.
5. **15 vision failures are data-bound** (`data/quote-feed-1m` is lane-only) and **1 is flaky**
   under full-suite order; **14 research failures** are data/script/Windows-probe bound. None
   touches the supervisor's runtime path.
6. **No profitability claim.** Admission stays `NO_GO`; the ledger is untouched.
7. `data/rfc048` remains red with its pre-existing provenance defect.

## 12. Recommendation

**`NOT_READY` for `main`**, with a single blocking item: sign-off on the weekly-window
loosening (G1/D). The code, the route manifest, the two verifiers, B1, B3 and the real PAPER
campaign are ready; merging before the signature would be exactly the silent risk change this
task forbade.
