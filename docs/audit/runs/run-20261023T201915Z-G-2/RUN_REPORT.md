# RUN_REPORT — G-2 hot activation of the kill switch

- **Run id:** `run-20261023T201915Z-G-2`
- **Contract:** [`docs/audit/G-2.md`](../../G-2.md)
- **Baseline:** `27db70efe1839ef1b421a0ce53b2744d70b882d5`
- **Branch:** `audit/mt0004-negative-controls` (not pushed, not merged)
- **Date:** 2026-10-23
- **Mode:** offline only. No live order, no PAPER run against a real feed, no
  deployment.

## 1. What was asked

Close G-2 — engage the kill switch on a process that is already running —
without touching G-1 (persistence), G-3 (live), G-4 (`paper_cycle`) or D-6.

## 2. G2-00 — preflight, read-only

| # | Measurement | Result |
|---|---|---|
| P-1 | `git rev-parse --show-toplevel`, `HEAD`, `status --porcelain` | `…/ff-wt-mt0004`, `27db70ef…`, clean |
| P-2 | ancestry of `60455b46` / `ef7955dc` / `27db70ef` | all three are ancestors of `HEAD` |
| P-3 | `main` contains `60455b46`? | **No** (`git merge-base --is-ancestor` → false) |
| P-4 | broker dispatch sites in `autonomous/runtime.py` | exactly one: `self._broker.execute_signal` at line 1455 |
| P-5 | callers of `_execute_paper` | exactly one: `_evaluate_asset` (line 1076) |
| P-6 | launch path | `scripts/autonomous_paper.py` → `run` → `run_cycle` → `_evaluate_asset` → `_execute_paper` |
| P-7 | process authority used by rule 0 | `DecisionEngine()` defaults to `process_kill_switch()` (runtime 341) |
| P-8 | existing operator channel | `StopController` + `STOP` file in `run_dir` (`paper_loop.py:270-320`) |
| P-9 | other in-process control surfaces | none; the dashboard is `GET` only (`app.py:172-201`) |
| P-10 | reserved CLI commands | `kill-switch`, `status` → exit 2 |

**Gate G2-01: passed.** Entry point, admission point and exact files are
demonstrated; `allowed_paths` is frozen in the contract §8.

### Reachability classification

| Path | Class | Covered |
|---|---|---|
| `scripts/autonomous_paper.py` | `RUNTIME_AUTHORITATIVE` | **yes** |
| `trading-bot run --demo` → `paper/paper_cycle.py` | `RUNTIME_REACHABLE` | **no** — bypasses `DecisionEngine` (G-4) |
| `trading-bot place-order`, `--auto-trade` | `LEGACY` (live) | **no** — out of scope (G-3) |
| `scripts/rfc010_*`, `rfc021_*` | `TEST_ONLY` | yes, same constructor |

## 3. G2-02 — implementation

Three edits and one new module, all inside the frozen scope:

1. **`src/trading_bot/autonomous/hot_stop.py` (new).** `HotStopGate` polls
   `<run_dir>/KILL_SWITCH`, activates the process `KillSwitch` (rule 0), and
   `order_boundary()` holds the same lock across the broker call. `engage` is
   idempotent and monotonic; there is no disarm. Every transition appends a
   JSON line to `<run_dir>/kill_switch_events.jsonl`.
2. **`runtime.py`.** The runtime builds the gate by default (a runtime without
   one would be the regression), polls at each cycle top, and performs the
   only broker call inside `order_boundary`.
3. **`app.py`.** `kill-switch --run-dir … --engage | --reason` writes the
   control file atomically and answers `{"status":"REQUESTED","enforced":false}`;
   `--disarm` is refused with exit 2. `status` remains a declared stub.

No production decision logic changed: `decision.py`, `paper/**`, `config/**`
and `execution/**` are untouched (`V-1`).

### The two ACKs are deliberately different

| ACK | Proves | Does not prove |
|---|---|---|
| CLI exit 0 + `REQUESTED` | the request is on disk | that the process stopped |
| audit `event=engaged` | the process is quiet; no dispatch in flight | that anything survives a restart (G-1) |

Conflating them is the false success this task exists to prevent, so the CLI
prints `enforced: false` and the runtime event is the only enforcement claim.

## 4. Tests actually executed

| Suite | Result |
|---|---|
| `tests/unit/autonomous/test_hot_engage.py` (new, 12) | **12 passed** |
| `tests/unit/test_app_cli_contract.py` (15) | **15 passed** |
| `tests/unit/autonomous` + `test_audit_contracts_tracked.py` + CLI contract (362) | **362 passed** |
| `scripts/audit/g2_mutants.py --rev HEAD` | baseline green, **7/7 mutants killed** |
| `ruff check` on the changed files | clean |
| `ruff format --check` on the new/changed files | clean (see D-4) |
| `mypy` on the changed source files | clean |

