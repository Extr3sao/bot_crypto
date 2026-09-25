# INDEPENDENT_RECERTIFICATION — final-HEAD protocol

## VERIFIED_COMMIT

```
RUNTIME_CODE_VERIFIED_COMMIT = b1f427ec5daeed7cc9fe054d4b841a4952bc8f15
  (last commit touching src/ scripts/ tests/ config/)
FULL_TREE_VERIFIED_COMMIT   = 3570fd7bf810ca4c5a64c67bd01064335a84dba1
  (final phase HEAD; docs-only delta over b1f427e:
   git diff b1f427e..HEAD --stat -- src scripts tests config  → EMPTY)
git rev-parse HEAD → 3570fd7bf810ca4c5a64c67bd01064335a84dba1  (match,
  verifier 11/11 re-executed in the fresh worktree at this exact commit)
```

Fixed-point note: verification was re-executed in the fresh worktree at
`f6626b6` and again at the final HEAD `3570fd7` (verifier 11/11, porcelain 0).
The record does not depend on any later commit. **Docs-only coverage clause**:
subsequent commits that leave `git diff <RECORD>..HEAD -- src scripts tests
config` EMPTY cannot invalidate this record (no runtime surface changed);
any commit that DOES touch those paths invalidates it and requires re-running
the full protocol.

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
