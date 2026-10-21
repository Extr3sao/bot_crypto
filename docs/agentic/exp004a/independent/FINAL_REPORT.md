# WP-051-02 final report — EXP-004A independent verification

> **Not certification.** Independence at the principal level is `BLOCKED` (RFC-051 §5). This report
> is a verifier-with-its-own-arithmetic run by the builder's session; it is evidence *about* the
> evidence, not a certificate.

## Fields required by RFC-051 §13

**PHASE** — 1. Protocol phase 1 (`PROTOCOL_FROZEN`, digests deferred). Phase 2 has not begun; the
capture window opens 2026-10-22 and closes 2027-01-20.

**COMMITS** — Evaluated: `47116b2f2c5fd37ed1a60550eefe17d8bd703638` (tree
`51394aa9efc02ba7ddc595428419253d3b229857`). Source at run time: `881f0610`, with **0** files of
drift under the declared `code_scope_paths`. Builder handoff commits: `00526da`, `d7181f6`,
`ec895bf`. Verifier commit: recorded in the commit that carries this file; the verifier's own
implementation hash at run time was `35cdf88e…` (`scripts/exp004a_verify.py`).

**IMPLEMENTED** — `scripts/exp004a_verify.py` (modes `verify` / `inspect-evidence`; exit
`0/2/3/4`), `tests/unit/research/test_exp004a_verify_adversarial.py` (20 cases). Independent
re-implementations of: prefix digesting, JSONL strictness, ledger canonicalisation, RFC-050 §3 day
classification, cost arithmetic, record-chain verification, Git provenance, path containment.
No builder module is imported; no builder number is hardcoded.

**TESTS** — 20/20 verifier acceptance cases pass (`FALSE_SUCCESS = 0`), 23.53 s. Six EXP-004A
builder suites re-executed by the verifier: **128 passed, 1 skipped**, exit 0 (223.98 s); the skip
is the Windows symlink privilege at `test_prereg_gate.py:591`. `ruff` and `mypy --strict` clean on
both new files.

**RUNTIME_VALIDATION** — Gate re-executed: `inspect` exit **3** / 0 defects, `authorize` exit **2**
with exactly `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`. Measurement replay twice: exit 0 both times,
identical output, ledgers untouched. Clean worktree at the evaluated commit reproduces both sealed
ledgers and contains no bar store. 786/786 sealed prefixes verify. See `RUNTIME_VALIDATION.md`.

**PAPER_VALIDATION** — Not applicable and not attempted. No paper run, no order, no exchange call,
no credential was used; `economic_executions = 0` before and after.

**FALSE_SUCCESS** — **0** on the defined acceptance suite. Scope: 20 adversarial cases in which a
mutated, absent, stale, mislabelled or over-claimed artifact must produce a non-`PASS` verdict. This
is a tested invariant, not a claim of universal impossibility.

**DEFECTS** — VF-01 (High) admission replay mismatch; VF-02 (Medium) one-spread round-trip
definition; VF-03 (Low) 702 vs 786 digest count; VF-04 (Low) stale `HEAD` label. Details in
`INDEPENDENT_VERIFICATION_REPORT.md` §3.

**BLOCKERS** — `INDEPENDENCE_NOT_PROVEN` (no distinct principal/run), `TIME_PROOF_WEAK` (no trusted
capture-start attestation), `COST_SCOPE_UNPROVEN` (round-trip definition and a fourth unclaimed
asset), `ADMISSION_REPLAY_MISMATCH` (claim C-004 fails), plus the standing
`BLOCKED_MISSING_INDEPENDENT_VERIFIER` in the promotion decision.

**EVIDENCE** — `INDEPENDENT_VERIFICATION_REPORT.json` (full findings and every per-record digest),
`CLAIM_VERDICTS.json`, `DIGEST_RECONCILIATION.json`, `SOURCE_INVENTORY.json`,
`ACCEPTANCE_DECISION.json`, `RUNTIME_VALIDATION.md`, `ADVERSARIAL_TEST_REPORT.md`. Raw bytes were
read-only throughout; `source_mutations = 0`.

