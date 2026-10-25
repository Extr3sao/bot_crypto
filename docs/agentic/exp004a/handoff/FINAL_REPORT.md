# FINAL_REPORT — RFC-051, builder side

**PHASE** — `PROPOSED` RFC, partially executed. WP-051-00 and WP-051-01 are done. WP-051-02,
WP-051-03 and WP-051-04 are `BLOCKED_MISSING_INDEPENDENT_VERIFIER`. Nothing here is certified,
and `EXP-004A` remains `PROPOSED, NOT AUTHORISED`.

**COMMITS** — the audited head is `8aac8b475a156d7961c0d15fa74c5ec9a175af50`
(tree `34b9927a…`) on `agent/ai-bots/RFC-TAP-AI-BOTS-003`. The **evaluated commit** for the
measurement is `47116b2f2c5fd37ed1a60550eefe17d8bd703638`, not the `d05f8de` the builder's own
report names: `git diff --stat d05f8de 47116b2` shows `47116b2` introducing those 9 files
(+2368 lines), so the code did not exist at the commit the report cited. This mission's own
artifacts are committed separately and must be treated as report-local, never as source:
reporting them changes the head again.

**IMPLEMENTED** — a read-only, allowlisted evidence publisher
([`scripts/exp004a_evidence_inventory.py`](../../../../scripts/exp004a_evidence_inventory.py)) with
path-escape and output-root guards, and the WP-051-00/01 documents. **No verifier was
implemented.** There is no `scripts/exp004a_verify.py`, no claim-level PASS/FAIL logic, no
`ACCEPTANCE_DECISION.json`, and no file under `docs/agentic/exp004a/independent/` — that
directory's continued absence is the artifact that shows A did not occupy B's output root.

**TESTS** — `13 passed, 0 skipped` for the new publisher suite (real directory junction plus
positive controls, so a refusal cannot be vacuous); `115 passed, 1 skipped` for the five existing
EXP-004A suites. The skip is
`test_prereg_gate.py:591 symlinks unavailable in this environment` — a host privilege limit, not a
pass. Layers covered: `UNIT`, `CONTRACT`. Layers **not** covered: `ADVERSARIAL` (T-01…T-20),
`INTEGRATION`, `REAL_RUNTIME`, `CLEAN_CHECKOUT` — all of them require the verifier.

**RUNTIME_VALIDATION** — the gate was re-run at `8aac8b4`: `inspect` → exit **3**, 0 defects,
`INSPECTION_ONLY_NO_RUN`; `authorize` → exit **2**, one defect,
`TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`, with `GIT_HEAD` recorded so the refusal is about the
phase and not about a dirty tree. Transcripts: `gate/INSPECT.txt`, `gate/AUTHORIZE.txt`.
Neither exit code nor any gate semantic was changed.

**PAPER_VALIDATION** — none, and none was attempted. No order path, no credentials, no exchange
call, no leverage. `economic_executions: 0`.

**FALSE_SUCCESS** — **0**. No claim marked PASS, no promotion asserted, no profitability stated,
no blocker downgraded to a warning. Scope: the artifacts this run produced.

**DEFECTS**

| ID | Severity | Defect | State |
| --- | --- | --- | --- |
| A-1 | medium | report cites `d05f8de`; the code it describes first exists at `47116b2` | open by design — corrected here, not by rewriting the sealed report |
| A-2 | medium | 0 admissible days are inside the capture window; the "4 of 90" figure counts pre-window days | open |
| A-3 | low | observer target 60 days vs experiment requirement 90 days | open |
| A-4 | low | gate transcripts matched `.gitignore:56 *.log`, absent from a clean checkout | closed — `.txt` transcripts added |
| A-5 | low | the manifest's worktree bytes (`3761481d…`) differ from its committed bytes (`07d4702a…`) under end-of-line normalisation, so a published worktree digest would name unreproducible bytes | closed — inventory publishes `blob_sha256` and states the policy |

**BLOCKERS** — `BLOCKED_MISSING_INDEPENDENT_VERIFIER`; `SOURCE_BYTES_UNAVAILABLE` for a clean
checkout (the bar store is gitignored and live); `TIME_PROOF_WEAK` (chronology rests on the Git
commit clock, there is no external timestamping authority); `DECLARED_SIZE_NOT_WALKED` (500 USDT
declared, 200 walked); `PHASE2_CAPTURE_OPEN` (`start_utc 2026-10-22`, `closed: false`);
`INSUFFICIENT_ADMITTED_DAYS` (4 joint days, 0 in-window, 90 required).

