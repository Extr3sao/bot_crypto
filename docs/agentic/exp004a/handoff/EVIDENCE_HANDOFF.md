# Evidence handoff contract — EXP-004A (WP-051-01)

**From:** EXP-004A builder (A), run `tap-foundation-2026-10-21`
**To:** the independent verifier (B) — **not yet assigned**
**Status of this document:** a *submission*, not a finding. Every value below is
`SUBMITTED_NOT_VERIFIED` until B recomputes it.

A verifier cannot verify what it cannot read, and it must not be handed a summary and asked to
agree with it. This is the readable surface: where the bytes are, what they claim to be, and what
would falsify each claim. It deliberately contains **no PASS/FAIL column** — the moment A writes
one, A is certifying A.

---

## 1. What is being handed over

| Item | Path | Digest of record |
| --- | --- | --- |
| Inventory (machine-readable) | `docs/agentic/exp004a/handoff/EVIDENCE_INVENTORY.json` | sha256 `c8b4f57966f28986…` |
| Authority map (WP-051-00) | `docs/agentic/exp004a/handoff/RUNTIME_AUTHORITY_MAP.md` | `git ls-files` at `8aac8b4` |
| Protocol | `docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md` | sha256 `cc7820a99d055438…` |
| Phase-1 manifest | `config/preregistrations/EXP-004A.json` | blob sha256 `07d4702adc264f03…`, commit `fed25aa` |
| Dataset declarations | `config/preregistrations/EXP-004A.datasets.json` | sha256 `8946f871a97b7575…`, commit `47116b2` |
| Identifier ledger | `config/preregistrations/EXP-004A.prior_runs.json` | sha256 `94b161030d4ca0ed…`, commit `47116b2` |
| Admission chain, 1h lane | `data/exp004a/admission_1h.jsonl` | sha256 `73f8ba7b5716a725…`, 234 records, tip `40693a41…` |
| Admission chain, 1h+15m lane | `data/exp004a/admission_1h+15m.jsonl` | sha256 `1f10efb48f1c1272…`, 14 records, tip `1d0661bb…` |
| Gate `inspect` at `8aac8b4` | `handoff/gate/INSPECT.{json,txt}` | exit **3**, 0 defects |
| Gate `authorize` at `8aac8b4` | `handoff/gate/AUTHORIZE.{json,txt}` | exit **2**, 1 defect |
| Cost tape | `data/st6/ST6_OBSERVATIONS.jsonl` | sha256 `3d5755d78af7c9f1…`, 912 rows |
| Bar store (live, gitignored) | `data/forward/edge03/{1h,15m}/{BTC,ETH,SOL}.jsonl` | **attested prefixes only** |

**Digest policy — which number to compare, depending on what you hashed.** Both digests are
published because they answer different questions, and picking the wrong one produces a
`DIGEST_MISMATCH` against an honest repository.

| You hash | Compare against | Measured example on this repo |
| --- | --- | --- |
| a checkout on disk | `sha256` | manifest checkout → `3761481d…` |
| the Git object at `last_commit` | `blob_sha256` | manifest blob → `07d4702a…` |
| either, for a tree pinned `-text` | both agree | ledger → `73f8ba7b…` / `1f10efb4…` |
| the live bar store | attested prefixes only | neither applies |

This was measured, not assumed: a throwaway worktree at `d7181f6` produced `3761481d…` for the
manifest, which is the inventory's `sha256`, while `git cat-file blob` produced `07d4702a…`. The
handoff tree itself is pinned `-text`, so its own published digest (`c8b4f579…`) is byte-identical
in the worktree, in the Git object and in a fresh checkout.

`evaluated_commit = 47116b2f2c5fd37ed1a60550eefe17d8bd703638`. This is *not* the commit the
builder's own report names (`d05f8de`); see finding A-1 in the authority map for the proof, which
is a one-command diff. B should decide the question independently and is under no obligation to
accept the correction.

### 1.1 How to regenerate the inventory

```bash
./.venv/Scripts/python.exe scripts/exp004a_evidence_inventory.py \
  --out docs/agentic/exp004a/handoff/EVIDENCE_INVENTORY.json
echo $?   # 0 written, 2 refused (allowlist / escape / forbidden output root)
```

The publisher is read-only over evidence and refuses an `--out` path under `data/`,
`reports/ai-bots/` or `evidence/`. **B must not import it.** It exists so A can expose hashes
without hand-typing them; a verifier that calls A's publisher has delegated its evidence
collection to A and should self-report `INDEPENDENCE_NOT_PROVEN`.

---

## 2. Allowlisted roots and the boundary

Readable by B: `config/`, `data/exp004a/`, `data/forward/edge03/`, `data/st6/`, `docs/`,
`scripts/`, `src/`, `tests/`. Anything else is out of scope, including `.env`, any credential
store, and the other 20 registered worktrees.

B writes **only** to `docs/agentic/exp004a/independent/`. That directory does not exist as of
this handoff, and that absence is deliberate and checkable: it is the artifact that shows A never
occupied B's output root.

