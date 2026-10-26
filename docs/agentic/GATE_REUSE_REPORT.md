# GATE_REUSE_REPORT — the fail-closed preregistration gate, extracted and parameterised

**Date:** 2026-10-21 · **Component:** `src/trading_bot/research/prereg_gate.py` · **Tests:**
`tests/unit/research/test_prereg_gate.py` · **Version string:** `PREREG_GATE_V1`

---

## 1. What was salvaged, and why it was worth salvaging

The received package (`EXP-003N_preflight_blocked_20261020`) was wrong about the world: it looked for the
wrong repository, claimed no dataset digests existed for files whose digests are frozen in `DESIGN.json`, and
claimed no prior `EXP-003N` run for an experiment that is sealed and published. Its *conclusions* are not
adopted anywhere in this mission.

Its **mechanism** is a different object, and it is better than what the repository had. Before this work,
`scripts/exp_003n_preregister.py --check` verified three things: config digests, dataset digests, and
`holdout.status == "CLOSED"`. Everything else — the embargo, the split ordering, the builder/verifier
separation, the prior-runs ledger, the git freeze — was prose in a design document. The package turned that
prose into code, and then it rejected its own experiment with it.

Extracted here, with the identifier as a parameter and no other change of substance.

## 2. What changed in the extraction

| Original (`exp003n_preflight.py`, 313 lines) | Extracted (`prereg_gate.py`) | Why |
| --- | --- | --- |
| `EXP-003N` hard-coded in 11 error codes, 2 decisions and 3 comparisons | `experiment_id` is an argument; codes are derived (`PRIOR_RUNS_FOUND_<ID>_RETROSPECTIVE_ONLY`) | the next experiment is not `N` — that identifier is spent |
| prior runs read only from `exp003n_executions` | reads `executions[<id>]`, the legacy `<slug>_executions`, and a `runs` list; **takes the maximum** | a ledger written in the other shape must not pass, and a ledger that disagrees with itself is not evidence of zero |
| no check that the identifier itself was spent | `SPENT_EXPERIMENT_IDENTIFIER:<dir>` from a boundary-safe scan of `reports/ai-bots/` | the decisive defect of the received package: `EXP-003N` already had a published run directory |
| an empty `holdout_past_consumed_exclusion` was accepted silently | `HOLDOUT_EXCLUSIONS_NOT_DECLARED` unless `no_previously_consumed_holdout: true` is asserted | an empty list is indistinguishable from a forgotten one |
| exit `0` only on authorisation, `2` otherwise | `0` authorised · **`3` inspection-only** · `2` blocked | so that "the script exited 0" cannot be quoted as approval |
| git freeze covered the manifest and the registry | also covers the prior-runs ledger | a ledger that is not committed proves nothing |
| `git status` on a `code_scope_paths` entry that does not exist returns clean | `RUNTIME_CODE_SCOPE_MISSING:<path>` | a scope that scopes nothing would pass |
| `zip(periods, periods[1:])` | `itertools.pairwise` | ruff `RUF007`; identical semantics |

Everything else is preserved deliberately, including the field lists — they are the same fields the received
draft left as 43 `null`s.

## 3. What it checks

Reads only. It imports no strategy, no broker, no backtester and no exchange client, and it reports
`economic_executions: 0` in every verdict.

1. `experiment_id` agrees across manifest, registry and the ledger.
2. `status ∈ {READY_TO_FREEZE, FROZEN}`, and `FROZEN` specifically in `authorize` mode.
3. Hypothesis, design, economics, acceptance and controls are complete — `null`, `""`, `[]` and `{}` all count
   as absent.
4. Three ordered splits with UTC timestamps, no overlap inside `embargo_minutes`, and no intersection with any
   window in `holdout_past_consumed_exclusion`.
5. `BUILDER != VERIFIER`, `OFFLINE_ONLY`, `holdout_opened is False`, `previous_results_exist is False`,
   `data_time_not_after_decision_time`, `no_retune_on_holdout`.
6. `raw` and `normalized` digests recomputed from the bytes on disk, plus a `reproduction_status` that is not
   `NOT_VERIFIED`.
7. The prior-runs ledger is completed, names this experiment, and counts **zero** executions for it.
8. No run directory and no declared marker already belongs to this identifier.
9. In `authorize` mode: `HEAD` exists, the manifest / registry / ledger are tracked, clean and each has a commit
   of its own, `candidate_code_commit` is an ancestor of `HEAD`, and every `code_scope_paths` entry exists and
   is clean.

## 4. Evidence

### 4.1 Tests — positive, negative, adversarial

```
$ ./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prereg_gate.py -q
51 passed, 1 skipped in 87.83s
```

The skip is `test_symlink_escape_is_refused`: Windows in this session cannot create a symlink without
elevation. The behaviour it tests is still covered by `test_path_traversal_is_refused`, which exercises the
same `safely_under_repo` gate with `../` and an absolute path. **The symlink case is unverified here, not
passing.**

