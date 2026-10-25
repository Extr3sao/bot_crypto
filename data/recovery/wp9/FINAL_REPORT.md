# FINAL REPORT — WP-9 / CI RUNTIME CERTIFICATION & PAPER READINESS RECOVERY

> Deliverables of this work package live beside this file:
> [WP9_CI_EXECUTION_REPORT.md](WP9_CI_EXECUTION_REPORT.md) + [.json](WP9_CI_EXECUTION_REPORT.json),
> [WP9_DISK_BUDGET_AUDIT.md](WP9_DISK_BUDGET_AUDIT.md) + [.json](WP9_DISK_BUDGET_AUDIT.json),
> [WP9_RUNTIME_24H_REPORT.md](WP9_RUNTIME_24H_REPORT.md) + [.json](WP9_RUNTIME_24H_REPORT.json),
> [WP9_M03_M07_READINESS.md](WP9_M03_M07_READINESS.md) + [.json](WP9_M03_M07_READINESS.json),
> [WP9_ACTIVE_ECONOMIC_BLOCKERS.md](WP9_ACTIVE_ECONOMIC_BLOCKERS.md) + [.json](WP9_ACTIVE_ECONOMIC_BLOCKERS.json),
> [RFC_050_COST_AND_ENTRY_DRAFT.md](RFC_050_COST_AND_ENTRY_DRAFT.md),
> [RUN_REPORT.md](RUN_REPORT.md) + [.json](RUN_REPORT.json),
> [INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json), and
> [evidence/](evidence/) with the raw stdout/stderr of the runs the reports name.
>
> **Revision.** Every number below was produced at `HEAD 5348fcd55ab9ef404c676d8aada8daa8c85b9785`
> (`main`, 256 commits ahead of `origin/main`). The tree carries these artefacts **uncommitted**:
> this lane did not commit, because the working tree also holds other lanes' modified data
> (`data/st6/**`, `evidence/real_decisions/**`, the root `RUN_REPORT.*` of a different work
> package) that are not this lane's to stage. A reader can therefore reproduce everything from
> `5348fcd` plus this untracked directory, but **the lane has no commit of its own yet** — that is
> the one open housekeeping item, stated here rather than hidden.

```
FALSE_SUCCESS       = 0
BUILDER != VERIFIER : scripts/wp9_verify.py, builder_imported = False
TEST_TARGET         = RUNTIME_TARGET (scripts/autonomous_paper.py, the lab's own entrypoint)
LIVE_TRADING        = DISABLED
TRADES_AUTHORIZED   = 0
FINAL STATUS        = PARTIAL
```

| gate | state | why |
| --- | --- | --- |
| CI_CERTIFIED | **BLOCKED** | no runner run id exists and none may be invented |
| 24 h stability | **NOT ESTABLISHED** | 0.0621 h executed of 24 h (`WINDOW_INCOMPLETE`) |
| disk preflight control | **IMPLEMENTED & VERIFIED** | refuses the defect that stopped window 1, exit 4 |
| M-03 / M-07 research-ready | **NOT_READY / NOT_READY** | history does not exist; nothing synthesised |
| strategies with demonstrable net advantage | **0 of 24** | cost plane 23.354 bps; best gross 8.912 bps |

---

## Q1 — Has the workflow been certified on a real GitHub Actions runner?

**No. The certificate is BLOCKED, not earned, and not simulated.**

[WP9_CI_EXECUTION_REPORT.json](WP9_CI_EXECUTION_REPORT.json) reports `ci_certified: false`,
`ci_certified = BLOCKED`, `runner: LOCAL`, with `certification.local_equivalent: false` and three
named blockers:

1. **No way to authenticate to the remote.** The dry-run push probe
   (`git push --dry-run origin HEAD:refs/heads/wp9-ci-probe-do-not-create`) exits `128` with
   `fatal: Cannot prompt because user interactivity has been disabled.` There is no `gh` CLI, no
   token in the environment, and the credential helper cannot prompt. The probe creates no ref.