**ARCHITECTURE_STATUS** — Additive only. No change to `prereg_gate`, its exit codes, the frozen
protocol, the ledgers or the stores. The verifier writes to one new directory. Reverting this work
deletes one script, one test file and one directory; nothing else moves.

**RFC_STATUS** — RFC-051: **PARTIALLY IMPLEMENTED**. WP-051-00 (runtime authority) and WP-051-01
(handoff) were delivered by the builder; WP-051-02's verifier exists and runs, but its independence
clause is unmet, and WP-051-03/04 (independent certification, gate coupling) have not started.
RFC-051 remains **PROPOSED**, and EXP-004A remains **NOT CERTIFIED**.

**NEXT_PHASE** — WP-051-02B: hand this verifier, the handoff and the fixtures to a **distinct
principal** in its own worktree; it must re-derive the 786 prefixes and the 5 admission mismatches
before anything else is built on top of them.

## Claim matrix

| Claim | Source | Evidence | Decision |
| --- | --- | --- | --- |
| C-000 independence | RFC-051 §5 | same session, same principal, no separate worktree; program-level audit clean | **BLOCKED** `INDEPENDENCE_NOT_PROVEN` |
| C-001 115 passed / 1 skipped / lint clean | builder RUN_REPORT | 128 passed, 1 skipped across 6 suites; ruff + mypy clean | **PASS** (count differs: 6 suites, not 5) |
| C-002 inspect exits 3, zero defects | gate JSON + transcript | re-executed: exit 3, 0 defects | **PASS** |
| C-003 authorize exits 2, one error | gate JSON + transcript | re-executed: exit 2, `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` only | **PASS** |
| C-004 235/234/229/5 and 4 | admission ledgers + bars | 235/234/229 reproduce; admissible 5→**3**, 4→**1**; 5 day-lane mismatches | **FAIL** `ADMISSION_REPLAY_MISMATCH` |
| C-005 234+14 attestations, zero byte errors | ledgers + store | 786/786 prefixes, 248/248 chains, 28/28 tracked refs, 0 errors | **PASS** |
| C-006 repeated run adds zero records | foundation entrypoint | two runs, exit 0, identical output, ledgers unchanged | **PASS** |
| C-007 cost medians at 200 USDT | ST-6 tape | medians exact under one-spread; two-spread differs by up to 0.94 bps; XRP unclaimed | **BLOCKED** `COST_SCOPE_UNPROVEN` |
| C-008 500 USDT not walked | tape + manifest | every row is 200.0; declared size absent | **PASS** (and must remain so) |
| C-009 stale `HEAD` label | git graph | evaluated `47116b2` ≠ labelled `d05f8de`; 0 scope drift | **PASS** |
| C-010 clean checkout reproduces ledgers | worktree at `47116b2` | both ledgers byte-identical; bars absent by design | **PASS** (with limit) |
| C-011 junction refused, symlink skipped | this host | junction created, refused, positive control passes; symlink unavailable | **PASS** (coverage limited) |
| C-012 economic 0, capture open | gate JSON + manifest | 0 executions; `closed: false` | **PASS** |
| C-013 freeze precedes capture, trusted | RFC-050 §2 | Git clock + builder-sealed timestamps only | **BLOCKED** `TIME_PROOF_WEAK` |
| C-014 verifier acceptance suite | this verifier | 20/20 pass | **PASS** |

## Promotion

`NO_PROMOTION`, on five independent grounds: phase-2 capture open, insufficient admitted days,
**zero** admitted days inside the capture window, the declared 500 USDT never walked, and no
independent verifier. Verification changed none of them; VF-01 makes the admitted-day count
smaller, not larger.

No live order, credential, leverage or execution permission was created, requested or used.
