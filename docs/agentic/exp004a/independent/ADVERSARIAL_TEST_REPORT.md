# Adversarial test report — RFC-051 verifier (EXP-004A)

**Suite:** `tests/unit/research/test_exp004a_verify_adversarial.py`
**Result:** 20 passed, 0 failed, 0 skipped — 23.53 s inside the verification run, 11.06 s standalone
**`FALSE_SUCCESS` on this suite: 0** — no defective artifact was returned as `PASS`.

Every fixture is synthetic and lives under `pytest`'s `tmp_path`. Nothing in this suite reads or
writes `data/exp004a`, `data/forward/edge03` or `data/st6`.

## What the suite asserts

The invariant is not "the checker returns a string". Each test builds a *consistent* evidence tree,
proves the honest tree passes, then breaks exactly one property and asserts the verifier names that
property with a stable reason code. Three tests are deliberate positive controls, because a checker
that refuses everything proves nothing:

- `test_t04b_an_appended_bar_is_growth_not_tampering` — today's append must leave yesterday's
  attestation valid. A verifier that flags it is useless against a live store.
- `test_the_containment_primitive_refuses_a_real_junction` — the link must genuinely reach the file
  before the refusal is allowed to mean anything.
- `test_t17_two_sweeps_of_one_snapshot_agree_exactly` — a replay must not move the numbers.

## Matrix

| ID | Case | Layer | Where it ran | Expected | Result |
| --- | --- | --- | --- | --- | --- |
| T-01 | Valid phase-1 manifest | REAL_RUNTIME | `check_gate` on `config/preregistrations/EXP-004A.json` with its real registry | inspect 3, authorize 2, promotion `NO_PROMOTION` | **executed** |
| T-02 | Protocol commit outside the evaluated history | UNIT | `test_t02…` (real git repo, orphan root) | `EVALUATED_SOURCE_MISMATCH` | **executed** |
| T-03 | Git dates only, no trusted start attestation | UNIT | `test_t03…` | `TIME_PROOF_WEAK` (BLOCKED) | **executed** |
| T-04 | One bar rewritten inside the sealed prefix | UNIT | `test_t04…` | `DIGEST_MISMATCH` | **executed** |
| T-04b | A bar appended after the seal | UNIT | `test_t04b…` | `PASS` (positive control) | **executed** |
| T-05 | External store absent | UNIT | `test_t05…` | `SOURCE_BYTES_UNAVAILABLE`, BLOCKED, never PASS | **executed** |
| T-06 | Backfilled day labelled prospective | UNIT + REAL | `test_t06…`; real replay | `ADMISSION_REPLAY_MISMATCH` | **executed — and it fired on the real evidence** |
| T-07 | Bar fetched before its own close | UNIT | `test_t07…` | `LOOKAHEAD_DETECTED` | **executed** |
| T-08 | Boundary day with gaps / late bars / missing interval | UNIT | `test_t08…` | `INCOMPLETE`, `DENSE_BUT_BACKFILLED`, joint needs both intervals | **executed** |
| T-09 | Same day sealed twice | UNIT | `test_t09…` | `LEDGER_DUPLICATE`; identical verdict on replay | **executed** |
| T-10 | Cost claimed at the declared 500 USDT without a walk | UNIT + REAL | `test_t10…`; real tape | `DECLARED_SIZE_NOT_WALKED` survives | **executed** |
| T-11 | Invented round-trip definition | UNIT + REAL | `test_t11…`; real tape | `COST_SCOPE_UNPROVEN` | **executed** |
| T-12 | Report produced for code that later changed | UNIT | `test_t12…` (real git repo) | `REPORT_CODE_STALE` | **executed** |
| T-13 | Junction escape with positive control | REAL_RUNTIME | `check_environment` on this host | refusal through the real branch | **executed** |
| T-14 | No symlink privilege on Windows | REAL_RUNTIME | `check_environment` records `symlink_privilege_available: false` | coverage not over-claimed | **executed, reported as a coverage limit** |
| T-15 | Verifier writes builder evidence | UNIT + REAL | `test_t15…`; before/after snapshot of every builder-owned file | `VERIFIER_MUTATED_SOURCE` | **executed, 0 bytes changed** |
| T-16 | Builder and verifier are one principal | UNIT + REAL | `test_t16…`; real `check_independence` | `INDEPENDENCE_NOT_PROVEN` | **executed — this is the run's own verdict** |
| T-17 | Replay of an identical snapshot | UNIT + REAL | `test_t17…`; `check_idempotency` | same verdict, same evidence | **executed** |
| T-18 | Truncated JSONL | UNIT | `test_t18…` | corruption reported, not silently dropped | **executed** |
| T-19 | Phase 2 supplied while capture is open | UNIT + REAL | `test_t19…` (promotion blocks) | `PHASE2_CAPTURE_OPEN`, `NO_PROMOTION` | **executed** |
| T-20 | Fewer than 90 admitted days | UNIT + REAL | `test_t20…`; real replay computes 0 | verification may pass; promotion `NO_PROMOTION` | **executed** |
| — | A replay that never finishes | UNIT | `test_a_timeout_is_reported_as_a_budget…` | killed tree, `BLOCKED`, never `PASS` | **executed** |
| — | An invented reason code | UNIT | `test_unstable_reason_codes…` | rejected at serialisation | **executed** |

## The two findings this suite is not needed to explain

**T-06 fired on the real store.** The frozen rule (RFC-050 §3) is `0 ≤ fetched_at_ms − (ts +
interval) ≤ lag_bound` for *every* bar of a day. Recomputing it from the real `data/forward/edge03`
bars marks `2026-10-15` and `2026-10-17` as `DENSE_BUT_BACKFILLED`, while both sealed ledgers label
them `PROSPECTIVELY_OBSERVED`. On 2026-10-15 two bars per asset arrived 10.58 M ms and 14.18 M ms
after close (bound: 7.2 M). On 2026-10-17 one bar per asset arrived 7.86 M ms after close. In the
15m lane the same days carry 8 and 9 bars outside the 30-minute bound, and 2026-10-19 and
2026-10-20 carry 9 and 5. Recomputed admissible days are therefore 3 (1h) and 1 (joint) against the
sealed 5 and 4. **This does not move the promotion decision** — every one of those days lies before
`capture.start_utc`, so the in-window count is 0 under either reading — but the sealed prospective
count is not reproducible and should not be quoted as 5/4.

**T-11 also fired.** The recorded medians reproduce exactly under one definition only:
`2 × fee + spread + buy_impact + sell_impact`, i.e. the spread is charged once for a round trip that
crosses the book twice. Charging it on both legs raises the median from 20.0012 to 20.0024 (BTC),
20.0408 to 20.0816 (ETH) and 20.9414 to 21.8828 (SOL). The tape also contains a fourth asset (XRP,
median 20.7444) that the claim does not mention.

## Limits of this suite

- The gate fixtures are real-runtime only: there is no synthetic gate here, because a second
  implementation of the gate would not be evidence about the real one.
- T-14 cannot be turned into a pass on this host; the symlink branch stays unexercised and is
  reported as `UNPROVEN_ENVIRONMENT_COVERAGE` rather than skipped silently.
- The fixtures are small (two days × three assets). They prove the decision boundary, not the
  throughput of the classifier.