2. **Actions has never registered the workflows.** The repository (`Extr3sao/bot_crypto`, public,
   reachable) reports exactly **1 registered workflow**: `CI Baseline` (`.github/workflows/ci.yml`,
   `active`). `.github/workflows/recovery-determinism.yml` and
   `.github/workflows/cost-barrier-gate.yml` — the WP-8 workflows this lane was asked to certify —
   **are not registered**, because they are not on the default branch.
3. **Running them would publish 256 commits.** The commit that carries them is 256 commits ahead of
   `origin/main`; triggering a runner means publishing this history to a public repository. That is
   a governance decision, not a side effect of an audit.

So there is **no workflow run id, no runner OS, no runner exit code to report** — inventing one is
the failure mode this lane exists to prevent. What *is* reported is what a real runner can be compared
against:

* **The registered CI is red and predates this work.** The five most recent `CI Baseline` runs all
  concluded `failure` — `35724120977` (`5e6f963`, 2026-09-22T11:54:55Z) and four older ones back to
  `29110223546` (2026-07-10). The remote's last push is 2026-09-22; nothing of WP-8/WP-9 has ever
  reached it.
* **The workflow's own sequence was executed locally instead, step by step, and every step passed.**
  `sequence_total: 12, sequence_failed: 0`: sync dependencies, prepare the evidence directory,
  verify the committed input bundle, prove the repair moved no economic finding, lane contract tests
  and determinism regressions, clean-checkout rehearsal (scope full), independent verification of the
  published artefacts — then, for the second workflow: sync, materialise declared inputs, full
  reproduction, adversarial gate verification, certification record. `local_execution_attempted:
  true`, shell `C:\Program Files\Git\bin\bash.exe`.
* `workflow_problems: []` — the workflow YAML was audited (checkout, `setup-uv`, pinned Python,
  declared timeouts, `ubuntu-latest`) and no structural defect was found. The verifier re-reads the
  YAML itself (control CI1) rather than trusting the audit's summary.

A local reproduction is evidence about the *sequence*; it is not a runner certificate, and this
report does not upgrade it to one.

## Q2 — What caused the disk exhaustion?

Two different events were conflated in the operator's summary, and the audit separates them.
[WP9_DISK_BUDGET_AUDIT.json](WP9_DISK_BUDGET_AUDIT.json) records three findings.

**WP9-DISK-01 — `CONFIGURATION_DEFECT` (this is the 4.16 h stop).** Window 1 was launched with an
**800 MB collector valve** while its own measured capture rate was **192.25 MB/h**, so the valve
fills in `800 000 000 / 192 251 691 = 4.161 h`. A 24 h window needed **4.618 GB**; the shortfall was
**3.814 GB**. No code defect was involved: the guard did what it was told — segments sealed, manifest
finalised, `exit 0`. Two numbers that were never compared.

**WP9-DISK-02 — `UNRECORDED_TERMINATION` (window 2).** `paper-lab-continuous-03` stopped after
**5.8868 h** with *every* child still `RUNNING`, **0 restarts** on all four, disk at **31.502 GB
free** and the valve only **1.74 GB** used. Nothing in the record says why, and **no manifest was
sealed**, so that window's data cannot be used as evidence. The absence of a stop record *is* the
finding; the cause is not reconstructed from a gap.

**WP9-DISK-03 — `SHARED_HOST_PRESSURE`.** The volume is **255.04 GB with 93.06 % already in use by
other writers**, and free space moved from 26.352 GB to 31.502 GB across window 2 while the lane
wrote only 1.737 GB. A budget that counts only this lane's bytes budgets for a machine that does not
exist — which is why the reserve is 2 GB and why the fit test is run against free space *minus* that
reserve.

**What did *not* cause it** (checked, so the diagnosis is not a story): no SQLite or embedded
database carries market data (gzip JSONL only — `PASS`); retention **deleted nothing** (75 raw
segments retained, 913 planned-deletable, `deleted: 0`, `freed_bytes: 0`, 0 windows compacted), so
the shortfall could not be relieved downstream and had to be fixed upstream; and no authoritative
evidence was removed to make room.

