# Fire commands — TASK-013.10 (post-merge)

> **When to run**: after `git fetch origin && git log --oneline -1 origin/main` shows
> the TSK-013.8 + TSK-013.9 squash-merge with the post-merge fixture values
> (`rate_limit_ms=50`, `max_backoff_ms=200` at `tests/unit/market_data/test_ccxt_connector.py:437,441`),
> and after `git checkout feature/tsk-013.10-latent-fixture-audit && git rebase origin/main`
> has succeeded (fast-forward or clean cherry-pick of the catalogue commits).

## One-liner — capture (output, REPO_SHA, DATE)

```bash
bash scripts/tsk-013.10-resweep.sh 2>&1 | tee /tmp/tsk-013.10-resweep-sample.txt; echo "REPO_SHA=$(git rev-parse HEAD)"; echo "DATE=$(date -Iseconds)"
```

This produces:
- `/tmp/tsk-013.10-resweep-sample.txt` — full script output (PASS 1 + PASS 2 + Drift invitation + manual triage reminder + SUMMARY + STATUS TILT).
- `REPO_SHA=<sha>` — the local HEAD after rebase (= the commit you will author the clean re-sweep entry on).
- `DATE=<ISO-8601 timestamp>` — for the retrieval-log entry metadata.

## Expected output signature (post-merge)

