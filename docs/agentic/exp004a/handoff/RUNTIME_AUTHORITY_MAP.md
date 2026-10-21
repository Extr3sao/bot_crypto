# Runtime authority map — EXP-004A (WP-051-00)

**Role:** EXP-004A builder (A). **Mode:** read-only audit. No code, data, manifest or RFC was
changed to produce this document.
**Audited:** 2026-10-21, `HEAD = 8aac8b475a156d7961c0d15fa74c5ec9a175af50`
(`agent/ai-bots/RFC-TAP-AI-BOTS-003`).
**Economic executions during the audit:** `0`.

This is the map RFC-051 §10 requires before any verifier exists. It answers one question per
path: *if a verifier reads this, is it reading the system or reading a description of the
system?* Where a path is a description, the document says so, because the whole point of
RFC-051 is that a report is not the runtime.

---

## 1. Baseline and ownership

| Fact | Value | How it was established |
| --- | --- | --- |
| `HEAD` | `8aac8b4` · "Correct the test total in the EXP-004A report to the 115 actually run" | `git rev-parse HEAD` |
| Branch | `agent/ai-bots/RFC-TAP-AI-BOTS-003` | `git rev-parse --abbrev-ref HEAD` |
| Registered worktrees | 21 | `git worktree list` |
| Entries dirty in this worktree | 277 at audit time, **none** under `docs/agentic/exp004a/`, `src/trading_bot/research/prospective/`, `src/trading_bot/research/execution_cost/`, `scripts/exp004a_*` | `git status --porcelain` |
| Files this mission added | 3 untracked paths (`docs/agentic/exp004a/handoff/`, `scripts/exp004a_evidence_inventory.py`, `tests/unit/research/test_exp004a_evidence_inventory.py`) | `git status --porcelain -- <paths>` |

The 277 dirty entries belong to other workstreams (ST-6 / EDGE-014 / EDGE-016 / `cap004` /
`context/retrieval-log.md`, among others). They were not staged, read for modification, or
reverted. A verifier must ignore them when computing `evaluated_commit`, because they are not
part of any EXP-004A tree.

### 1.1 `f831c66` and `39153a0`

The prior mission's report was carried by `f831c66` ("Make the preregistration gate reusable and
prove EXP-003N from a clean checkout"). The identifier `39153a0` also exists and looks like the
same change. It is not.

| Property | `f831c66` | `39153a0` |
| --- | --- | --- |
| Parent | `277d1df` | `277d1df` (identical) |
| Reachable from `HEAD` | yes | **no** — no branch contains it |
| On any branch | yes (this one) | no |
| Difference vs. the other | — | `docs/agentic/FINAL_REPORT.md` only, ±5 lines |

`39153a0` is a **superseded draft** of the same commit: the working file list in
`docs/agentic/FINAL_REPORT.md` said "9 files … one checkpoint entry", `f831c66` corrects it to
"10 files … two appended entries" and adds the reconciliation report to the table. Nothing else
differs, and no evidence artifact, ledger, manifest or test result lives only in `39153a0`.

**Consequence for verification:** cite `f831c66`, never `39153a0`. `39153a0` is an orphan and
will not be found by `git log HEAD`, so a verifier that reports "commit not found" against it is
reporting the truth about a commit that was never part of the delivered history.

---

## 2. Path classification

`RUNTIME_AUTHORITATIVE` = code/data the running system reads. `RUNTIME_REACHABLE` = a
documented entrypoint a human runs. `TEST_ONLY`, `RESEARCH_ONLY`, `EXPERIMENTAL`, `LEGACY`,
`ORPHAN`, `DEAD_CODE` as in RFC-051 §10.

