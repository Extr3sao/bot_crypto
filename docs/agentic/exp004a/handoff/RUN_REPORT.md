# RUN_REPORT — RFC-051, builder side (WP-051-00, WP-051-01)

**Status: `BLOCKED` · `BLOCKED_MISSING_INDEPENDENT_VERIFIER`**
Executed at `HEAD = 8aac8b4` on 2026-10-21. `economic_executions: 0`, `source_mutations: 0`.

## What this run did

| WP | Outcome | Artifact |
| --- | --- | --- |
| WP-051-00 | **done** — read-only runtime authority audit, path classification, entrypoint exit codes, evidence access matrix | `RUNTIME_AUTHORITY_MAP.md` |
| WP-051-01 | **done** — allowlisted, read-only evidence inventory plus a claim-submission table | `EVIDENCE_INVENTORY.json`, `EVIDENCE_HANDOFF.md` |
| WP-051-02 | **blocked** — B may not be authored by A | — |
| WP-051-03 | **blocked** — needs B's verifier | — |
| WP-051-04 | **blocked** — needs B's outcome | — |

## Commands actually run, with exit codes

```text
git rev-parse HEAD                                   -> 8aac8b475a156d7961c0d15fa74c5ec9a175af50
git worktree list | wc -l                            -> 21
git status --porcelain | wc -l                       -> 277   (0 owned by this mission)
git merge-base --is-ancestor 39153a0 f831c66         -> non-zero (not an ancestor)
git diff --stat d05f8de 47116b2 -- <9 code files>    -> 9 files, +2368 lines
python -m trading_bot.research.prereg_gate --mode inspect   -> exit 3, 0 defects
python -m trading_bot.research.prereg_gate --mode authorize -> exit 2, TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE
python scripts/exp004a_evidence_inventory.py         -> exit 0, 28 references, 6 store series
pytest tests/unit/research/test_exp004a_evidence_inventory.py -> 13 passed, 0 skipped, exit 0
pytest <5 EXP-004A suites>                           -> 115 passed, 1 skipped, exit 0
```

The transcripts of the two gate runs are in `gate/INSPECT.txt` and `gate/AUTHORIZE.txt`. They
are `.txt`, not `.log`, because `.gitignore:56 *.log` had silently kept the original transcripts
out of the tree (finding A-4).

## What the numbers say

- **Admission:** 234 sealed days in the 1h lane with 5 admissible; 14 in the 1h+15m lane with 4.
  Of those admitted days, **0 lie inside the frozen capture window** `2026-10-22 → 2027-01-20`.
  The window has not opened. `4 of 90` is a statement about the store, not progress against the
  90-day requirement.
- **Inventory reconciliation:** 235 days with any data → 234 settled → 229 `DENSE_BUT_BACKFILLED`
  → 5 prospectively observed in 1h → 4 in the joint 1h+15m lane. The observer's own target in
  `coverage.json` is **60** days; the frozen experiment requirement is **90**. Reconcile against
  90.
- **Cost:** the tape walked 200 USDT. The declared notional is 500. `DECLARED_SIZE_NOT_WALKED`
  is the label, and it is also a frozen stop condition, so it blocks promotion by itself.
- **Gate:** `inspect` exit 3 and `authorize` exit 2 are the mechanism working. Neither is an
  authorisation, and exit 2 with one named refusal is not a defect to repair.
- **Independence:** `independent_verifier_identity` is `NOT_YET_ASSIGNED`, `scripts/exp004a_verify.py`
  does not exist, and `docs/agentic/exp004a/independent/` does not exist. That is the blocker.

## What was not run, and why

`scripts/exp004a_foundation.py` was **not** re-run. It appends to the sealed admission chains;
re-running it during a verification mission would be a builder write to the evidence under audit.
The measurement numbers are therefore re-reported, not re-measured — which is exactly why they
are labelled `SUBMITTED_NOT_VERIFIED` and why a verifier is required.

The verifier itself, its adversarial suite (T-01…T-20), the clean-checkout replay against
external bytes, and the acceptance decision were not implemented or executed. Authoring them as
A would make the artifact inadmissible on independence grounds regardless of its quality.

## `FALSE_SUCCESS`

Zero. No claim was marked PASS, no promotion asserted, no profitability claimed, and no blocker
was softened into a warning. This counts what this run produced; it is not a claim about anything
outside its scope.