**Cost, measured not padded** (planning rate 192.42 MB/h = the sealed window's own bytes ÷ its own
seconds, **plus** the measured non-segment overhead of 167 455 B/h = 0.087 %):

| horizon | required (mean) | required (1.5× stress) | fits now (17.62 GB free − 2 GB reserve) |
| --- | ---: | ---: | --- |
| 24 h | 4.618 GB | 6.927 GB | yes / yes |
| 48 h | 9.236 GB | 13.854 GB | yes / yes |
| 72 h | 13.854 GB | 20.763 GB | yes / **no** |

**Controls implemented** (justified by the finding, tested, and verified by a second implementation):

* `src/trading_bot/research/disk_budget.py` — the planner: rate taken from the audit's measurement
  with its source named, measured overhead added, 2 GB reserve, 1.5× stress planning.
* `scripts/start_paper_lab.py` — a **preflight (§10)** that refuses the window before any child
  starts. Default run now returns **exit 4**:
  `REFUSED: INCOHERENT_BUDGET — the collector valve cannot pay for the window: 1.100 GB affords
  5.72 h of the 24.00 h declared, and 4.618 GB is needed at 192.42 MB/h (this is the defect that
  stopped the first 24 h window)`.
  `--autoscale-collector-budget` raises the valve to the recommended **6.927 GB** and the same
  command passes.
* Raw evidence of both: [evidence/preflight_refusal.out](evidence/preflight_refusal.out) /
  [.err](evidence/preflight_refusal.err) and
  [evidence/preflight_autoscale.out](evidence/preflight_autoscale.out).
* Frozen evidence, audit trails and raw data were not touched: retention still deletes nothing, and
  no authoritative file was removed or rewritten by this lane.

## Q3 — Is the runtime stable over a full 24 hours?

**Not established. The window did not run, and the report says so in its own verdict:
`WINDOW_INCOMPLETE`.**

[WP9_RUNTIME_24H_REPORT.json](WP9_RUNTIME_24H_REPORT.json): `hours_executed: 0.06209` of
`hours_target: 24.0` → **0.2587 %** of the requested window; `window_complete: false`,
`stability_declared: false`, `checks_total: 13`, `checks_failed: 0`,
`checks_not_exercised: 4`. The rehearsal *is* prepared, driven and measured; the 24 h window is a
**time** requirement that cannot be satisfied by a shorter run, and no amount of instrumentation
converts 3.7 minutes into a stability certificate.

What the 3.7 minutes do establish (all `PASS`):

* the real entrypoint `scripts/autonomous_paper.py` ran **4 legs, each `exit 0`** — 51.953 s,
  69.157 s, 49.375 s, 53.031 s — against live public market data, in the mode the runtime itself
  reports as `paper`;
* **0 runtime failures, 0 orders, 0 production actions** across all 18 evaluations
  (`identity` per leg: 6/6, 2/2, 4/4, 6/6 hold);
* **no hidden critical error**: `0` errors in the leg reports; 9 cycles with latency
  **min 2 487 ms / max 5 743 ms**;
* **checkpoint/resume works**: leg 2 continued from record 6 (+2), leg 3 from record 8 (+4), leg 4
  from record 12 (+6), on the same run id, run root and `paper_state.json`;
* **no look-ahead**: every one of the 18 traces has `window_end_ts <= decision_time_ms`;
* **replay reconstructs every decision without touching the market**: 6/6, 8/8, 12/12, 18/18 ok,
  `failed=0`, `market_data_accessed=False`;
* **resource cost, from the whole child process tree** (a venv `python.exe` is a launcher stub;
  sampling it alone reports the stub): RSS ≤ **149.557 MB**, CPU ≤ **1.578 s** per leg
  (≈ 2–3 % of one core), disk **84–71 kB** per leg for the leg's own run dir. The paper runtime is
  nowhere near the binding constraint; **disk is** (Q2).
* **the controlled stop went through the runtime's own STOP file (§51)** and exited zero, and the
  resume continued the same chain rather than starting a new one.

