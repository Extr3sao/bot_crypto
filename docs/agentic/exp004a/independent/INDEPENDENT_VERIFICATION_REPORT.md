# Independent verification report — EXP-004A (RFC-051, WP-051-02)

> **Citation warning.** This run is **not** independent certification. The verifier is a distinct
> *program* with its own reference implementations, but it was executed by the same principal that
> produced the evidence. RFC-051 §5 requires a distinct principal or agent run; that condition is
> **BLOCKED**, and `INDEPENDENCE_NOT_PROVEN` is one of this report's own findings. Quote the
> measured numbers; never quote this document as "independently certified".

| | |
| --- | --- |
| Run | `verifier-b/EXP-004A/WP-051-02:2026-10-21T10:26:12.509519Z` |
| Evaluated commit | `47116b2f2c5fd37ed1a60550eefe17d8bd703638` (tree `51394aa9efc02ba7ddc595428419253d3b229857`) |
| Source at run time | `881f0610a13d971404e7aaaa24d486a15b4d7277`, 0 files of drift in the declared code scope |
| RFC-050 | `cc7820a99d0554389ddc45c9ff285729c25c1b1727b1bebffa93fa593b8b89d5` |
| Verifier implementation | `scripts/exp004a_verify.py`, `35cdf88ec40e671d6eaac43cdabbf3e1b77a8b9f58f0a7068afd6fad5c4eb6d9` |
| Environment | win32, Python 3.11.15, `.venv/Scripts/python.exe`, 263 dirty entries in the shared tree |
| Run status | **FAIL** |
| Promotion | **NO_PROMOTION** |
| `FALSE_SUCCESS` | **0** (20/20 acceptance cases pass) |
| Source mutations | **0** (every builder-owned file byte-identical before and after) |
| Economic executions | **0** |

## 1. Verdict

Four claims fail or cannot be completed, so the run is `FAIL`, not `PASS` and not `BLOCKED`.
`PASS` would require every in-scope claim to be substantiated; the independence precondition is
also unmet, which is recorded separately rather than hidden inside the aggregate.

| Status | Claims |
| --- | --- |
| PASS (11) | C-001, C-002, C-003, C-005, C-006, C-008, C-009, C-010, C-011, C-012, C-014 |
| FAIL (1) | **C-004** — `ADMISSION_REPLAY_MISMATCH` |
| BLOCKED (3) | **C-000** independence, **C-007** cost scope, **C-013** chronology |

## 2. What was recomputed, and what it said

**Integrity (C-005) — agrees, in full.** 786 sealed series prefixes recomputed from the live bar
store: 786 match, 0 mismatches, 0 missing, 0 unaligned, 0 duplicate timestamps, 0 look-ahead
observations. 28 tracked references hashed twice — as checkout bytes and as Git objects at each
file's own last commit — 0 mismatches, 4 files showing the expected end-of-line difference between
the two forms. 248 attestation records: 248 record digests recompute, 248 back-links validate,
248 sequence numbers contiguous, 234 + 14 unique days, both chain tips equal to the published ones
(`40693a41…`, `1d0661bb…`). The claim that the byte evidence is internally sealed and
append-only holds. Note the count: 234 × 3 + 14 × 6 = 786 prefix digests, not the 702 the claim
implies — the joint lane's six series per record were not counted in the builder's headline.

**Admission (C-004) — does not agree.** Recomputing RFC-050 §3 from the raw bars
(`0 ≤ fetched_at_ms − (ts + interval) ≤ lag_bound` for every bar of a day) reproduces the
235 → 234 → 229 shape and the 5 prospective 1h days only in the aggregate:

| | sealed | recomputed |
| --- | --- | --- |
| 1h admissible | 5 | **3** |
| 1h+15m admissible | 4 | **1** |
| admissible inside the capture window | 0 | **0** |

Five day-lane classifications disagree. On `2026-10-15` two bars per asset arrived 10.58 M ms and
14.18 M ms after close against a 7.2 M ms bound; on `2026-10-17` one bar per asset arrived 7.86 M ms
after close; in the 15m lane `2026-10-17`, `2026-10-19` and `2026-10-20` carry 8, 9 and 5 bars
outside the 30-minute bound. All five are still labelled `PROSPECTIVELY_OBSERVED`. The probe is not
the classifier's: the aggregation, the day boundaries and the `lag_bounds_ms` values are the
record's own.

**Promotion impact: none.** Every disagreeing day precedes `capture.start_utc` (2026-10-22). The
in-window count is 0 under either reading, so `INSUFFICIENT_ADMITTED_DAYS` and
`ZERO_ADMITTED_DAYS_INSIDE_CAPTURE_WINDOW` hold regardless — but "5 prospective 1h days / 4 joint"
should not be quoted as verified, and the classifier needs a defect ticket before phase 2.

**Gate semantics (C-002, C-003) — agrees.** Re-executed as a black box against the real entrypoint
and the real registry (`config/preregistrations/EXP-004A.datasets.json`): `inspect` → exit **3**,
`INSPECTION_ONLY_NO_RUN`, zero defects; `authorize` → exit **2**, exactly one error,
`TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`. Both match the recorded transcripts, and neither is an
authorisation. The first attempt of this audit used the gate's default registry path, got three
unrelated registry errors and a clean `2`; that was a harness defect, corrected, and re-run — it
is recorded here because the difference between "the gate refused" and "the gate could not read its
inputs" is exactly the kind of thing a verifier must not paper over.