**EVIDENCE** — `RUNTIME_AUTHORITY_MAP.md`, `EVIDENCE_HANDOFF.md`,
`EVIDENCE_INVENTORY.json` (28 tracked references, 6 live store series, sha256
`1c7d9cfe…`), `CLAIM_SUBMISSION.json` (the matrix below, machine-readable),
`RUN_REPORT.json` / `RUN_REPORT.md`, `gate/INSPECT.{json,txt}`, `gate/AUTHORIZE.{json,txt}`.
The handoff tree is pinned `-text` in `.gitattributes`, so those digests survive a checkout
instead of naming bytes a fresh clone cannot reproduce.

**ARCHITECTURE_STATUS** — unchanged. The two-phase freeze, the sealed attestation chains, the
prefix-digest scheme and the knowledge-classed cost model stand exactly as delivered. This
mission added a publisher and documents; it changed no runtime module, no manifest, no RFC, no
sealed test and no admission byte.

**RFC_STATUS** — `RFC-051: PARTIALLY_IMPLEMENTED_BUILDER_SIDE / NOT_CERTIFIED`. The RFC's own
principle is that a verifier written by the builder is not a verifier; honouring that principle
means stopping here rather than producing an artifact that looks complete.

**NEXT_PHASE** — hand `EVIDENCE_HANDOFF.md` to a distinct principal (B) with an isolated
worktree and write access limited to `docs/agentic/exp004a/independent/`. B's first executable
step is WP-051-02: implement the `verify` / `inspect-evidence` CLI with exit codes `0/2/3/4`
against `evaluated_commit 47116b2`, then run T-01…T-20 and replay from immutable snapshots. C
then reviews B. Only after that does WP-051-04 attach a promotion interface — and its answer will
still be `NO_PROMOTION`, because the blockers above are facts about the experiment, not about
verification quality.

---

## Claim matrix

The same twelve rows exist in machine-readable form in `CLAIM_SUBMISSION.json`; this table is
its human rendering and the two must stay identical.

`DECISION` is the *builder's* submission. A builder may submit and may point at evidence; it may
not decide. Every row is `SUBMITTED_NOT_VERIFIED`.

| Claim | Source | Evidence | Decision |
| --- | --- | --- | --- |
| C-001 tests pass, linters clean | 5 suites, `ruff`, `mypy` | `RUN_REPORT.json.tests`; re-runnable at `47116b2` | `SUBMITTED_NOT_VERIFIED` |
| C-002 `inspect` exit 3, 0 defects | gate | `gate/INSPECT.json` at `8aac8b4` | `SUBMITTED_NOT_VERIFIED` |
| C-003 `authorize` exit 2, one refusal | gate | `gate/AUTHORIZE.json` at `8aac8b4` | `SUBMITTED_NOT_VERIFIED` |
| C-004 235→234→229→5→4 | `data/forward/edge03` bars | `EVIDENCE_INVENTORY.json.admission` | `SUBMITTED_NOT_VERIFIED`, **with the window qualifier A-2** |
| C-005 234 + 702 + 14 digests, zero errors | sealed chains + store | `builder_observations.sealed_prefixes` (9 prefixes recomputed, all equal — A's observation, not a verdict) | `SUBMITTED_NOT_VERIFIED` |
| C-006 repeated run adds nothing | append-only ledger | `data/exp004a/*.jsonl` chain + `LEDGER_DUPLICATE` guard in `ledger.py` | `SUBMITTED_NOT_VERIFIED` |
| C-007 200 USDT medians 20.00/20.04/20.94 bps | ST-6 tape | `data/st6/ST6_OBSERVATIONS.jsonl` (912 rows) | `SUBMITTED_NOT_VERIFIED`; round-trip scope still `COST_SCOPE_UNPROVEN` |
| C-008 500 USDT not walked | tape | `DECLARED_SIZE_NOT_WALKED` in `execution_cost/measured.py` | `SUBMITTED_NOT_VERIFIED` — and it is a frozen stop condition |
| C-009 report head vs later commits | git graph | `git diff --stat d05f8de 47116b2` | `SUBMITTED_NOT_VERIFIED`; A states the label is wrong (A-1) |
| C-010 clean checkout reproduces ledger bytes | `git worktree` at `47116b2` | prior byte-exact comparison, `73f8ba7b…` / `1f10efb4…` | `SUBMITTED_NOT_VERIFIED`; bars remain unavailable in a clean checkout |
| C-011 junction refused, symlink skipped | escape suite | `13 passed, 0 skipped` on this host; 1 skip in the older suite | `SUBMITTED_NOT_VERIFIED`; cross-platform coverage unproven |
| C-012 `economic_executions: 0`, phase 2 open | gate JSON, manifest | `gate/*.json`, `capture.closed: false` | `SUBMITTED_NOT_VERIFIED` |

## Promotion

`NO_PROMOTION`. The decision does not belong to this report: it belongs to the deterministic
acceptance controller in RFC-051 §6.4, and it would be `NO_PROMOTION` even if every claim above
returned PASS tomorrow, because phase 2 is open, the window has admitted zero days, and the
declared notional has never been walked.