Also honest and worth stating: the cadence matters. In leg 1 (free-running `--interval 20`) all 6
evaluations were **stale** (max age 537.7 s against a 450 s budget) and the router rejected all 6
for exactly that reason; in legs 2–4 (bar-close cadence and later legs) 0 were stale. Running the
loop faster than the data makes the freshness gate drop cycles — a real behaviour, measured, not a
failure.

## Q4 — What percentage of the real flow was executed?

**4 of 10 stages (`stages_reached: 4`), and the stages that were reached were reached 18/18.**

| stage | reached | evidence |
| --- | --- | --- |
| scan and bar history fetched | 18/18 | `traces.jsonl asset_context.bar_count` |
| regime and context built | 18/18 | `traces.jsonl regime` |
| router consulted | 18/18 | `traces.jsonl strategies_considered` |
| decision persisted to the trace chain | 18/18 | `traces.jsonl` |
| proposal built | **0/18** | `traces.jsonl proposal` |
| agents consulted | 0/0 | `traces.jsonl agent_messages` |
| risk engine evaluated | 0/0 | `traces.jsonl risk.risk_evaluated` |
| independent verifier ran | 0/0 | `traces.jsonl verification.verdict` |
| order created (`TRADE_PAPER`) | 0/18 | `traces.jsonl mode` |
| broker reconciliation / outcome resolved | 0/0 | `legs/*/RUN_REPORT.json totals.outcomes_resolved` |

`proposals: 0`, `proposal_share: 0.0`, `order_creating_stages_reached: 0`. The cause is stated by the
report itself: the router evaluated **108 candidates over 6 distinct strategies** with statuses
`['NOT_APPLICABLE', 'REJECTED']` — no admitted strategy and no candidate that emitted alpha, so no
proposal exists to hand to the agents, the risk engine or the verifier. Those three checks are
reported **`NOT_EXERCISED`, never `PASS`**: a branch the window never entered cannot be certified by
that window, and the report refuses to claim it.

**Calibration note for the operator:** the 4/10 figure is *not* a defect count. It is the honest
ceiling of a rehearsal whose admission ledger is empty by design (Q6). What this work package can
prove is that the four stages the market allowed are correct, replayable and gap-free; that the
other six are unreachable while the ledger stays empty; and that the flow's *shape* is measurable
rather than asserted.

## Q5 — What is still missing for M-03 and M-07?

Both hypotheses are **`NOT_READY`** against `config/microstructure_preregistration.json`
(`M-PREREG-V1`, preregistered 2026-09-29, whose own rule forbids lowering a threshold retroactively).
`researcher_ready: false`; the audit's own summary: *the infrastructure works and the cadence meets
the bar; the history does not exist yet, and no sample may be synthesised to fill it*.

**M-03 (order book imbalance) — 3/6 criteria met.** Met: checkpoints 1 984 ≥ 1 000; longest
unrecoverable gap 0 s ≤ 300 s; timeframes 1/5 min measurable. Not met:

| missing | requirement | observed | shortfall |
| --- | --- | ---: | ---: |
| `forward_book_hours` | ≥ 24 h | 4.159 h | **19.841 h** |
| `assets` | BTC, ETH, **SOL** | BTC, ETH | SOL never captured |
| `book_health_at_checkpoints_pct` | ≥ 90 % | — | **NOT_MEASURABLE** |

The `NOT_MEASURABLE` row is deliberate: the sealed manifest publishes the books' state *at shutdown*
(`STALE`, because the feeds stop) and never the fraction of the window they were healthy. A number
there would have been invented, so the criterion is reported as unanswerable by the evidence that
exists.

**M-07 (open interest × price) — 2/6 criteria met.** Met: sample interval 61.367 s ≤ 120 s;
timeframes 5/15/30 min measurable. Not met:

| missing | requirement | observed | shortfall |
| --- | --- | ---: | ---: |
| `open_interest_days` | ≥ 7 days | 0.1733 d | **6.827 d** |
| `min_oi_samples` | ≥ 10 000 | 488 | **9 512** |
| `disjoint_periods_required` | 3 disjoint, each ≥ 1 d | 0 | **3** |
| `assets` | BTC, ETH, SOL | BTC, ETH | SOL |

**Cost to close, and whether it fits on this volume:**