Guards B must keep, because A's own tooling is the negative case that proves they matter: a
declared path is rejected if it is not under an allowlisted root, if it contains a `.` or `..`
segment, if it is absolute, or if it *resolves* outside the repository root. Both the declared and
the resolved path are checked — a junction whose declared path looks honest will fail only the
second check. `tests/unit/research/test_exp004a_evidence_inventory.py` exercises those branches
with a real directory junction plus positive controls.

---

## 3. Claims submitted for verification

The twelve claims are RFC-051 §1's, restated with the evidence that would settle each. "Expected
class" is what A believes B will conclude **if the bytes are available**; it is a prediction to be
falsified, not a status.

| ID | Builder-reported value | Evidence to recompute | Falsifier | Expected class |
| --- | --- | --- | --- | --- |
| C-001 | 115 passed, 1 skipped; ruff + mypy clean | the 5 suites under `tests/unit/research/`; `ruff check`, `mypy` | any failing test at `evaluated_commit` | PASS, with the skip named |
| C-002 | `inspect` exit 3, 0 defects | re-run §3.1 `inspect` | exit ≠ 3, or defects ≠ 0 | PASS |
| C-003 | `authorize` exit 2, only `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` | re-run `authorize` | any second error, or exit 0 | PASS |
| C-004 | 235 → 234 → 229 → 5 → 4; 4/90 admitted | re-derive from bars' `fetched_at_ms` | any count that disagrees, or a day admitted with a bar outside its lag bound | PASS **with a scope qualifier**: 0 of those days lie inside the capture window |
| C-005 | 234 + 702 + 14 digests, zero byte errors | recompute prefixes from `data/forward/edge03` | one prefix mismatch | PASS if the store is readable; `BLOCKED` otherwise |
| C-006 | a repeated run adds zero records | snapshot the ledgers, re-run the counter, diff | any new or rewritten record | PASS / `LEDGER_DUPLICATE` |
| C-007 | BTC 20.0012 · ETH 20.0408 · SOL 20.9414 bps median at 200 USDT | `execution_cost` over the ST-6 tape | a median that disagrees, or a bps definition that is one-way | PASS for 200; `COST_SCOPE_UNPROVEN` for round-trip wording |
| C-008 | 500 USDT not walked | the tape's walked notionals | any 500 USDT sample | `DECLARED_SIZE_NOT_WALKED` — blocking for promotion, correct for verification |
| C-009 | report at `d05f8de`, later `8aac8b4` | `git diff --stat d05f8de 47116b2` | the code existing at `d05f8de` | **FAIL as labelled**: `evaluated_commit` is `47116b2` (A-1) |
| C-010 | clean checkout reproduces the sealed ledger bytes | `git worktree add` at `47116b2`, re-derive, compare | a differing ledger byte | PASS for ledgers; `SOURCE_BYTES_UNAVAILABLE` for bars |
| C-011 | Windows junction refused; symlink test skipped | run the escape suite on B's host | a link that escapes undetected | PASS on Windows, `UNPROVEN_ENVIRONMENT_COVERAGE` elsewhere |
| C-012 | `economic_executions: 0`, phase 2 open | gate JSON, manifest `capture.closed` | any execution or a closed capture | PASS |

Two of these are worth B's early attention because they are the ones A could plausibly have got
wrong: **C-004's denominator** (the admitted days are all pre-window, so 4/90 is not window
progress) and **C-007's unit** (a ~20 bps median is compatible with a *round trip* only if the
tape's two-sided walk is what was summed — the model charges 24.786 bps, the fee alone is 20, and
the difference is spread plus depth, so a one-way reading would double-count).

---

## 4. Blockers B will hit, declared in advance

| Blocker | Why it cannot be removed by A | Reason code |
| --- | --- | --- |
| No independent verifier exists | A writing it is the failure RFC-051 §5 defines | `BLOCKED_MISSING_INDEPENDENT_VERIFIER` |
| Bar store is outside Git and live | appending hourly; whole-file digests are transient | `SOURCE_BYTES_UNAVAILABLE` if B cannot snapshot |
| Chronology rests on the Git commit clock | no external timestamping authority exists in this repo | `TIME_PROOF_WEAK` |
| 500 USDT notional unobserved | scaling a depth walk is an invention | `DECLARED_SIZE_NOT_WALKED` |
| Capture window has not opened | `start_utc = 2026-10-22`, `closed: false` | `PHASE2_CAPTURE_OPEN`, `INSUFFICIENT_ADMITTED_DAYS` |
| Only 4 joint days admitted, 0 in-window | 90 are required | `INSUFFICIENT_ADMITTED_DAYS` |

A verifier that turns any of these into a PASS has produced a `FALSE_SUCCESS`. A verifier that
returns `BLOCKED` on all six has done its job.

---

## 5. What A will not do

A will not write `scripts/exp004a_verify.py`, will not create artifacts under
`docs/agentic/exp004a/independent/`, will not emit an `ACCEPTANCE_DECISION.json`, and will not
score any claim in this table. A will keep the gate and its exit codes exactly as they are, and
will not re-seal, re-classify or delete any admission record to make a verification easier.

The promotion decision is not A's either, and it is not B's: it belongs to the deterministic
acceptance controller in RFC-051 §6.4, and its current value is `NO_PROMOTION` for reasons that
have nothing to do with verification quality — phase 1, an open capture, 0 in-window days, and an
unwalked declared notional.
