# FINAL_REPORT — EXPERIMENT RECOVERY

**Mission:** TRADING AGENTIC PORTABLE — EXPERIMENT RECOVERY
**Date:** 2026-10-21 · **Checkout:** `bot freebuff` @ `277d1df` · **Branch:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Economic executions:** **0** · **Live orders:** **0** · **Promotions:** **0** · **`FALSE_SUCCESS`: 0**

---

## Verdict

**`EXP-003N` is verified — not quoted.** Its verifier was re-executed from a **clean worktree at `277d1df`** and
produced **12/12 checks and 10/10 negative controls, field-identical to the published artefact**, exit `0`. The
experiment stays `CLOSED`; its 43 null preregistration fields were not touched and are not adoptable.

**No next experiment is authorised.** Five candidate windows are spent, nine families are in the negative
registry, and the best gross edge measured anywhere in this repository is **14.80 bps against a 24.79–27.31 bps
round trip**. The only remaining decision-grade measurement is the toll itself, and it needs 90 prospectively
observed days where the tree currently has **5**. That is `EXP-004A`, proposed and deliberately not started.

## Mission items

| # | Item | Status | Where the evidence is |
| --- | --- | --- | --- |
| 1 | Establish authoritative repo, branch, HEAD, remote, worktrees, run inventory | **done** | `RUNTIME_AUTHORITY_REPORT.md` §1–2 — `origin` is `bot_crypto`, upstream 13 behind, 21 worktrees, 58 modified + 211 untracked |
| 2 | Independently reproduce the EXP-003N verifier | **done** | `ECONOMIC_EVIDENCE_REPORT.md` §2 — 12/12, 10/10, identical from clean `HEAD`; the sealed tree refuses with exit 4 |
| 3 | Preserve EXP-003N as CLOSED; do not populate the 43 nulls | **done** | 43 nulls and `DRAFT_UNFROZEN` re-counted in the received package; nothing in the repo or the package was edited |
| 4 | Extract the gate; run positive, negative, adversarial tests | **done** | `GATE_REUSE_REPORT.md` — `prereg_gate.py`, 51 passed / 1 skipped, ruff + mypy clean |
| 5 | Reconcile and commit documentation safely | **done, scoped** | the commit carrying these reports contains only this mission's 10 files (2 code, 7 reports, 1 checkpoint entry); the 58 modified and 211 untracked entries belonging to other agents were not staged |
| 6 | Audit historical economic experiments | **done** | `EXPERIMENT_INVENTORY.md` + `ECONOMIC_EVIDENCE_REPORT.md` §3–7 |
| 7 | Identify the strongest remaining testable hypothesis | **done** | `NEXT_EXPERIMENT_PROPOSAL.md` §2 — the toll, not a signal |
| 8 | Determine whether untouched confirmatory data exist | **done, negative** | 5 prospectively observed days out of 235; 229 `DENSE_BUT_BACKFILLED` |
| 9 | Propose one experiment only if prereg and independence can be satisfied | **done, `PROPOSED` and blocked** | `EXP-004A`, blocked by a gate gap it must not paper over (`NEXT_EXPERIMENT_PROPOSAL.md` §4) |
| 10 | Deliver the six reports | **done** | `RUNTIME_AUTHORITY_REPORT.md`, `EXPERIMENT_INVENTORY.md`, `GATE_REUSE_REPORT.md`, `ECONOMIC_EVIDENCE_REPORT.md`, `NEXT_EXPERIMENT_PROPOSAL.md`, this file |

## What this mission changed in the repository

| File | Nature |
| --- | --- |
| `src/trading_bot/research/prereg_gate.py` | **new** — the fail-closed gate, identifier-parameterised |
| `tests/unit/research/test_prereg_gate.py` | **new** — 52 tests across positive, negative and adversarial |
| `docs/agentic/RUNTIME_AUTHORITY_REPORT.md` | new report |
| `docs/agentic/EXPERIMENT_INVENTORY.md` | new report |
| `docs/agentic/GATE_REUSE_REPORT.md` | new report |
| `docs/agentic/ECONOMIC_EVIDENCE_REPORT.md` | new report |
| `docs/agentic/NEXT_EXPERIMENT_PROPOSAL.md` | new report |
| `docs/agentic/FINAL_REPORT.md` | this file |
| `docs/agentic/RECONCILIATION_EXP-003N_PREREG_PRECHECK.md` | new report — drafted during the 2026-10-21 reconciliation, committed here |
| `docs/agentic/EXECUTION_CHECKPOINT.md` | two appended entries (this mission and the preceding reconciliation) |

No historical decision, sealed artefact, dataset or verdict was modified. `reports/ai-bots/EXP-003N-…` is
untouched: `sha256sum -c` → **29/29**.

## The three findings that matter