`ruff check src/trading_bot` repo-wide reports **34 pre-existing** findings in
`research/edge0*`, `risk/manager.py` and `ops/windowless.py` — none in a file
this run touched, and not fixed here (out of scope).

### Mutants (ACC-G2-09)

| Id | Property removed | Killed by |
|---|---|---|
| M1 | engage forgets to close the gate | 3 boundary/state tests |
| M2 | the lock is not held across the dispatch | `test_engage_waits_for_the_in_flight_dispatch` |
| M3 | an unreadable control file fails open | `test_unreadable_control_path_engages` |
| M4 | engage closes the gate but leaves the authority NORMAL | `test_control_file_engages` |
| M5 | a deleted control file reports disengaged | `test_deleting_the_control_file_does_not_rearm` |
| M6 | a repeated engage is reported as a new transition | `test_engage_is_idempotent_and_audited` |
| M7 | the runtime calls the broker without the boundary | both runtime tests |

M1 was rewritten after its first version **survived**: removing only the early
`_engaged` check is an *equivalent* mutant, because the in-lock re-check still
refuses. The property was mutated instead of one line. Recording this because
a survivor is the only reason the harness is worth running.

## 5. Offline runtime trace (ACC-G2-11)

[`offline_trace.py`](offline_trace.py) builds the real runtime over deterministic
fixtures with a **hostile** decision engine that always returns `TRADE_PAPER`,
and a broker that only counts calls:

| Step | Gate | Engine mode | Order created | Broker calls | Switch |
|---|---|---|---|---|---|
| 1 operational | false | `TRADE_PAPER` | **true** | 1 | `normal` |
| 2 after control file | **true** | `TRADE_PAPER` | false | 1 | `halted` |
| 3 next cycle | true | `TRADE_PAPER` | false | 1 | `halted` |

Verdict: `OPERATIONAL_THEN_ENGAGED_NO_NEW_ORDER`
([`offline_trace.json`](offline_trace.json)).

Note what row 2 shows: the decision engine still says `TRADE_PAPER` and the
order is still refused. That is the point — the boundary is not rule 0, so a
future decision-engine regression cannot reopen the path.

## 6. Defects found in this run

| Id | Defect | Status |
|---|---|---|
| **G2-D-1** | The first mutation matrix demanded 7/7 but one mutant (M1 v1) was *equivalent*, not surviving. The harness caught my own mis-specification, not a test hole. | Fixed (mutant re-specified) |
| **G2-D-2** | The replay module `paper_cycle.py` remains outside both rule 0 and the gate. | **Open** (G-4, out of scope) |
| **G2-D-3** | `git merge-base` confirms `main` still lacks `60455b46`; nothing in this run changes that. | **Open**, unchanged |
| **G2-D-4** | `runtime.py` is not `ruff format --check` clean **at HEAD**, before this change (verified by formatting the committed file). My hunk is clean; the file's pre-existing drift is left alone rather than mixed into a safety commit. | Recorded, not fixed |
| **G2-D-5** | The backlog guard (`test_audit_contracts_tracked.py`) rejected `provenance: gap` — its closed vocabulary only knew `recovered`, `reissued`, `lost`, so a gap-derived task was unrepresentable and the truthful entry failed the build. | Fixed by contract amendment A-1: `"gap"` added to the closed set. Recorded here because widening a guard's vocabulary is exactly the kind of change that deserves a reader's attention. |

## 7. What this run does **not** establish

- **G-1:** the engaged state does not survive a restart. The gate is memory.
- **G-3:** the live path (`place-order`, `--auto-trade`, `execution/live_gate.py`)
  was not measured and is not covered by the gate.
- **G-4:** `trading-bot run --demo` → `paper_cycle.py` has no `DecisionEngine`
  and no gate. It is **unprotected** by this change, by design of its own path.
- **D-6:** the inherited MT-0003 subprocess test still targets `REPO_ROOT/src`.
  Not touched here; the new suite derives the path from the imported module.
- **No real execution:** no feed, no PAPER campaign, no order, no deployment.
- **The filesystem is the authorisation boundary** for the control file, exactly
  as it already is for `STOP`. Anyone who can write `run_dir` can stop the bot
  (fail-safe direction) — and can also delete the file, which changes nothing
  once engaged.

## 8. Reproduce

```bash
# focal + regression
uv run --frozen pytest tests/unit/autonomous tests/unit/test_app_cli_contract.py -q

# mutation matrix against the commit
uv run --frozen python scripts/audit/g2_mutants.py --rev <sha> --json mutants.json

# offline trace
PYTHONPATH=src:. uv run --frozen python docs/audit/runs/run-20261023T201915Z-G-2/offline_trace.py \
    --run-dir /tmp/g2-offline --json /tmp/g2-trace.json
```
