# INDEPENDENT_RECERTIFICATION — final-HEAD protocol

## VERIFIED_COMMIT

```
RUNTIME_CODE_VERIFIED_COMMIT = b1f427ec5daeed7cc9fe054d4b841a4952bc8f15
  (last commit touching src/ scripts/ tests/ config/ in this phase)
VERIFICATION AT TREE HEAD   = verifier 11/11 + porcelain 0 re-executed in the
  fresh worktree at f6626b6, 3570fd7, e458477, and 448c38b (final HEAD =
  git rev-parse HEAD at record time; worktrees code-identical to b1f427e,
  `git ls-tree` diff of src/scripts/tests/config proven EMPTY; cleanup
  worktree removed after the run — fresh-checkout procedure is repeatable)
```

Fixed-point / self-consistency clause (terminates the hash-chase): this
record names the RUNTIME commit, not a tree hash that the record itself
would invalidate by existing. **Coverage rule**: any HEAD whose
`git diff b1f427e..HEAD -- src scripts tests config` is EMPTY remains
covered by this record (no runtime surface changed); any commit touching
those paths invalidates it and requires re-running the full protocol.

## Protocol (fresh checkout, no reliance on the primary workspace)

Executed twice this phase:

1. **Baseline closure proof (§3)** — worktree `../tap_recert` at `c4a1e02`
   (pre-hardening HEAD): `git worktree add` → `uv sync` fresh →
   pytest 584 · verifier 11/11 · mypy 0 · ruff clean. Resolves the prior
   report's insufficient `git status`-only closure argument.
2. **Final-HEAD recertification (§12)** — same worktree re-checked out to
   `b1f427e` (porcelain = 0), fresh `uv sync`, then re-checked out to the
   final phase HEAD `f6626b6` and re-run:

```
uv run pytest tests -m "not slow and not market" -q   → 607 passed (both runs)
uv run python scripts/verify_l5_independent.py        → 11/11 PASS, 0 FAIL
uv run mypy .                                         → 0 issues / 238 files
uv run ruff check .                                   → clean
uv run ruff format --check .                          → 244 files OK
```

The verifier did NOT modify code in either run (validation-only).

## Role independence (§11 — honest accounting)

```
PROCESS_INDEPENDENCE                = PASS
  (verifier + tests executed in a separate worktree with a fresh venv;
   outputs captured raw; verifier read-only)

BUILDER_VERIFIER_ROLE_INDEPENDENCE  = PARTIAL
  (the same agent session wrote the hardening commits and ran the
   verification; scripts/verify_l5_independent.py is builder-authored
   by a previous session and unmodified here, which mitigates but does
   not eliminate same-actor bias. PARTIAL is NOT upgraded to PASS.
   Full PASS requires a verification actor outside this work session.)
```

## Invalidated-run ledger

None: every verification listed above ran on a commit matching
`git rev-parse HEAD` at run time, with porcelain = 0.
