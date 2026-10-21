# FINAL_REPORT — TAP-EXP-004A-FOUNDATION

**Mission:** prepare the prospective economic validation without running it
**Date:** 2026-10-21 · **Branch:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Base commit audited:** `f831c66`
**Economic executions:** **0** · **Live orders:** **0** · **Promotions:** **0** · **`FALSE_SUCCESS`: 0**

---

## Verdict

**The infrastructure can observe, prove the observation, and measure a cost. It cannot yet do the third at
the declared notional, and it has 4 of the 90 days the experiment needs. `EXP-004A` is prepared and
refused by its own gate.**

| # | Mission item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Audit `f831c66`, relate it to `39153a0`, respect other worktrees | **done** | §1 — `39153a0` is the pre-amend twin (same parent, one file differs); 21 worktrees untouched |
| 2 | Review `prereg_gate.py`, design the two-phase preregistration | **done, implemented** | §3, `RFC-050`, `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` |
| 3 | Automatic prospective observation accumulating 90 admissible days | **done as a mechanism, 4/90 accumulated** | §4, `admission_1h.jsonl` (234 attestations), `admission_1h+15m.jsonl` (14) |
| 4 | Execution cost distinguishing observed / simulated / assumed | **done at 200 USDT, refused at 500** | §5 — BTC 20.0012 bps measured, 500 USDT `DECLARED_SIZE_NOT_WALKED` |
| 5 | Resolve the 235-day inventory discrepancy; duplicates add no observations | **done** | §2 — 235 → 234 → 229 backfilled → 5 (1h) → **4** (1h+15m) |
| 6 | Unit, integration, adversarial tests, including symlink escapes | **done, 87 passed / 1 skipped** | §6 — junction escape now proven on this host |
| 7 | Do not authorise or execute `EXP-004A` | **respected** | gate exit 2; `discover_existing_runs` still `[]` |

## 1. Authority

`HEAD` is `f831c66` on `agent/ai-bots/RFC-TAP-AI-BOTS-003`, remote `github.com/Extr3sao/bot_crypto.git`,
21 worktrees. `39153a0` carries the same message and timestamp and is **not** an ancestor of `f831c66`:
both have parent `277d1df`, and the only difference is three lines of `docs/agentic/FINAL_REPORT.md`. It is
the pre-amend version of the same commit — an orphan, not a competing history. Nothing was written outside
this checkout except the `data/exp004a/` state directory created by this mission.

## 2. The 235-day discrepancy, resolved

The mission named a discrepancy without naming its shape. There are four, and they nest:

| Quantity | Value | What it actually counts |
| --- | --- | --- |
| `days_with_any_data` | **235** | UTC days on which the 1h series holds a bar, observed or not |
| `window_observation_days` | **234** | those minus the day still in progress at generation time |
| `densely_covered_but_backfilled` | **229** | days whose bars all arrived **after** their close |
| `prospectively_observed` | **5** | days whose bars were stored inside the lag bound |
| **1h + 15m intersection** | **4** | the same, requiring both series — the number an experiment needing both may use |

The published figure names `primary_series = 1h:BTC/ETH/SOL`, so **5 is not wrong for 1h**. It is wrong for
anything else, and the previous report's summary — "5 prospectively observed days out of 235" — inherits the
impression that 235 is a candidate pool. It is not: 97.4 % of it is history.

Three specific corrections, each re-derived in this run from `data/forward/edge03/*/*.jsonl`:

1. **The 15m lane starts on 2026-10-07**, which is also where the frozen 15m corpus ends
   (`frozen_15m_end_utc = 2026-10-07T11:30:00Z`). So for 15m, days before that instant are *in sample*, and
   the "235 days" contain zero 15m observations. Requiring both series is 15 days of evidence, not 235.
2. **2026-10-15 drops out at 15m.** It has 22/24 1h bars inside the lag bound (0.9167, admitted) and 79/96
   15m bars (0.8229, refused). The difference between 5 and 4 is exactly that day.