- **PASS 1** (`rg` sweep on `tests/**/*.py`): rg hits present (candidates for triage), all values `>=` the model's `ge=` floor — no violations. Manual triage tags every hit as `[VALID]` or `[BYPASS intencional]`.
- **PASS 2** (`grep` on `src/trading_bot/config/*.py`): bounded `Field(...)` declarations present; no drift relative to PASS 1 name list.
- **STATUS TILT**: `[STATUS: NEEDS-TRIAGE]` (rg hits > 0; manual triage applied). If `[STATUS: CROSS-CHECK-DRIFT-ONLY]` fires, that means the rebase actually moved the rg hits to 0 (e.g. upstream bumped beyond the catalogue's modelled scope) — still valid; just update the catalogue narrative accordingly.

## Next step (after the one-liner)

```bash
# Stage + commit the clean re-sweep entry in context/retrieval-log.md
git add context/retrieval-log.md
git commit -m "docs(retrieval): TSK-013.10 clean re-sweep post-TSK-013.8+013.9 squash-merge

Sample output: /tmp/tsk-013.10-resweep-sample.txt
REPO_SHA: <paste REPO_SHA from above>
DATE:     <paste DATE from above>

0 active violations; 4 model_construct() sites catalogued as deuda potencial
(see TSK-013.10 backlog entry + ADR-0016). Audit-gate helper
scripts/tsk-013.10-resweep.sh (Gate TSK-013.10 verbatim rg+grep) returned
rc=0 with STATUS TILT triage-applied."

# Then stage + commit the audit-gate helper script
bash -n scripts/tsk-013.10-resweep.sh && git add scripts/ && git commit -m "chore(scripts): stage TSK-013.10 re-sweep helper (Gate TSK-013.10 verbatim rg+grep, 3-round code-review verified, Refs TSK-013.11)"

# Now the branch is 3 commits ahead of main; push + open the catalogue-only PR (Path A slim 2-commit scope per pr-body-TASK-013.10-catalogue-only.md) OR the full 3-commit scope per pr-body-TASK-013.10.md.
```

## Cross-links

- `scripts/tsk-013.10-resweep.sh` — the audit-gate helper this one-liner invokes.
- `tasks/backlog.md` **TSK-013.10** — parent ticket; the clean re-sweep entry fulfills its DoD `(a)-(d)`.
- `tasks/backlog.md` **TSK-013.11** — deferred round-3 micro-nits (paste/sd ' ' + `[STATUS: NEEDS-TRIAGE]` hygiene); cherry-pick the script commit first, then file TSK-013.11 as a separate follow-up PR per its DoD.
- `pr-body-TASK-013.10-catalogue-only.md` — Path A (slim 2-commit scope: catalogue + clean re-sweep entry). Add a "Repro audit trail" section citing `/tmp/tsk-013.10-resweep-sample.txt` + REPO_SHA + DATE so reviewers can verify the clean state.
- `pr-body-TASK-013.10.md` — Path B (full 3-commit scope: catalogue + clean re-sweep entry + audit-gate helper). Use this if the operator wants the script to ride in the SAME PR (vs TSK-013.11 follow-up).
- `.ai/commands/04-plan.md` Gate TSK-013.10 — gate contract that the script wraps verbatim.
- `docs/specs/TSK-103-universe-scanner/05-tasks.md` — F5 kickoff chain cross-link (TSK-013.10 sweep applied retroactively to all Phase 1 fixtures).
- ADR-0012 (CI gate-recovery precedent) + ADR-0016 (umbrella baseline remediation).

## Cherry-pick-safety

- Single file at repo root, no path hard-codes, no logic — pure operator reference.
- The `fire-commands-*.md` files at root are an established pattern (`pr-body-*.md` already in the same directory); cherry-pick rides cleanly with the catalogue + script commits.
- Tied to TASK-013.10 lifecycle: once the catalogue-only PR lands, this file can be deleted in a follow-up sweep (not required for production behaviour).

## Operator decision: Path A vs Path B

- **Path A (slim 2-commit scope, default)**: catalogue + clean re-sweep entry only. Script commit held for a separate PR (becomes TSK-013.11's first commit, with the deferred micro-nits cherry-picked in turn). Per the close-pattern (each PR finely-scoped, independently reviewable, independently revertable).
- **Path B (full 3-commit scope)**: catalogue + clean re-sweep entry + script. Use if the operator wants the audit-gate helper to ride in the SAME PR (faster TSK-013.11 fulfilment, but the deferred micro-nits from round-3 review still need their own follow-up PR for cherry-pick-safety).

Either path is valid; the operator chooses based on reviewer load + desired atomicity.

## Clean re-sweep entry template (paste into `context/retrieval-log.md`)

> Copy the block below into `context/retrieval-log.md` as a new entry; fill the 3 placeholders (DATE, REPO_SHA, sample path) from the one-liner output above. The remaining `N` / `M` integers come from the script output (PASS 1 + PASS 2 hit counts).

```
[YYYY-MM-DDTHH:MM:SS+TZ] | commit=<SHA> | sample=/tmp/tsk-013.10-resweep-sample.txt | TSK-013.10 clean re-sweep: 0 active violations in tests/ (post-TSK-013.8+013.9 squash-merge). 4 model_construct() sites catalogued as deuda potencial (see TSK-013.10 backlog entry). Audit-gate PASS-1 rg-pattern matched N candidate lines; PASS-2 grep on src/trading_bot/config/*.py matched M bounded-field declarations; no Coverage-evolution drift detected. Operator-fired via scripts/tsk-013.10-resweep.sh (Gate TSK-013.10 verbatim rg+grep).
```

### Variable filling checklist

| Placeholder | Source | Example |
| --- | --- | --- |
| `YYYY-MM-DDTHH:MM:SS+TZ` | `date -Iseconds` output of the one-liner (line 3) | `2026-07-15T10:42:31+02:00` |
| `<SHA>` | `git rev-parse HEAD` output of the one-liner (line 2). Must be the local HEAD **after** `git rebase origin/main`. | `71046d10175a04c5c57ebfb0a89a5d24b8419183` |
| `N` (PASS 1 hits) | `=== SUMMARY ===` block of the captured sample file, line `rg hits  (PASS 1): N` | e.g. `N=12` (12 candidates, all `[VALID]` after manual triage) |
| `M` (PASS 2 hits) | Same SUMMARY block, line `grep hits (PASS 2): M` | e.g. `M=18` (18 bounded-field declarations) |
| `sample=/tmp/tsk-013.10-resweep-sample.txt` | literal path produced by `tee` in the one-liner | unchanged |

### After the template is filled

1. Paste the filled template into `context/retrieval-log.md` as a new entry (append; do NOT replace existing entries).
2. `git add context/retrieval-log.md && git commit -m "docs(retrieval): TSK-013.10 clean re-sweep post-TSK-013.8+013.9 squash-merge (sample=/tmp/tsk-013.10-resweep-sample.txt, REPO_SHA=<paste>)"`
3. Then run the script-commit + push sequence from the "Next step" section above.

### Edge cases

- If the post-merge sweep finds MORE than 0 active violations (counter to the premise of this entry), STOP and re-triage per the manual triage categories in the script output. Do NOT paste this template as-is; the audit trail would be falsified (ADR-0012 honest-state precedent).
- If the script returns rc != 0, that means the gate fired a non-clean exit (rg missing / config dir missing / parse error). Do NOT paste this template; investigate the rc first.
- If the `STATUS TILT` line says `[STATUS: CROSS-CHECK-DRIFT-ONLY]` instead of `[STATUS: NEEDS-TRIAGE]`, that means rg hits dropped to 0 (e.g. upstream constraint hardening removed all candidate hits). The template still applies but `N=0`; note this in the entry as a positive signal (constraint hardening was aggressive enough to drop the candidate surface).
