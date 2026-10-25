# DISCOVERY EXECUTION FLOW

| field | value |
| --- | --- |
| status | **PROPOSED — NOT IN FORCE** (describes the flow that RFC-046 would authorize) |
| vehicle | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.md` |
| policies | `docs/governance/DISCOVERY_ADMISSION_POLICY.md`, `docs/governance/DISCOVERY_STOP_RULES.md` |
| gate | `PROFITABILITY_GATE_V1` |
| scope | offline research; no execution path, no scheduler, no new agent |

## 1. Flow

```text
  external source ─────────────┐
  (registered, full text)      │
                               ▼
                    ┌──────────────────────┐
                    │ 1. HYPOTHESIS         │  H-<nnn>, 12 fields, ≤3 per campaign
                    │    preregistration    │  → ledger entry (immutable once written)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 2. ADMISSION CHECK    │  A-1..A-9, reject conditions,
                    │    (policy)           │  duplicate-of-closed-line check
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 3. STRATEGY SPEC      │  15 fields → DATASET_HASH + CONFIG_HASH
                    │    FROZEN + HASHED    │  (no measurement has run yet)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 4. DEV EXECUTION      │  PIT enforced: data_time <= decision_time
                    │    (development data) │  cost model applied, never ZERO_COST
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 5. VALIDATION         │  one pass, after the hash
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 6. FINAL OOS          │  opened ONCE; never used for selection
                    │    NET VALIDATION     │  PROFITABILITY_GATE_V1 (PG-1..PG-11)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 7. ROBUSTNESS         │  1.25x / 1.5x cost stress, sub-periods,
                    │    BATTERY            │  regime splits, single-trade dependence
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 8. INDEPENDENT        │  separate program, written after the freeze,
                    │    VERIFICATION       │  may return FAIL
                    └──────────┬───────────┘
                               ▼
              ┌────────────────┴─────────────────┐
              ▼                                  ▼
   PROFITABILITY_GATE_V1 = PASS        CAMPAIGN_FAILED / HALTED
   (separate paper promotion gate)     (write up, stop, no refill)
```

## 2. Stages, artefacts and gates

| stage | input | output | gate that must pass | owner |
| --- | --- | --- | --- | --- |
| 1 hypothesis | registered external source | hypothesis record + ledger entry | 12 fields complete | hypothesis author |
| 2 admission | hypothesis record | admit / `DEFER` / inadmissible with reason | A-1…A-9 | policy (mechanical) |
| 3 spec freeze | admitted hypothesis | frozen spec + hashes | all 15 fields + hash present | author |
| 4 dev execution | frozen spec, DEV data | measurements, PIT log | `data_time <= decision_time` | author |
| 5 validation | DEV result | validation result | same spec hash | author |
| 6 final OOS | candidate hash | net OOS result | **PG-1…PG-11** | author, verified later |
| 7 robustness | candidate + results | battery report | predeclared criteria | author |
| 8 verification | all of the above | `PASS` / `FAIL` per check | 9 checks, `false_success = 0` | **verifier (not the builder)** |

No stage may be skipped, reordered, or repeated to obtain a different answer. A repeated stage is a new candidate
with a new id (ST-9).

## 3. Data partition, made concrete

```text
DEVELOPMENT   : the window the hypothesis was formed on; reusable inside the hypothesis
VALIDATION    : one pass, after the candidate hash
FINAL OOS     : one pass, last, after validation and robustness
```

- Boundaries are artefacts. A partition without its own hash is a convention and will drift.
- The mechanical PIT check is `data_time <= decision_time` for **every** feature of **every** candidate. The
  availability rule has exactly one definition in the repository and candidates reuse it: the existing conventions
  are `autonomous/pit.availability_ms` and `candle_filter.is_candle_complete`.
- `DEF-HTF-PIT-001` (`market_data/htf_pit.py::get_completed_htf_state_at`, documented in `WP-HTF-PIT-001`) is the
  live demonstration of why this is enforced mechanically rather than by care: a 15-minute bar is treated as closed
  900 **milliseconds** after its open. The helper is currently an orphan, which is the only reason it has not leaked
  yet. No candidate may be wired to it before it is fixed and cross-checked against the two conventions above.
- A look-ahead finding is `HALTED_BY_VIOLATION` (ST-7), not a re-run.

## 4. The verification boundary

The verifier is a **second program** that re-derives rather than re-reads:

| check | what it re-derives |
| --- | --- |
| V-1 | the external source says what the hypothesis claims it says |
| V-2 | rules equal the frozen rules, by hash |
| V-3 | data availability per the declared PIT rule |
| V-4 | the result reproduces from frozen artefacts |
| V-5 | the applicable cost model was used at the candidate's turnover |
| V-6 | metric arithmetic, including the PG-6 confidence bound |
| V-7 | temporal separation (no OOS leakage into selection) |
| V-8 | every §08 gate is satisfied, not paraphrased |
| V-9 | artefacts trace to a commit |

Structural rules: builder ≠ verifier; the verifier may return `FAIL` even when the author recommends promotion; an
incomplete, erroring or non-reproducing verifier blocks promotion (ST-5); and a verifier that raises an exception
instead of producing a verdict is itself a defect — the RFC-035E `TypeError` on missing inputs (TD-2) is the
recorded precedent, and the correct behaviour there is a fail-closed `FAIL`/`INCOMPLETE`, never a traceback.

## 5. Evidence persistence

The repo's `reports/*` tree is gitignored (`.gitignore` line 55, `!reports/.gitkeep`), which lets multiple threads
write results without fighting over tracked files — and quietly makes the evidence non-versioned (TD-5). The flow
therefore splits deliberately:

| role | location | versioned |
| --- | --- | --- |
| canonical declared state | `docs/rfc/RFC-046_CONTROLLED_DISCOVERY.json` | **yes** |
| derived audit record | `data/rfc046/audit.json` | **yes** |
| working surface, measured reports | `reports/rfc046/*` | no (by convention) |

A future campaign must follow the same split: the *claim* lives in a tracked artefact, the *run output* may live in
`reports/`. A result that exists only in a gitignored tree is not evidence.

## 6. What this flow deliberately does not add

- **no new agent** — the flow is executed by existing scripts and by a human decision maker;
- **no daemon, scheduler or watcher** — the campaign is run, not deployed;
- **no execution path** — nothing here can place an order; paper and micro-live keep their own gates;
- **no dynamic routing, no dashboards, no orchestration framework** — all still frozen;
- **no automatic promotion** — the only automatic transitions are the ones to a stopped state.

## 7. Determinism and reproducibility

A campaign run must be reproducible from: the frozen spec hash, the dataset hash, the config hash, the cost model
version and the code commit. If any of those five is missing, the run is not evidence and the verifier must say so.
Timestamps are derived from the run, not typed as constants into the artefact (TD-4) — a frozen constant in a
tracked artefact is exactly how an audit trail starts lying about *when* something was measured.