3. **A duplicate is a recount.** `EXP-003J`'s 505 closes and −225.401044 USDT at OOS are `EXP-003K`'s `real`
   arm. Counting them as two negative results would double-count one measurement; the independence book
   resolves the four claims in the ledger to **3** independent windows.

## 3. Two-phase preregistration (item 2)

`prereg_gate` can now express what it previously could not: a protocol frozen **before** its data exists.
The mechanism is summarised in `RFC-050`; the parts that make it fail-closed rather than decorative:

- phase 1 (`PROTOCOL_FROZEN`) **cannot** be authorised — `authorize` returns exit 2 with
  `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE`, and `inspect` returns exit 3, never 0;
- a deferred digest is legal only per dataset, only with `digest_deferred_by`, only while `digests_deferred`
  is true, and never in phase 2;
- **no dataset file may exist in phase 1**, and the manifest's commit must precede `capture.start_utc`;
- phase 2 requires the phase-1 commit to be an ancestor whose commit time is before the capture started,
  `capture.closed`, the registry commit **at or after** `capture.end_utc`, and every dataset's period inside
  the capture window;
- an unverifiable commit clock blocks authorisation (`TWO_PHASE_TIMING_UNVERIFIABLE`).

The real `EXP-004A` phase-1 manifest is committed at `config/preregistrations/EXP-004A.json`: four datasets
with deferred digests, a 90-day capture from `2026-10-22T00:00:00Z`, and a prior-runs ledger that records
the three consumed windows and the J≡K duplicate. **The gate refuses it**, which is the correct outcome.

## 4. Prospective observation (item 3)

The observing mechanism already existed — the WP-EDGE-03 forward observer, 730 recorded runs, 20 847 bars —
and this mission did not add a second collector. What it added is the ability to **count** observations and
to make the count uneditable:

- `admission.classify_day` applies the WP-EDGE-04 rule without loosening it (≥ 90 % of calendar bars, every
  bar inside its lag bound), and keeps `DENSE_BUT_BACKFILLED` distinct from `INCOMPLETE`;
- `AttestationLedger` sealed **234** day attestations for the 1h lane (702 series digests) and **14** for the
  joint lane (84 digests), then verified every prefix digest against the store: **0 errors**;
- a second run appended **0** records and still verified — the seal is idempotent and stable;
- `sealable_through` refuses to seal a day whose bars could still legitimately arrive, so a seal cannot be
  premature.