| Path | Class | Why |
| --- | --- | --- |
| `src/trading_bot/research/prereg_gate.py` | `RUNTIME_AUTHORITATIVE` | the gate itself; `GATE_VERSION = PREREG_GATE_V1`, `_DECISIONS = {AUTHORIZED:0, INSPECTION_ONLY:3, BLOCKED:2}` |
| `src/trading_bot/research/prospective/{store,admission,ledger,independence}.py` | `RUNTIME_AUTHORITATIVE` | classification, prefix sealing, chain link, experiment-vs-day counting |
| `src/trading_bot/research/execution_cost/{__init__,measured}.py` | `RUNTIME_AUTHORITATIVE` | knowledge-classed cost measurement; `DECLARED_SIZE_NOT_WALKED` |
| `scripts/exp004a_foundation.py` | `RUNTIME_REACHABLE` | the one documented runner; `python scripts/exp004a_foundation.py` |
| `config/preregistrations/EXP-004A.json` | `RUNTIME_AUTHORITATIVE` | phase-1 manifest the gate evaluates |
| `config/preregistrations/EXP-004A.datasets.json` | `RUNTIME_AUTHORITATIVE` | the dataset declarations (digests `null`, deferred) |
| `config/preregistrations/EXP-004A.prior_runs.json` | `RUNTIME_AUTHORITATIVE` | identifier-spend ledger the gate reads |
| `config/preregistrations/EXP-004A.baseline.json` | `RUNTIME_AUTHORITATIVE` | `NO_TRADE` baseline declaration |
| `data/exp004a/admission_1h.jsonl`, `admission_1h+15m.jsonl` | `RUNTIME_AUTHORITATIVE` | the sealed attestation chains — **the** admission evidence |
| `data/forward/edge03/{1h,15m}/{BTC,ETH,SOL}.jsonl` | `RUNTIME_AUTHORITATIVE`, **outside Git** | the bar store the attestations pin; `.gitignore:47 data/forward/` |
| `data/st6/ST6_OBSERVATIONS.jsonl` | `RUNTIME_AUTHORITATIVE` | the observed cost tape; tracked, 912 rows |
| `data/forward/edge04/coverage.json` | `RESEARCH_ONLY` (derived) | regenerated every observer tick; the RFC-050 problem P2 — never evidence of its own past |
| `docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md` | `RESEARCH_ONLY` (protocol text) | frozen intent; the *gate*, not this prose, enforces it |
| `docs/agentic/exp004a/*.{json,md}` | `RESEARCH_ONLY` (builder reports) | produced by the builder; RFC-051 exists because these are not certification |
| `tests/unit/research/test_{prereg_gate,prereg_gate_two_phase,prereg_gate_escape,prospective_admission,execution_cost_measured}.py` | `TEST_ONLY` | exercise the runtime modules; not part of any measurement |
| `src/trading_bot/research/edge03/*`, `edge04*`, `edge05/*`, `edge12/*` | `RUNTIME_REACHABLE` (other workstreams) | the forward observer that fills `data/forward/edge03`; **not** modified here |
| `scripts/exp004a_verify.py` | **absent** | the verifier must be authored by B (§4) |
| `docs/agentic/exp004a/independent/` | **absent** | verifier output root; must stay empty until B writes it |

Nothing in this worktree is `ORPHAN` or `DEAD_CODE` with respect to EXP-004A. The one orphan in
the audit scope is the commit `39153a0` above, not a file.

---

## 3. Entrypoints, and what they actually returned

Run from the repository root with `PYTHONPATH=src` and the project virtualenv
(`./.venv/Scripts/python.exe`).

```bash
python -m trading_bot.research.prereg_gate \
  --repo . \
  --manifest config/preregistrations/EXP-004A.json \
  --registry config/preregistrations/EXP-004A.datasets.json \
  --experiment-id EXP-004A --mode inspect|authorize --json-out <path>
```

| Mode | Exit | Decision | Errors | Transcript |
| --- | --- | --- | --- | --- |
| `inspect` | **3** | `INSPECTION_ONLY_NO_RUN` | none | `handoff/gate/INSPECT.{json,txt}` |
| `authorize` | **2** | `BLOCKED` | `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` | `handoff/gate/AUTHORIZE.{json,txt}` |

Both were re-run at `8aac8b4` for this audit. `authorize` also recorded
`GIT_HEAD=8aac8b475a156d7961c0d15fa74c5ec9a175af50`, so the refusal is about the manifest's phase,
not about a dirty tree. **Exit 3 is not authorisation and exit 2 here is not a defect**; a
verifier that "fixes" either has misunderstood the object it is verifying.

`python scripts/exp004a_foundation.py` is the measurement/admission runner. It is *not* re-run
here: it appends to the sealed ledgers, and a builder re-running it during a verification
mission would be a write to the evidence under audit.

---

## 4. Evidence access matrix

| Evidence | In Git? | Stable unit | Verifier must |
| --- | --- | --- | --- |
| Phase-1 manifest, datasets, prior-runs ledger, baseline | yes | whole file | compare a **checkout** against `sha256`, a **Git object** against `blob_sha256` |
| Gate results at `8aac8b4` | yes, `handoff/gate/*.json` + `*.txt` | whole file | recompute the exit codes by re-running |
| Admission attestation chains | yes (`47116b2`) | whole file, append-only | verify each record's `sha256` and `prev_sha256` chain from genesis |
| Bar series (`data/forward/edge03`) | **no** — gitignored, live | **attested byte prefix** (`byte_end`) | recompute the prefix digest; **never** a whole-file digest, it changes hourly |
| ST-6 cost tape | yes | whole file | hash, then check the 200 USDT walk actually covers the declared 500 |
| `coverage.json` | documented only | none | treat as a claim, re-derive 235/234/229/5 from bars |

