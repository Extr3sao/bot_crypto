# Format change report (WP-003-07)

**Commit:** `026ea574` — *Apply the project formatter to the trunk, exempting the files that committed pins certify*
**Branch:** `recovery/trunk-format-001`, created from `1d2192b0`
**Tool:** `ruff 0.15.20` from the repository `.venv`, default configuration (`quote-style = "double"`, `line-length = 100`)

Every number below is the output of a command run in this session. The machine-readable
counterpart is [`FORMAT_EVIDENCE.json`](FORMAT_EVIDENCE.json), produced by
[`scripts/verify_trunk_format.py`](../../../../scripts/verify_trunk_format.py) reading **only git
objects** — the before side from `1d2192b0`, the after side from `026ea574` — so a clean
checkout reproduces it without trusting this working tree.

---

## 1. What the inventory said, before touching anything

`ruff format --check .` on `1d2192b0` printed, and I reproduced it exactly:

```
433 files would be reformatted, 374 files already formatted
```

That is 433 of the 807 tracked Python files, and it matches the figure recorded in
`wp00305/evidence/CI_GATES.json` for the same sha. No discrepancy.

## 2. What was applied

`ruff format .` — the project's configured formatter, nothing else. Nothing was hand-edited,
no `# fmt: off` was added, no rule was disabled, no configuration was changed.

| | value |
| --- | --- |
| files reformatted | **409** |
| lines | **+29 793 / −13 943** |
| by area | `scripts` 209 · `tests` 110 · `src` 90 |
| files carrying control comments | 151 (`# noqa` ×327, `# pragma` ×72, `# type: ignore` ×39) |
| comment tokens compared | **7 305**, identical in order and text |

## 3. Proof that it is representational only

| check | result |
| --- | --- |
| AST identical, `ast.dump(include_attributes=False)` | **408 / 409** |
| AST identical once docstring *values* are excluded | **409 / 409** |
| comment tokens identical (order and text) | 409 / 409 |
| control comments preserved one for one | 409 / 409 |
| literal rewrites with an unchanged value | 152 |
| literal rewrites with a changed value | **0** |
| file added, renamed or deleted | none |

The 152 "representation" rewrites are the interesting ones, because they are exactly the
changes that `ast.dump` cannot see and that a careless verifier would wave through or a
careless reviewer would miss. They are three kinds, all value-preserving: quote style
normalised to `"`, an f-string whose inner quotes were inverted (`f"{b['x']}"` →
`f"{b["x"]}"`), and implicit concatenation joined onto one line (`"a" "b"` → `"a b"` in
effect). The verifier merges adjacent literals before comparing and evaluates each pair, so a
real content change in the same position would be reported as a failure rather than counted as
punctuation.

### The one difference that could not be removed

`scripts/sprint002_lib.py:356`, one byte:

```
-    """Runtime-parity EMA: seed = mean(first n), multiplier 1.0 + ignore. """
+    """Runtime-parity EMA: seed = mean(first n), multiplier 1.0 + ignore."""
```

Ruff strips trailing whitespace inside docstrings, and a docstring **value** is an AST
constant. For this file the two acceptance criteria — *the format gate passes* and *every AST
is identical* — cannot both hold. I kept the formatter (that is the point of the work package)
and declared the exception instead of hiding it: the verifier proves the difference is confined
to docstrings, is whitespace-only, and is one occurrence in 409 files.

## 4. The finding that changed the plan

The first attempt formatted **all 433**. The suite then went from `81 failed / 3213 passed` to
`87 failed / 3207 passed`. Comparing **node ids**, not counts, gave six new red nodes:

```
tests/unit/forward/test_forward_collector_replay.py::test_the_capture_code_still_matches_the_certified_commit
tests/unit/research/test_active_recovery_wp.py::test_audit_is_deterministic_and_committed
tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical
tests/unit/research/test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout
tests/unit/research/test_cost_barrier_ci_parity.py::test_the_producer_pins_survive_a_checkout_that_rewrites_line_endings
tests/unit/research/test_cost_barrier_gate.py::test_a_missing_required_input_blocks_rather_than_fails
```