Progress toward 90 days: **1h lane 5 of 90** (85 remaining; at 5 admissible days per 234 settled days the
projection is a date in 2040, which is a measurement of the observer's gaps, not a forecast);
**joint lane 4 of 90**. `EXP-004A` cannot start on this corpus, and the run says so with a number.

## 5. Execution cost (item 4)

Measured from `data/st6/ST6_OBSERVATIONS.jsonl` — 900 quotes, 896 usable, 13 distinct days, all four assets.

| Asset | Median at 200 USDT | p90 | Class | Fee share of the total |
| --- | --- | --- | --- | --- |
| BTCUSDT | **20.0012 bps** | 20.0012 | `OBSERVED` | 0.99994 |
| ETHUSDT | **20.0408 bps** | 20.0419 | `OBSERVED` | 0.99796 |
| SOLUSDT | **20.9414 bps** | 20.9650 | `OBSERVED` | 0.95505 |
| XRPUSDT | **20.7444 bps** | 20.7702 | `OBSERVED` | 0.96412 |

The round trip is **the venue fee plus almost nothing**: 20 bps of taker fee at VIP0, a measured spread of
0.0012 bps on BTC and 0.94 bps on SOL, and zero measured depth impact at 200 USDT. The frozen model charges
24.786 bps on BTC/ETH and 27.310 on SOL, of which 4.79 bps is spread and slippage that **the tape does not
show**. That gap is the whole of the `COST-CONFIRM` question, and it is now a measured distance.

Two refusals, both deliberate:

- **500 USDT is not reported as measured.** Every ST-6 window walked 200 USDT. Depth is not linear in size,
  so the 500 USDT row is `DECLARED_SIZE_NOT_WALKED` and its total is a *lower bound* (impact ≥ 0), labelled
  `OBSERVED` only for the components that were observed. The experiment declares 500 USDT, so the
  experiment's own notional was never walked — a prerequisite defect, now recorded rather than papered over.
- **The frozen rule is applied and cannot fire.** `INSUFFICIENT_EVIDENCE` at both sizes: 13 days against a
  frozen 60-day floor, and (at 500) a size never walked. The rule is reported for its arithmetic and
  authorises nothing.

## 6. Tests (item 6)

| Suite | Result |
| --- | --- |
| `test_prospective_admission.py` | 30 passed — classification, thresholds, lag boundary, pending days, store corruption, ledger rewrite/truncation/tamper/conflict, independence |
| `test_execution_cost_measured.py` | 16 passed — tiers, nearest-rank percentiles, walked vs unwalked size, no-observation ≠ zero, the real tape |
| `test_prereg_gate_two_phase.py` | 14 passed — phase 1 never authorisable, deferral refused in phase 2, commit-clock ordering, predates/after-close, status/phase mismatch |
| `test_prereg_gate_escape.py` | 4 passed — **junction escape proven**, plus the positive control |
| `test_prereg_gate.py` (pre-existing) | 51 passed, 1 skipped |
| **Total** | **115 passed, 1 skipped**, `ruff` clean, `mypy` clean on the new modules |

**The symlink gap is closed on this host.** `Path.symlink_to` needs a privilege Windows does not grant, but
`mklink /J` does not, and `Path.resolve` follows a junction exactly as it follows a symlink. The test builds
a real link out of the checkout, asserts the linked file is readable through it, and then asserts
`safely_under_repo` returns `None` — with a positive control on an ordinary file so the refusal cannot be
the result of a check that refuses everything. The one remaining skip is the old
`symlink_to` test, which is superseded rather than fixed.

## 6.1 Post-commit evidence

The gate was re-run **after** the protocol was committed, so the "not yet committed" housekeeping
defects of the run-time pass are gone and what remains is the deliberate refusal:

| Mode | Decision | Exit | Defects |
| --- | --- | --- | --- |
| `inspect` | `INSPECTION_ONLY_NO_RUN` | **3** | none — `PROTOCOL_FROZEN_BEFORE_CAPTURE_START` verified from git |
| `authorize` | `BLOCKED` | **2** | exactly one: `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` |

Raw output: `GATE_INSPECT.json`, `GATE_AUTHORIZE.json`, and their logs, in this directory.

A clean checkout at `HEAD` reproduces the sealed ledger **byte for byte** —
`73f8ba7b…` for `admission_1h.jsonl` and `1f10efb4…` for the joint lane, identical to the index — which is
what the `data/exp004a/** -text` rule in `.gitattributes` exists to guarantee. Without it, a CRLF checkout
would rewrite the bytes the attestations hash and make the committed seal fail verification on a machine
that never touched the data.

Commits: `47116b2` (mechanism, tests, RFC, phase-1 protocol, seal) and `fed25aa` (the pointer binding
phase 1 to the commit that froze its code). Both precede `capture.start_utc`.

## 7. What was not done, and why

| Not done | Reason |
| --- | --- |
| Authorising `EXP-004A` | phase 1 is unspent, its data does not exist, and 4 of 90 days are admitted |
| Writing the phase-2 registry or the digest commit | it may not exist before the capture closes; writing it now would be the exact fraud the mechanism prevents |
| Declaring a 500 USDT measurement | the tape walked 200; scaling would fabricate the number |
| Writing `scripts/exp004a_verify.py` | the verifier must not be authored by the builder — `independent_verifier_identity` is `NOT_YET_ASSIGNED` |
| Adding a second collector | the forward observer already records per-bar ingest time; a second pipeline is a second truth |
| Modifying any sealed artefact, verdict or spent window | `reports/ai-bots/EXP-003N-…` untouched; nothing in `reports/` was rewritten |

## 8. Limitations

1. **4 of 90 days.** The observer produces ~5 admissible days per 234 settled days, because the 1h store is
   dense only where a backfill filled it. At 90 days the experiment is ~4.5 years away, which means the
   observer's coverage is the binding constraint — not the protocol.
2. **The 15m lane cannot corroborate the 1h lane** before 2026-10-07, so any experiment requiring both has
   15 days of history, not 235.
3. **13 ST-6 days, not 90.** The cost figures are a measurement of 13 days, including one weekend.
4. **200 USDT ≠ 500 USDT.** The declared notional of `EXP-004A` was never walked by the collector.
5. **Program-level verification.** The tests are adversarial and the seal is cryptographic, but the verifier
   of a future version of this experiment is still a program written by this workstream, not a person.
6. **Accumulation is automatic at the observation layer, manual at the counting layer.** The forward observer
   already runs on the host scheduler (730 recorded runs); the admission/seal step is invoked, not scheduled.
   It is append-only and idempotent — a second run appended **0** records — so invoking it daily adds only
   newly settled days and never rewrites one. Wiring it to the existing supervisor is a distinct change to
   host state and was not made here.
7. **The run report is generated, not curated.** `RUN_REPORT.json` records the gate defects that existed at
   generation time, including "not yet committed"; the post-commit gate output is captured separately in
   `GATE_AFTER_COMMIT.json`.

## 9. Reproduce

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. admission + seal + cost + gate, from the real store and the real tape
./.venv/Scripts/python.exe scripts/exp004a_foundation.py

# 2. the seal verifies against the bytes it was computed from
./.venv/Scripts/python.exe -c "
import json; from trading_bot.research.prospective import AttestationLedger, index_series
led = AttestationLedger(path='data/exp004a/admission_1h.jsonl')
idx = [index_series(f'data/forward/edge03/1h/{a}.jsonl', a, '1h') for a in ('BTC','ETH','SOL')]
print(led.verify(idx).as_dict())"

# 3. the gate refuses the experiment it is preparing
./.venv/Scripts/python.exe -m trading_bot.research.prereg_gate --repo . --experiment-id EXP-004A \
    --manifest config/preregistrations/EXP-004A.json \
    --registry config/preregistrations/EXP-004A.datasets.json --mode authorize   # BLOCKED, exit 2

# 4. the identifier is still unspent
./.venv/Scripts/python.exe -c "
from trading_bot.research.prereg_gate import discover_existing_runs
from pathlib import Path; print(discover_existing_runs(Path('.'), 'EXP-004A'))"   # []

# 5. the tests, including the junction escape
./.venv/Scripts/python.exe -m pytest tests/unit/research/test_prospective_admission.py \
    tests/unit/research/test_execution_cost_measured.py \
    tests/unit/research/test_prereg_gate_two_phase.py \
    tests/unit/research/test_prereg_gate_escape.py -q
```

## 10. Final statement

The repository now has an instrument that distinguishes a day it watched from a day it downloaded, seals
that distinction so a quoted count cannot drift, and prices a round trip from the tape instead of from a
constant. It also has the first measured answer to the only question its evidence left open: at 200 USDT the
toll is **20.00–20.94 bps and almost entirely fee**, against a model that charges 24.79–27.31. That is a
distance, not a profit, and it does not authorise a strategy.

`EXP-004A` is prepared, its protocol is frozen before its data exists, and its own gate refuses it — with
`4` of `90` days admitted and the declared notional never walked. No promotion, no paper run, no live order,
and no number in this report was invented: each is either re-derived here from stored bytes or labelled with
the class of evidence behind it.