| hypothesis | window | at measured rate | at 1.5× stress | fits? |
| --- | ---: | ---: | ---: | --- |
| M-03 | **72 h** (24 h is the criterion; three non-overlapping DEV/VAL/OOS segments make 72 h the floor) | 13.842 GB | 20.763 GB | measured **yes**, stress **no** |
| M-07 | **168 h** (7 days; three disjoint ≥1-day periods cannot be cut from less) | 32.298 GB | 48.447 GB | **no** at either rate |

So the binding constraint is **not** the verifier, the replay gate (`REPLAY_VERIFICATION.json`:
411/411 fingerprints, `book_match: true`, deterministic, no internet) or the retention policy — it is
**history that has not been accumulated**, and on the present 93 %-full volume M-07 cannot be
accumulated at all without another volume (`--data-root`) or authorised deletion of raw that
compaction has already replaced. Two further facts are stated so they are not mistaken for evidence:
window 2 (`paper-lab-continuous-03`, 5.8868 h, `HEALTHY` at the end) **collected but never sealed**
a manifest, so it is **not usable as evidence**; and per the pre-registration the accumulation is
**already automatic** (`scripts/forward_collector.py`, started by `scripts/start_paper_lab.py`) —
what it lacked was a window its valve could pay for, which is exactly what Q2's preflight now
enforces before starting.

## Q6 — How many strategies have demonstrable net advantage?

**Zero. 0 of 24 ledger entries, and the report counts them from the artefact rather than asserting
it** ([WP9_ACTIVE_ECONOMIC_BLOCKERS.json](WP9_ACTIVE_ECONOMIC_BLOCKERS.json)).

* `strategies_total: 24`, `profitable_strategies: 0`,
  `strategies_with_demonstrable_net_advantage: 0`.
* Primary classifications: **17 `NO_ECONOMIC_ADVANTAGE`** (`NO_ALPHA` — no gross alpha before any
  cost) on top of **7 `EXECUTION_COSTS`** (`EXECUTION_COST` — a gross edge that does not survive the
  round trip). 17 strategies are *flagged* `EXECUTION_COSTS` as a secondary reading; the two roles
  are kept separate rather than collapsed.
* The cost plane reproduces its frozen value: **23.3536 bps** (stress 35.0303 bps).
  `cost_plane_reproduces_frozen_value: true`.
* The best gross cell in the registry is **`volatility@30m` at 8.912 bps**, which is
  **14.442 bps short** of the plane. Every registered cell is `clears_the_plane: false`; the closest
  is that one, and the family rank then runs `volatility@1h` (6.276, −17.078),
  `mean_reversion@30m` (5.472, −17.882), `mean_reversion@15m` (2.714, −20.640), `trend@30m` (2.206,
  −21.148), `mean_reversion@5m` (1.4854, −21.868), `trend@15m` (1.284, −22.070), `breakout@5m`
  (−0.084, −23.438).
* `binding_blocker`: **`EXECUTION_COSTS (primary for 7, flagged for 24) on top of
  NO_ECONOMIC_ADVANTAGE (primary for 17)`** — the honest reading is that the *primary* wall for
  most of the registry is that there is no edge to begin with; costs merely finish off the seven
  that had some.
* No frozen criterion was modified by this audit (`frozen_criteria_changed: false`), and R6 P2
  QUALITY is left **separate and unused as evidence** — the label does not exist in this repository,
  so it is an operator-side lane and is neither mapped nor inferred.

## Q7 — What conditions block paper?

Four, and none of them is "the runtime is broken":

1. **No admitted strategy exists to promote.** `ADMITTED_STRATEGIES: 0`, `paper_candidates: []`,
   `PAPER_PROMOTION: NOT_AUTHORIZED` (`governance` in the economic report). The router in Q4
   therefore has nothing to select, which is *why* the flow stops at "proposal built" — the stop is
   a consequence of an empty admission ledger, not a runtime defect.
2. **The operator gate is not satisfied.** This work package was executed **without paper
   authorisation**, so the runtime rehearsal is a read-only market-data rehearsal
   (`paper_authorisation: NOT_AUTHORIZED — this is a read-only market-data rehearsal, not the
   contractual paper test`). The gate stays closed; a replay/shadow result was not promoted into it.