**Idempotency (C-006) — agrees.** `scripts/exp004a_foundation.py --skip-seal` run twice (159.0 s and
148.2 s, both exit 0), identical stdout digest, identical timestamp-stripped reports, both ledgers
byte-identical before and after. Zero records added, zero records removed.

**Cost scope (C-007) — reproduces, but not as a round trip.** The recorded medians are exact under
`2 × fee + spread + buy_impact + sell_impact`: BTC 20.0012, ETH 20.0408, SOL 20.9414. Under that
definition the half-spread is charged **once** for a round trip that crosses the book **twice**;
charging both legs gives 20.0024 / 20.0816 / **21.8828**. The tape is a single size (200.0 USDT,
912 rows, `3d5755d7…`) and contains a fourth asset, XRP (median 20.7444), that no claim mentions.
The verdict is therefore `COST_SCOPE_UNPROVEN`, not "the medians are right".

**Declared size (C-008) — agrees, and must stay.** No row walked 500 USDT. `DECLARED_SIZE_NOT_WALKED`
survives verification; no 500-USDT cost and no profitability figure is asserted anywhere in this
report.

**Provenance (C-009) — agrees.** The evaluated commit is `47116b2`, the protocol pin in the
manifest, and it is an ancestor of the branch head; the builder report's own `d05f8de` label is not
that pin (`label_matches_manifest_pin: false`), which is what the claim says. Zero files changed
under `code_scope_paths` between the evaluated commit and the head at run time.

**Clean checkout (C-010) — agrees, with its limit.** A worktree at `47116b2` reproduces both sealed
ledgers byte for byte (`73f8ba7b…`, `1f10efb4…`) and contains **no** bar store: `data/forward/edge03`
is gitignored. A clean checkout therefore proves the ledgers and the code, never the market bytes.

**Chronology (C-013) — blocked.** No capture-start attestation exists; ordering rests on the Git
committer clock (`2026-10-21T10:00:56+02:00` for the protocol commit) and on builder-written
`sealed_at_utc` fields. `TIME_PROOF_WEAK`; no decision here depends on stronger chronology, and none
was taken.

**Path safety (C-011) — agrees on what it can test.** A real directory junction was created, it
verifiably reaches a file outside the root, the containment check refuses it, the positive control
inside the same root passes, and `../` traversal is refused. `symlink_privilege_available: false`
on this host, so POSIX-style symlink coverage remains unexercised — reported, not skipped silently.

**Tests (C-001) — agrees, at a different count.** Six EXP-004A suites re-executed by the verifier:
**128 passed, 1 skipped**, exit 0. The skip is `test_prereg_gate.py:591`, symlink privilege. The
builder's `115 passed, 1 skipped` covers five suites and excludes the inventory suite the verifier
also ran.

## 3. Defects found

| ID | Severity | Finding |
| --- | --- | --- |
| VF-01 | **High** | Two 1h days and three joint days sealed as `PROSPECTIVELY_OBSERVED` contain bars fetched outside the frozen lag bound (`ADMISSION_REPLAY_MISMATCH`). No in-window effect today; blocks any future prospective-coverage claim until the classifier and the sealed records are reconciled. |
| VF-02 | Medium | The "round-trip" cost charges the spread once per round trip; the two-spread figure is 0.0012 / 0.0408 / 0.9414 bps higher on BTC / ETH / SOL. Any promotion decision that consumes this number must state which definition it used. |
| VF-03 | Low | The byte-integrity claim's headline (702 digests) omits the joint lane's six-series records; the sealed total is 786. |
| VF-04 | Low | The builder report's `HEAD` label (`d05f8de`) is not the commit whose code was measured (`47116b2`). Corrected in interpretation, not rewritten in the sealed file. |

Anything not listed here was recomputed and agreed. Nothing in this section is a reason to relax a
gate: VF-01 makes one gate harder, not easier.

## 4. Independence, stated plainly

Program-level separation is real and audited at run time: this verifier imports no `trading_bot`
module, delegates no calculation to `scripts/exp004a_foundation.py` or
`scripts/exp004a_evidence_inventory.py`, contains no hardcoded verdict numbers (checked by AST), and
writes only under `docs/agentic/exp004a/independent/`. Principal-level separation is **not** real:
the same session that produced the handoff produced this verifier, with no separate worktree and no
disjoint principal. RFC-051 §5 is explicit that a role label is not evidence.

Consequences, accepted rather than argued away:

- `independence.status = BLOCKED`, `reason_code = INDEPENDENCE_NOT_PROVEN`, claim C-000 BLOCKED.
- `promotion.blocking_reasons` includes `BLOCKED_MISSING_INDEPENDENT_VERIFIER`.
- The findings above stand on their own arithmetic and can be re-run in seconds
  (`--mode inspect-evidence`), but they cannot be promoted to certification by this run.

## 5. Reproduce it

```
./.venv/Scripts/python.exe scripts/exp004a_verify.py --mode inspect-evidence      # bytes only, ~15 s
./.venv/Scripts/python.exe scripts/exp004a_verify.py --mode verify                # full audit, ~10 min
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_exp004a_verify_adversarial.py -q
```

Exit codes are the verifier's own: `0 PASS`, `2 FAIL`, `3 BLOCKED`, `4 ERROR`. The phase-1 gate's
codes are untouched.