**1. The `2026-08-06 → 2026-08-20` window is spent, and `EXP-003N`'s `CLOSED` label hides it.** `EXP-003K` ran
both its `control` (131 closes) and `real` (175 closes) arms on that window. N's own neutrality is real — the
verifier confirms twice that N produced no row at or after `2026-08-06` — but the window cannot confirm
anything for a future experiment, and the reconciliation inherited the impression that it was pristine.

**2. `EXP-003J` and `EXP-003K` are one measurement, not two.** J's 505 closes and −225.401044 USDT at OOS are
K's `real` arm. Counting them separately would double-count a single negative result.

**3. The forward corpus is 98 % backfilled.** `data/forward/edge04/coverage.json` records 235 days from
2026-03-01 to 2026-10-21: **229 `DENSE_BUT_BACKFILLED`, 5 `PROSPECTIVELY_OBSERVED`, 1 `INCOMPLETE`**. Dense
and prospective are different properties, and the instrument that distinguishes them already exists — which is
why the proposal demands `prospectively_observed: true` per bar rather than a file count.

## What was not done, and why

| Not done | Reason |
| --- | --- |
| Any economic execution | forbidden by the mission and by `ECONOMIC-001` standing (`TRADES_AUTHORIZED=0`) |
| Populating the 43 null preregistration fields | it would fix thresholds after the answer is known |
| Re-running `EXP-003K/L/M` | the mission asked for J/K/L/M *audit*, not re-execution; their numbers are reported as reported, and only N was re-derived |
| Committing `EXP-003J`'s untracked run directory | it belongs to another workstream; committing it would claim their run as this mission's |
| Restoring `data/st6/*` or `.ci/*` cleanliness | same reason; recorded as a hazard in `RUNTIME_AUTHORITY_REPORT.md` §4 |
| A human-independent verification | `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON`; a program is not a person and the report says so everywhere |

## Residual limitations

1. **The reproduction is program-level.** The verifier shares no code with the builders, but it is a program
   written by the same workstream. This is stronger than quoting a report and weaker than an external auditor.
2. **The gate has a real gap.** A preregistration frozen before its data exists cannot pass, because digests are
   required at freeze time. `EXP-004A` needs a declared two-phase freeze that does not exist yet, and the
   proposal refuses to weaken the digest check to route around it.
3. **One test is skipped.** `test_symlink_escape_is_refused` cannot run without symlink privilege on this
   Windows host; `test_path_traversal_is_refused` covers the same gate with `../` and absolute paths, but the
   symlink branch itself is **unverified here**.
4. **The audit of `J/K/L/M/EDGE/ALPHA` is documentary.** Only `EXP-003N` was recomputed. Rows are marked
   accordingly, and no re-derived claim is made for any of the others.
5. **The inventory is bounded by this checkout.** `reports/ai-bots/EXP-003J-…` is untracked, so a clean
   checkout sees a strictly smaller history than this disk does.

## Reproduce this report

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. authority
git rev-parse --abbrev-ref HEAD && git log -1 --format='%H %s' && git remote -v
git rev-list --count origin/agent/ai-bots/RFC-TAP-AI-BOTS-003..HEAD    # 13
git worktree list | wc -l                                               # 21

# 2. the sealed experiment, unmodified
(cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 && sha256sum -c SHA256SUMS.txt)   # 29/29 OK

# 3. the verifier reproduces from clean HEAD (dataset bytes are outside Git by design)
git worktree add --detach "$TMP/003n-head" 277d1df
cp reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/* \
   "$TMP/003n-head/reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/"
cp -r reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 "$TMP/003n-head/reportcopy"
rm -f "$TMP/003n-head/reportcopy/SEAL.json"
(cd "$TMP/003n-head" && ./.venv/Scripts/python.exe scripts/exp_003n_verify.py \
    --negative-controls --out "$TMP/003n-head/reportcopy")            # 12/12, 10/10, exit 0
git worktree remove --force "$TMP/003n-head"

# 4. the gate
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prereg_gate.py -q     # 51 passed, 1 skipped
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate \
    --repo . --experiment-id EXP-003N --mode authorize                    # BLOCKED, exit 2, SPENT_EXPERIMENT_IDENTIFIER

# 5. the spent-window ledger and the forward corpus
./.venv/Scripts/python.exe -c "import json;c=json.load(open('data/forward/edge04/coverage.json'));\
from collections import Counter;print(Counter(d['class'] for d in c['days']))"
```

## Final statement

The repository does not lack discipline; it lacks an edge above its costs, and it now says so with reproduced
numbers instead of repeated assertions. `EXP-003N` is closed and verified. The gate that guards the next
experiment exists, is tested, and rejects the identifier it was written for. Nothing was promoted, and no
number in this report was invented — every one is either re-derived here or labelled as reported.