3. **Disk: a 24 h accumulation is not payable by the naive configuration.** The default preflight
   refuses with `exit 4` (1.1 GB affords 5.72 h of 24 h); the payable valve is **≥ 6.927 GB**
   (`--autoscale-collector-budget`). And the *evidence* window requires a **sealed manifest**: a run
   that stops without one (WP9-DISK-02) produces data that cannot be used, so stopping cleanly is
   part of the gate.
4. **Governance floor, unchanged:** `LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`,
   `PROFITABILITY_VERIFIED = false`, `FALSE_SUCCESS = 0`. Nothing in this work package is
   profitability evidence, and 3.7 minutes of correct mechanics is not a licence to trade.

## Q8 — What is the next justified economic experiment?

**E-1 — measure the cost plane; then E-2 — the 30-minute entry screen.** In that order, from the
report's own priority list:

1. **E-1 (priority 1, `EXECUTION_COSTS`)**: a measured round trip on the forward book with a frozen
   order policy, reported as a **distribution rather than a model**. Cost: **uses data already being
   captured — no new window**. Unblocks: **the ranking of every registered family at once**, because
   23.3536 bps is currently a *model*, and a model is exactly what all 24 verdicts depend on.
2. **E-2 (priority 2, `NO_ECONOMIC_ADVANTAGE`)**: a forward-drift entry screen at **30m**, where the
   best gross edge lives (`volatility@30m`, 8.912 bps), pre-registered against the existing
   partitions. Unblocks: whether *any* entry-side variant is net-positive at all.
3. Priority 3 (`INSUFFICIENT_DATA`) is the M-03/M-07 accumulation of Q5 — 72 h and 7 days — and is
   blocked on volume, not on code.
4. Priority 4 (`RUNTIME_FAILURE`) is defect **DEF-206** (it flags 20 strategies without deciding
   any): a code change with contract tests, no new data, and **no economic value on its own** — worth
   doing, but not the next economic experiment.

The RFC that would carry E-1/E-2 **did not exist**, and creating it is therefore not duplication:
[RFC_050_COST_AND_ENTRY_DRAFT.md](RFC_050_COST_AND_ENTRY_DRAFT.md) is written as a **`DRAFT`,
`authorized: false`** — it proposes, it does not run. Its number is derived from the tree (the
highest number actually occupied, 049), because `docs/roadmap/RFC_REGISTRY.json` still calls `048`
free while `048` and `049` are both occupied (`derived_next_free: 50`); the registry is flagged as
stale rather than trusted. **No campaign was launched**: E-1 and E-2 are proposals awaiting an
operator's authorisation.

## Q9 — Which commits, tests and evidence support each result?