Coverage of the three categories:

| Category | Tests | What they pin |
| --- | --- | --- |
| **Positive** | 5 | a complete, committed, digest-backed prereg **is** authorised; `inspect` never returns 0; the CLI exit contract holds; the same fixture authorises under a different identifier with `EXP-003N` appearing nowhere in the output |
| **Negative** | 26 (17 parametrised + 9 standalone) | each defect produced *alone* in an otherwise authorising fixture: draft status, one missing hypothesis field, missing splits, overlap, non-UTC timestamp, reused holdout, negative embargo, thin bootstrap, unargued sample selection, negative fee, missing CI gate, missing safety gate, live mode, identical builder/verifier, opened holdout, no-retune control, empty execution command, tampered dataset bytes, unverified provenance, no datasets, untracked manifest, dirty manifest, non-ancestor commit, missing declared path |
| **Adversarial** | 21 | filling the nulls after seeing results (caught by `GIT_DIRTY`); emptying the exclusion list; a ledger that disagrees with itself; identifier case/separator hiding a prior run; a *neighbouring* identifier that must not block; a published run directory; a marker file; `../` path escape; absolute path; symlink escape (skipped); `previous_results_exists` in a legacy shape; a missing manifest; authorisation that mutates nothing |

### 4.2 Static checks

```
$ ./.venv/Scripts/python.exe -m ruff check src/trading_bot/research/prereg_gate.py tests/unit/research/test_prereg_gate.py
All checks passed!
$ ./.venv/Scripts/python.exe -m mypy src/trading_bot/research/prereg_gate.py
Success: no issues found in 1 source file
```

### 4.3 The real repository, with the spent identifier

```
$ ./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate \
      --repo . --experiment-id EXP-003N --mode authorize
[prereg-gate] FAIL INVALID_CONTROL_data_time_not_after_decision_time
[prereg-gate] FAIL PREREG_NOT_ACCESSIBLE
[prereg-gate] FAIL SPENT_EXPERIMENT_IDENTIFIER:EXP-003N-GROSS-FIRST-DISCOVERY-001
[prereg-gate] BLOCKED · EXP-003N · authorize · 69 defect(s) · economic_executions=0
exit 2
```

Two of those lines are worth reading carefully. `SPENT_EXPERIMENT_IDENTIFIER` is the check the received
package lacked, and it fires against the very experiment the package wanted to open. `PREREG_NOT_ACCESSIBLE`
is not a bug: this repository has **never had** a `config/preregistration.json` — the 43-null draft exists only
inside the received zip, and it stays there. The gate is reporting the truth about this checkout.

## 5. What the gate cannot do

Stated because a gate that is believed beyond its power is worse than none:

1. **It cannot detect a holdout that was read before the preregistration existed.** It can detect a reuse that
   the manifest admits to, and a window that a published run directory covers. It cannot see a human opening a
   CSV in Excel.
2. **It cannot tell that a digest belongs to honest data.** A fabricated file with a matching digest passes.
   The digest proves the bytes did not change, not that they came from a venue.
3. **It cannot make the verifier a person.** `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON` is checked only as
   "builder ≠ verifier", which is exactly what it says.
4. **It cannot freeze a dataset that does not exist yet.** A prospective experiment has no bytes to hash at
   registration time. Today the registry is required at freeze time, which means a preregistration written
   *before* collection cannot pass. This is a real gap, and it is the one thing standing between this
   component and `EXP-004A` (see `NEXT_EXPERIMENT_PROPOSAL.md` §4).
5. **Git order is evidence, not proof.** `PREREG_FILE_COMMIT` proves the file has a commit; proving that commit
   precedes the first result requires reading the run's own evidence, which is the verifier's job, not a
   static gate's.

## 6. How to use it

```bash
# a draft that is still being written: report defects, authorise nothing
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate \
    --repo . --experiment-id EXP-004A --mode inspect --json-out /tmp/inspect.json

# the only invocation that can return 0
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate \
    --repo . --experiment-id EXP-004A --mode authorize --json-out /tmp/authorize.json
```

Wire the `authorize` call in **after** collecting the "is this identifier spent?" answer from
`EXPERIMENT_INVENTORY.md`, which is what the run directory scan approximates and the ledger states explicitly.

## 7. Verdict

**Adopted.** The gate is the one artefact of the received package that survives contact with this repository,
and it survives because its logic was sound even though its inputs were fabricated by a sandbox that could not
see the checkout. It is now identifier-parameterised, tested in three categories, and it rejects the identifier
it was written for.

**Not adopted:** the 43-null preregistration, the four-entry prior-runs ledger, and every conclusion in the
package's `FINAL_REPORT.md`. Filling those nulls now would choose thresholds after the answer is known, which
is the single thing the document forbids.