All six are **content pins**, and the mechanism is deliberate:

- `data/recovery/wp7/evidence/PRODUCER_PINS.json` records `sha256`, `sha256_lf` and
  `sha256_crlf` for four producers;
- `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json → evidence_digests` records the digest of
  five producer scripts plus their inputs;
- `scripts/active_economic_audit.py` hashes five **certified entrypoints** into
  `ACTIVE_ECONOMIC_AUDIT.json → payload_sha256` (`sources` is volatile, `entrypoints` is not);
- `src/trading_bot/research/forward/collector.py` is pinned **by commit** (`f406a45`) to the
  certified forward capture;
- the `st6` snapshot bundles and `data/recovery/RUN_REPORT.json` pin their own producers.

Reformatting any of those files changes the bytes the record certifies. Regenerating the record
would mean editing certified evidence to make a test pass, which this work package is forbidden
to do and should not do.

### How the exemption set was derived, rather than guessed

Rather than chase test failures one at a time, I scanned **417 committed JSON artefacts** for
objects that carry a `path` ending in `.py` together with a digest field. That found **46
pinned Python paths** (`PYTHON_PINS.json`), of which 24 were inside the formatted set. The
remaining pins were already byte-identical to base, so they never appeared as candidates.

The invariant that closes the loop: `ruff format --check .` now flags **24 files, and they are
exactly the 24 declared exemptions** — nothing flagged is undeclared, nothing declared is
unflagged (`EXEMPTIONS.json → identical: true`).

## 5. The 24 files that stay byte-identical

| pinned by | files |
| --- | --- |
| `PRODUCER_PINS.json`, `COST_BARRIER_CERTIFICATION.evidence_digests`, certified audit entrypoints, commit `f406a45` | `scripts/{active_economic_audit,autonomous_paper,cost_barrier,cost_barrier_adversarial,cost_barrier_evidence,cost_barrier_explorer,cost_barrier_gate,cost_barrier_verify,paper_lab_research,rfc010_baseline_replay,rfc021_ledger_pit}.py`, `src/trading_bot/research/forward/collector.py` |
| `data/st6/**` snapshot bundles (8 artefacts) | `scripts/{st6_close_verify,st6_forward_regime,st6_health_check,st6_scheduler_evidence,st6_scheduler_verify,st6_scheduler_witness,st6_slot_ledger}.py`, `tests/unit/research/test_st6_scheduler.py` |
| `data/recovery/RUN_REPORT.json` | `scripts/campaign_state_view.py`, `scripts/recovery_verify.py`, `tests/unit/research/test_active_recovery_wp.py` |
| `data/recovery/COST_BARRIER_EXPLORER.json` | `src/trading_bot/research/microstructure/cost_model_v3.py` |

This is a structural constraint on the repository, not a property of this commit: **the format
gate cannot reach zero for these files while their certification records are in force.** The
gate is therefore honestly reported as `24`, not as `0`, and not as "green because we excluded
them".

## 6. What the other gates did

| gate | base `1d2192b0` | head `026ea574` | delta |
| --- | --- | --- | --- |
| `ruff format --check .` | 433 | 24 | **−409**, and the 24 are the exemptions |
| `ruff check .` | 100 | **100** | 0 |
| `mypy .` | 253 errors / 29 files / 801 checked | **253 / 29 / 802** | 0 (`+1` file is the verifier, 0 errors) |
| collection | 0 errors | 0 errors | 0 |

No new lint, type or collection debt is attributable to this commit.

## 7. How to re-run the proof

```bash
cd <checkout of 026ea574>
python scripts/verify_trunk_format.py --base 1d2192b0 --head 026ea574 --expect-files 409 \
  --json /tmp/FORMAT_EVIDENCE.json
python scripts/verify_trunk_format.py --base 1d2192b0 --self-test   # 6/6 controls must fire
ruff format --check .            # 24 files, exactly the exemptions
```

The self-test builds six mutant commits from the base tree with `git commit-tree` plumbing and
requires each one to be rejected: no change, an added assignment, an added comment, an added
`# noqa`, a changed literal value, and an added file. A green run therefore means something.