**Commits.** Everything runs at **`HEAD 5348fcd55ab9ef404c676d8aada8daa8c85b9785`** (`main`,
2026-10-11), 256 commits ahead of `origin/main`. The verifier records the head it ran on
(`head: 5348fcd…`). `main` is the WP-8 commit ("Carry the verifier's record with the report that
names it"). **This lane's artefacts are uncommitted** (see the revision note at the top): the tree
also holds other lanes' modified files, and this lane will not stage work it did not author.

**Tests** (all on `5348fcd` + working tree):

| run | result |
| --- | --- |
| `uv run python -m pytest tests/unit/research/test_wp9_disk_budget.py tests/unit/autonomous/test_lab_operations.py -q` | **32 passed** (2.47 s) — the new planner/preflight tests plus the lab-operations contract they extend |
| `uv run python -m pytest tests/unit -q -x` | **3361 passed** (421.29 s) |
| `uv run python -m pytest tests/regression tests/bdd -q` | **23 passed** (0.26 s) |
| `uv run python -m pytest tests/integration -q` | **24 passed** (4.07 s) |

**Independent verification** ([INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json)):
`verdict: PASS`, **41 checks, 0 failed**, **12 of 12 negative controls detected**,
`false_success: 0`, `builder_imported: false`. Method: *a second implementation — every headline
number re-derived from a primary artefact (the sealed manifest, the segment files, the
pre-registration, the frozen cost components, the workflow text, the traces) and compared with what
the builder published; each check is shown to fail under a deliberate mutation.* Builders it
re-derives rather than imports: `wp9_disk_budget_audit.py`, `research/disk_budget.py`,
`wp9_m03_m07_readiness.py`, `wp9_economic_blockers.py`, `wp9_ci_audit.py`, `wp9_runtime_rehearsal.py`.
The controls include: a 1 % change in the rate must break D1; one byte of drift in the segment sum
must break D3; changing the reserve must flip the D4 fit verdict; a doubled fee must be visible in
E1; a softened workflow step must be found by reading the YAML (CI1); a moved trace boundary and a
substituted chain link must fail T6/T2.

**Evidence trail — one home per claim:**

| claim | artefact / command |
| --- | --- |
| CI blocked, workflow audit, 12-step local sequence | [WP9_CI_EXECUTION_REPORT.json](WP9_CI_EXECUTION_REPORT.json) · `uv run python scripts/wp9_ci_audit.py` · [.ci/wp9/](../../../.ci/wp9/) stdout/stderr |
| the 4.16 h stop, the 24/48/72 h cost | [WP9_DISK_BUDGET_AUDIT.json](WP9_DISK_BUDGET_AUDIT.json) · `uv run python scripts/wp9_disk_budget_audit.py` |
| the preflight refusal (exit 4) and its autoscaled pass | [evidence/preflight_refusal.out](evidence/preflight_refusal.out) · [evidence/preflight_autoscale.out](evidence/preflight_autoscale.out) · `uv run python scripts/start_paper_lab.py --duration-hours 24 --dry-run` |
| the runtime rehearsal, its limits, its flow coverage | [WP9_RUNTIME_24H_REPORT.json](WP9_RUNTIME_24H_REPORT.json) · `reports/autonomous-paper/wp9-runtime-legs/**` (traces, legs, `LEGS.json`) |
| M-03 / M-07 shortfalls | [WP9_M03_M07_READINESS.json](WP9_M03_M07_READINESS.json) · `config/microstructure_preregistration.json` |
| the economic wall | [WP9_ACTIVE_ECONOMIC_BLOCKERS.json](WP9_ACTIVE_ECONOMIC_BLOCKERS.json) · `config/strategy_admission.json`, `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` |
| the folded summary of all of it | [RUN_REPORT.md](RUN_REPORT.md) · `uv run python scripts/wp9_run_report.py` |

**Deliberately not claimed anywhere in this package:** that any workflow ran on a GitHub runner; that
the runtime is stable for 24 h; that any strategy is profitable; that M-03 or M-07 can be researched
yet; that the agents, the risk engine or the independent verifier were exercised in the live window
(they were `NOT_EXERCISED`); that the unsealed window 2 is evidence; and that any paper or live
authorisation was granted.

---

## Status

**PARTIAL.** Every capability this work package set out to *build and verify* is built, tested and
independently verified: the disk defect is diagnosed to its arithmetic cause and now refused before
the first child starts; the real runtime ran, was folded through a controlled stop and a resume,
replayed without market access, and its flow coverage is measured honestly at 4/10 stages; M-03 and
M-07 are audited against a frozen pre-registration with their shortfalls and their *cost to close*
stated; the economic wall is classified per strategy rather than summarised; and an RFC-050 draft
exists without running anything.

Every gate that is *withheld* is withheld by its own criterion, not by inconvenience: **CI_CERTIFIED**
needs a runner run id (no credentials, no registration, and publishing 256 commits is a governance
decision), and **24 h stability** needs 24 h of wall clock that a 3.7-minute rehearsal cannot
substitute. The two things a reader should take away are (a) the *day* of runtime is now startable —
the preflight will refuse anything a valve cannot pay for and will name the payable value — and
(b) nothing in the ledger has a demonstrable net advantage, so the honest next move is E-1: replace
the 23.3536 bps cost *model* that every one of the 24 verdicts rests on with a measurement.