The manifest is the concrete case for publishing both digests: a checkout of `d7181f6` yields
`3761481d…`, the Git object yields `07d4702a…`, and end-of-line normalisation is the whole
difference. A verifier that hashed one form and compared against the other's number would report
`DIGEST_MISMATCH` against an honest repository — so the inventory publishes `sha256` and
`blob_sha256` side by side and says which addresses which.

The asymmetry between rows 3 and 4 is the single most important operational fact for B: a
whole-file digest of a series file is true for one instant, while the sealed prefix is true
forever. `handoff/EVIDENCE_INVENTORY.json` publishes both and labels which is which.

Observed while auditing: the store was being appended during the audit itself
(`1h/*.jsonl` mtime 10:10–10:11, `15m/*.jsonl` 10:25, sizes 1.71 MB / 0.41 MB). The capture is
live. Any digest B computes over a whole series file will differ from the one in this document,
and that difference is **not** evidence of tampering.

---

## 5. Findings

Each finding is a fact about the delivered state, stated with the command that shows it, and
none of them is a verdict on a claim: verdicts belong to the verifier.

**A-1 — the builder report names a commit that does not contain the code it describes.**
`docs/agentic/exp004a/RUN_REPORT.json` records `authority.head = d05f8de`, but
`git diff --stat d05f8de 47116b2` shows `47116b2` *introducing* those 9 files (+2368 lines): the
measurement code did not exist at `d05f8de`. The correct `evaluated_commit` is
`47116b2f2c5fd37ed1a60550eefe17d8bd703638` — the commit that created the code, the sealed
ledgers, the reports and the tests together, and whose copies of those files are byte-identical
to the clean working tree now. This is RFC-051 §6.2 V-GIT / T-12 in the wild, and it is a
labelling defect, not an unverified measurement.

**A-2 — zero admitted days inside the frozen capture window.** The window is
`2026-10-22 → 2027-01-20` and `closed: false`. Every admissible day in the ledgers
(`2026-10-15, 16, 17, 19, 20` for 1h; `16, 17, 19, 20` for 1h+15m) is **before**
`capture.start_utc`. They prove the classifier recognises a genuinely prospective day; they are
not progress against `min_oos_trading_days: 90`. Quoting "4 of 90" without that qualifier
overstates the window by four days.

**A-3 — the observer's target and the experiment's target are different numbers.**
`data/forward/edge04/coverage.json` declares `required_days: 60, remaining_days: 55`, while
`config/preregistrations/EXP-004A.json` requires `min_oos_trading_days: 90`. A verifier that
reconciles "the 235-day inventory" against the observer's own target will resolve the
discrepancy to the wrong yardstick. The 90 is the frozen one; the 60 is a different lane's
stopping rule.

**A-4 — the gate stdout/stderr transcripts were not in Git.** `docs/agentic/exp004a/GATE_*.log`
match `.gitignore:56 *.log`, so a clean checkout had the JSON but not the transcript. Fresh
transcripts were produced at `8aac8b4` under `handoff/gate/*.txt` (a `.txt` suffix is not
ignored) so the stdout/stderr is now reproducible from the tree.

**A-5 — `39153a0` is an orphan.** See §1.1. No branch contains it; it differs from `f831c66` by
five lines of report prose.

**A-6 — the 500 USDT notional is declared, not walked.** `economics.declared_notional_usdt:
500.0`; the tape walked 200. `DECLARED_SIZE_NOT_WALKED` is the correct label and
`acceptance.stop_conditions` already lists "any asset whose declared notional was never walked"
as disqualifying. No verifier may convert the 200 USDT observation into a 500 USDT one.

**A-7 — independence cannot be established inside this session.** `controls.independent_verifier_identity`
is `NOT_YET_ASSIGNED`, `scripts/exp004a_verify.py` does not exist, and `docs/agentic/exp004a/independent/`
does not exist. RFC-051 §5 requires B to be a distinct principal with an isolated worktree; a
second prompt in the same session does not satisfy that. WP-051-02 onward is therefore
`BLOCKED_MISSING_INDEPENDENT_VERIFIER`, and A does not fill the gap by writing the verifier.

---

## 6. What the builder deliberately did not do

- Did not implement `scripts/exp004a_verify.py`, a verifier CLI, or any claim-level PASS/FAIL
  logic. Writing it would make the verifier's independence unevidenced from the first commit.
- Did not create `docs/agentic/exp004a/independent/`. Its absence is a checkable fact: if that
  directory exists with builder commits in it, independence has already failed.
- Did not run `scripts/exp004a_foundation.py`, `--skip-seal` or not, because both paths write to
  the ledgers under audit.
- Did not re-seal, re-classify, re-label or delete any admission record, and did not touch
  `data/forward/edge03`, `docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md` or any other workstream's
  dirty files.
- Did not place an order, read a credential, or enable anything. `economic_executions: 0`.
