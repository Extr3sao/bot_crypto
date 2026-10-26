# Runtime authority map — Trading Agentic Portable

> Versioned record. Generated 2026-10-23T18:53:56Z while recovering the
> multi-agent audit after MT-0004 was blocked with `BLOCKED_SPEC`.
>
> This file exists because the audit corpus used to live in `reports/`, which
> `.gitignore:55` excludes (`reports/*`). Nothing under `reports/multiagent-audit`
> was ever committed (`git log --all --oneline -- reports/multiagent-audit`
> returns 0 commits), so a worktree reset destroyed every contract in it. The
> map below is derived from git objects and from imports in the tree, not from
> those lost notes.

## 1. How this map was produced

Every claim below is reproducible with a command in the same commit. The
commands are printed next to the claim; the revision is pinned by SHA because
`codepaper/supervisor-001` is a moving branch (it advanced twice during this
recovery: `60455b46` → `0e2ba09d` → `cc4f15f6`).

```bash
git rev-parse HEAD                                  # 0e2ba09d47625fd899bee4e4fd3a82a0232c2d29
git rev-list --left-right --count main...HEAD       # 0       299
git merge-base --is-ancestor 60455b46 HEAD          # exit 0 → MT-0003 is an ancestor
git log --all --oneline -- reports/multiagent-audit # (empty) never tracked
git log --all -S'MT-0004' --oneline                 # only 9c83e62a (MT-0002)
```

## 2. Branch inventory and the authority decision

| Ref | SHA | Date | Relation to `main` | Verdict |
|---|---|---|---|---|
| `main` | `1d2192b0` | 2026-10-12 | — | **Legacy.** Does not contain MT-0003: no `kill_switch_v2` importer, no `tests/unit/autonomous/test_decision_kill_switch.py`. |
| `codepaper/supervisor-001` | `cc4f15f6` (moving) | 2026-10-23 | 299 ahead, 0 behind | **Authoritative line of development.** Contains `9c83e62a` (MT-0002) and `60455b46` (MT-0003) in its ancestry. |
| `recovery/mt0003-kill-switch-60455b46` | `60455b46` | 2026-10-23 | 298 ahead | Preservation ref created in the blocked run so `git gc` could not prune MT-0003. Still points at the MT-0003 commit, not at a descendant. |
| `recovery/trunk-format-001` | `dc21870f` | 2026-10-23 | separate lane | Line-ending/format lane. Does not contain the MT token (`git grep MT-0004 recovery/trunk-format-001` → empty). |
| `audit/mt0004-negative-controls` | `0e2ba09d` | 2026-10-23 | 299 ahead | **This task.** New branch cut from `codepaper/supervisor-001@0e2ba09d`, pinned by SHA so later supervisor commits cannot silently change the baseline. |

`main` being 299 commits behind is not the only reason it loses: it also lacks
the control entirely. More commits alone would not have decided it — the
decisive test is reachability of the MT-0003 gate inside the tree, checked in
§3.

Worktrees in play at measurement time:

```text
.../bot freebuff            1d2192b0 [main]                          (dirty: other lanes)
.../bot freebuff/wt-sup001  0e2ba09d [codepaper/supervisor-001]      (dirty: other lanes)
.../ff-wt-base              1d2192b0 (detached)
.../ff-wt-trunkfmt          dc21870f [recovery/trunk-format-001]
.../ff-wt-mt0004            0e2ba09d [audit/mt0004-negative-controls]
```

No original branch was reset, deleted or rewritten. The dirty trees belong to
other lanes and were not staged, committed or reverted by this task.

## 3. Kill-switch reachability

```bash
grep -rn 'kill_switch_v2' --include='*.py' src scripts tests
# src/trading_bot/autonomous/decision.py:36   ← the only production importer
# tests/unit/autonomous/test_decision_kill_switch.py
grep -rn 'from trading_bot.paper.kill_switch import' --include='*.py' src scripts tests
# (empty)
```

| Component | Classification | Evidence |
|---|---|---|
| `src/trading_bot/paper/kill_switch_v2.py` (`KillSwitch`, 5 states) | **RUNTIME_AUTHORITATIVE** | Imported by `autonomous/decision.py:36`; that is the object rule 0 reads. |
| `src/trading_bot/domain/enums/kill_switch.py` (state enum + allowed-action table) | **RUNTIME_AUTHORITATIVE** | Consumed by `kill_switch_v2`; `KILL_SWITCH_ALLOWED_ACTIONS` defines what each state permits. |
| `src/trading_bot/autonomous/decision.py` (`_kill_switch_no_trade`, rule 0) | **RUNTIME_AUTHORITATIVE** | Called at the top of both `intend` and `decide`. |
| `src/trading_bot/autonomous/runtime.py` | **RUNTIME_AUTHORITATIVE consumer** | `runtime.py:341` builds `DecisionEngine()` with no injected switch, so the runtime reads the process authority. |
| `src/trading_bot/risk/futures/integration.py` (`run_through_decision_engine`) | **RUNTIME_REACHABLE** | Builds `DecisionEngine()` at line 332, so it inherits rule 0. |
| `src/trading_bot/paper/kill_switch.py` (V0.3 `KillSwitch`) | **ORPHAN** | Zero importers in `src/`, `scripts/`, `tests/`. Two classes named `KillSwitch` in the codebase; only `kill_switch_v2` is wired. |
| `src/trading_bot/paper/paper_cycle.py` (`PaperCycleEngine`) | **RUNTIME_REACHABLE, gate present (G-4)** | Imported by `paper/harness.py:31` and `scripts/start_paper_trading.py:34`. Its imports (`grep -n '^from' paper_cycle.py`) include `risk.manager.RiskManager`, `risk.defensive_blocks` and `autonomous.hot_stop.HotStopGate`; the launcher injects a gate over `process_kill_switch()` and a run directory, so the entry dispatch is refused by the same hot-stop authority as the autonomous runtime. It still does not import `autonomous.decision`: G-4 closes the stop boundary, not rule 0. |
| `src/trading_bot/app.py` — `kill-switch`, `status` | **RUNTIME_REACHABLE, refuses** | Both are in `NOT_IMPLEMENTED_SUBCOMMANDS` (`app.py:66`) and `main` returns 2 with an empty stdout (`app.py:1392-1400`). No in-process activation surface exists. |
| `tests/unit/autonomous/test_decision_kill_switch.py` | **TEST_ONLY** | 35 cases over rule 0, including the real runtime. |
| `tests/unit/test_app_cli_contract.py` | **TEST_ONLY** | Drives `python -m trading_bot.app` in a subprocess; AST scan of `main`. |

### TEST_TARGET == RUNTIME_TARGET

Tests only prove something about the runtime if they import the tree under
test. Verified explicitly, not assumed:

```bash
uv run --frozen python -c "import trading_bot; print(trading_bot.__file__)"
# C:\...\ff-wt-mt0004\src\trading_bot\__init__.py
```

The `.venv` of this worktree is an editable install pointing at *this*
worktree's `src` (`.venv/Lib/site-packages/__editable__.crypto_scalping_agentic_bot-0.1.0.pth`),
and `PYTHONPATH` takes precedence over that `.pth` (verified with a sentinel
module), which is what makes the mutation harness in
`scripts/audit/negative_controls.py` able to test a mutated copy without
touching the working tree.

## 4. MT-0003 recovery

`60455b46` is an ancestor of this branch and the control is present in the
tree; nothing had to be cherry-picked.

```bash
uv run --frozen pytest tests/unit/autonomous/test_decision_kill_switch.py \
                       tests/unit/test_app_cli_contract.py -q
# 43 passed
```

Decision-engine order in this tree (first match wins): **0 kill switch**,
1 agent veto, 2 verifier, 3 no proposal, 4 unknown strategy, 5 binding risk
veto, 6 gross edge, 7 paper admission. Rule 0 reads no request field.

## 5. Declared gaps (still open — not closed by this task)

| Gap | Meaning | Status in this tree |
|---|---|---|
| **G-1** | Kill-switch state is not persisted; a restart boots `NORMAL` | **Closed for the autonomous path** by `docs/audit/G-1.md`: `HotStopGate` adopts `<run_dir>/KILL_SWITCH` in its constructor, before any broker call, and `engage` writes the marker atomically. Scope is the run directory — a new `--run-id` is a new scope and boots operational, which the contract states and pins with a test. `KillSwitch` itself still has no store, by design. |
| **G-2** | No hot activation from the CLI | **Closed for the autonomous path** by `docs/audit/G-2.md`: `HotStopGate` polls `<run_dir>/KILL_SWITCH` and holds the lock across `broker.execute_signal`, so an ACK means nothing is in flight. `kill-switch --run-dir … --engage` writes that file; `status` stays a stub. The `paper_cycle` and live paths remain **unprotected** (G-3/G-4). |
| **G-3** | Live order paths that bypass `DecisionEngine` | Open. Not measured here; the CLI's live path was not exercised in this task. |
| **G-4** | Duplicate engine `paper/paper_cycle.py` | **Closed for the paper launcher** by `docs/audit/G-4.md`: `PaperCycleEngine` now refuses an entry at `HotStopGate.order_boundary`, and `scripts/start_paper_trading.py` builds the gate over `process_kill_switch()` and `<run-dir>/KILL_SWITCH`. `run --demo` was never on this path: it runs the synthetic scanner only. The module still does not import `autonomous.decision`; route-to-one-engine is a separate architectural change, not a stop bypass. |

## 6. What this map cannot tell you

- **The original MT-0004 contract.** It is not in any git object. See
  `docs/audit/MT-0004-R1.md` §2.
- **Whether MT-0040 exists.** The identifier appears in no committed file and
  in no commit message (`git log --all -S'MT-0040'` → empty). Any reference to
  it is recollection, not evidence.
- **The live path.** `execution/live_gate.py` reads
  `settings.risk.kill_switch_enabled`, a *config boolean*, not the runtime
  state from `kill_switch_v2`. This is the mechanism behind G-3 and it was not
  exercised, so it is recorded as an untested claim, not a verified defect.

## 7. Addendum — the refs moved while this run was open

`codepaper/supervisor-001` and `main` are being written by other lanes. Both
advanced during this task, so §2 is a snapshot, not a live view. Re-measured at
2026-10-23T19:10Z and again at commit time:

| Ref | Then (§2) | Now | Does the authority decision change? |
|---|---|---|---|
| `main` | `1d2192b0` | `47ca8dac`, then `cedc1346` | **No.** `git merge-base --is-ancestor 60455b46 main` → NO; `git grep kill_switch_v2 main -- src/trading_bot/autonomous/decision.py` → none; `main:tests/unit/autonomous/test_decision_kill_switch.py` does not exist. |
| `codepaper/supervisor-001` | `60455b46` | `3b758e22` | **No.** `60455b46` is still an ancestor; this branch was cut at `0e2ba09d` and is pinned by SHA. |

The rule that decides is the reachability check in §3, not the tip of any
branch: a branch with more commits is authoritative only when the gate is
reachable from it.

## 8. Addendum — the G-2 boundary (2026-10-23)

G-2 measured this tree at `27db70ef` and added one row to §3's picture. The
broker boundary is no longer just `runtime.py:1455`: it is that call **inside**
`HotStopGate.order_boundary`.

```text
scripts/autonomous_paper.py
  → AutonomousPaperRuntime.run / run_cycle          (runtime.py:422, 552)
      → run_cycle: hot_stop.poll()                  (cycle boundary)
      → _evaluate_asset → DecisionEngine.decide     (rule 0, MT-0003)
      → _execute_paper                              (runtime.py:1414)
          → hot_stop.order_boundary()  [lock held]  (hot_stop.py)
              → broker.execute_signal               (the only dispatch)
```

| Path | Boundary | Covered |
|---|---|---|
| `scripts/autonomous_paper.py` | `runtime.py:1455` inside the gate | **yes** |
| `scripts/start_paper_trading.py` → `paper_cycle` | `paper_cycle.py` dispatch inside `HotStopGate.order_boundary` | **yes** (G-4) |
| `trading-bot run --demo` | no broker: `_run_single_iteration` → `_build_demo_scanner` (fake data) | n/a — no sink |
| `trading-bot place-order`, `--auto-trade` | Bitunix clients | **no** in this row — live, closed by G-3/P0/RFC |

`grep -n "execute_signal" src/trading_bot/autonomous/runtime.py` returns exactly
one dispatch site, which is why a single boundary is sufficient here and why a
second one appearing later invalidates the G-2 claim.

## 9. Addendum — the live gate boundary (2026-10-24, P0)

G-3 installed the hot stop at the live sinks and explicitly left
`execution/live_gate.py` out of scope. P0 (`docs/audit/P0-LIVE-GATE.md`) closed
that defect: before P0, `grep -rn LiveTradingGate src/` matched only the module
and its package `__init__`, so a deployment the gate would reject still sent an
order.

The live path now has two authorities at the same boundary, in this order:

```text
trading-bot run --mode live --auto-trade      trading-bot place-order
trading-bot close-position / set-tpsl
  → _cmd_run (pre-flight: stop? gate? → exit 2 before any client)
      → _maybe_execute_live_* (entry)
          → _live_order_boundary(opens_risk=True, settings=…)
              → hot-stop switch check        (KILL_SWITCH_ENV / HotStopGate)
              → LiveTradingGate.validate()   (ten checks, all must pass)
                  → HotStopGate.order_boundary()  [lock held]
                      → broker sink
```

| Path | Gate | Evidence |
|---|---|---|
| `run --auto-trade` futures/spot entry | **yes** | startup + boundary; 0 calls with any rejected check |
| `place-order` futures OPEN / spot buy | **yes** | pre-client + boundary |
| `close-position`, `set-tpsl`, futures CLOSE, spot sell | no (exempt) | 1 call with GATE-004 rejected |
| `run --demo` | n/a | no broker or client is constructed (G-4 probe) |

`HotStopGate` still owns the stop and is still byte-identical to `a072da90`.

## 10. Addendum — order-derived authorisation (2026-10-25, RFC-TAP-EXEC-SEC-002)

The P0 row that exempted `close-position`, `set-tpsl`, futures `CLOSE` and spot
`sell` was a caller-supplied boolean. RFC-TAP-EXEC-SEC-002
(`docs/audit/RFC-TAP-EXEC-SEC-002.md`) replaced it with a category derived at
the sink from the order, the position and the venue's real payload:

```text
CLI/runtime
  → hot stop (marker / process switch)
  → confirmation (`--confirm-live`) for run --auto-trade and place-order
  → _live_order_boundary(intent, position, capabilities, settings, confirm_live)
      → classify_order(...)                       # deterministic, no name
      ├─ PROVEN_REDUCTION  → reduction payload guard → broker
      └─ OPEN_OR_INCREASE / UNKNOWN → stop check → ten gate checks
                                       → HotStopGate.order_boundary() [lock]
                                       → broker
```

| Entrypoint | Category today | Gate |
|---|---|---|
| `run --auto-trade` futures OPEN / spot buy | `OPEN_OR_INCREASE` | yes, plus `--confirm-live` |
| `place-order` futures OPEN / spot buy | `OPEN_OR_INCREASE` | yes, plus `--confirm-live` |
| `place-order` futures CLOSE + `--reduce-only`, matching one-way position | `PROVEN_REDUCTION` | no |
| `close-position` with an observable position | `PROVEN_REDUCTION` (venue closes by id) | no |
| `run` stale-position flatten | `PROVEN_REDUCTION` (same primitive) | no |
| `set-tpsl` | `UNKNOWN` | yes |
| `place-order` spot `sell` | `UNKNOWN` | yes |
| futures `CLOSE` without `reduceOnly`, hedge/ambiguous mode, excess qty, no position, stale snapshot, unreadable position | `UNKNOWN` | yes |
| `scripts/start_paper_trading.py` paper entry | not a live order | paper hot stop, no live gate (G-4) |
| `run --demo` | not classified — no broker | n/a (G-4) |

The proof is revalidated on the **wire payload** inside the adapter, immediately
before `_request`: `reduceOnly` must be `true`, `tradeSide` must be `CLOSE`, the
side must close the position, `0 < qty <= position.qty`, and a flash-close
payload may contain nothing but `positionId`. A `PROVEN_REDUCTION` is recorded
in `live_order_authorizations.jsonl` with the rule and a non-sensitive settings
fingerprint.

`HotStopGate` still owns the stop and is still byte-identical to `a072da90`.
The gate does not replace it: P0's refusal for a stopped process names the stop,
not the gate, and an already-stopped `run` keeps G-3's start-and-report
behaviour. The gate's verdict is the stricter `failed_gates == 0`, not
`GateReport.all_passed`: GATE-006 and GATE-008 are rated `high` by the class, and
a rejected check must still stop an order. That policy lives in
`app._evaluate_live_gate`, not in the gate.

## 11. Addendum — G-4 paper route and the retired demo claim (2026-10-25)

G-4 measured the route instead of repeating the previous sentence. The result
has two rows, and they are different:

```text
scripts/start_paper_trading.py
  → PaperOrchestrator → PaperSessionRunner → PaperCycleEngine
      → RiskManager.check_signal              (already present)
      → _hot_stop_verdict()                   (marker / process switch)
      → HotStopGate.order_boundary() [lock]   (same class as G-2)
          → PaperBroker.execute_signal        (the paper sink)
```

```text
trading-bot run --demo / --mode paper --auto-trade
  → _cmd_run → _run_single_iteration → _build_demo_scanner
      → market_data.fake                      (synthetic snapshots)
      → _print_demo_results                   (no broker, no exchange client)
```

`run --demo` was never joined to `paper_cycle` in git history:
`git log -S'PaperCycleEngine' -- src/trading_bot/app.py` returns no commit. The
previous map rows that said otherwise were a documentation defect, not a code
path. `app.py` now has no `PaperCycleEngine`, `PaperBroker` or `execute_signal`
symbol at all, and the G-4 probe runs the command with those sinks instrumented:
zero calls, exit 0, both with and without `--auto-trade`.

For the real paper route, the marker is `<run-dir>/KILL_SWITCH`; the default is
`data/storage/paper` (`PAPER_RUN_DIR` overrides), and
`trading-bot kill-switch --run-dir data/storage/paper --engage` writes it. A
stop is checked after risk approval and re-checked under the boundary lock. A
reduction (`PaperBroker.close_position` from the opposite-signal path) stays
outside the stop, so a stop does not trap the book.

What is still not true: `paper_cycle` does not route through
`autonomous.decision.DecisionEngine`, so rule 0 and the paper engine remain two
decision implementations. G-4 closes the *stop* bypass on the reachable paper
entrypoint; it does not merge the engines and does not claim they are one.

## 12. Addendum — G-5 paper end-to-end (2026-10-25)

G-5 executed the route above instead of only describing it. The canonical
composition is `scripts/start_paper_trading.py::build_cycle_engine` feeding
`PaperOrchestrator → PaperSessionRunner → PaperCycleEngine`; the measured run
opened one paper position, persisted it in `PaperStateStore`, restored it with
`StartupReconcilerV4` in fresh instances, and closed it through
`PaperBroker.reconcile_session` at take-profit. The evidence is
`docs/audit/runs/run-20261025T131004Z-G-5/` (`evidence.json`, 12/12 clean-export
verification).

Two clarifications this addendum pins:

- `trading-bot run --mode paper` is **not** the paper engine. It still runs the
  synthetic scanner only and now says so on stdout
  (`paper_cycle=NOT_RUN`, `broker=NOT_CONSTRUCTED`). Connecting it to the
  broker would violate G-4 REQ-G4-02, so it remains `NOT_REACHABLE`.
- `PaperSessionRunner._market_conditions` now uses the injected `now_fn` (wall
  clock by default) for the defensive blocks. Before G-5 it used the wall
  clock directly, which could attribute a rejection to `weekend_trading` while
  the replay clock said Wednesday. Policy is unchanged; the session has one
  clock.

The operational limit is unchanged and explicit: the committed
`config/strategy_admission.json` admits no strategy, so the real launcher ends
in `NO_TRADE`. The trade in the evidence uses
`docs/audit/fixtures/g5_paper_ledger.json` (`CONTROLLED_TEST_FIXTURE`), which is
reachability evidence, not a production admission or an edge claim.

## 13. Addendum — G-6 durable PAPER execution (2026-10-25)

G-6 measured the crash boundary that G-5 had left as a logical restart. The
reachable paper launcher now uses `DurablePaperBroker` over the existing
`PaperStateStore`; the broker records `PREPARED`, `FILLED` and `ACCOUNTED`
before the next boundary, and `StartupReconcilerV4` is the sole recovery
authority:

- `PREPARED`/`FAILED` means the broker may have acted. The cloid is already in
  `sent_intents`; recovery marks it `BLOCKED_UNKNOWN` and never resends it.
- `FILLED` carries the exact position row against the pre-fill accounting
  snapshot. Recovery materializes that position once and persists `ACCOUNTED`.
- `ACCOUNTED` must match the restored book; if the position is closed, a
  persisted `ClosedTrade` naming the same `position_id`/`entry_order_id`
  converts the row to `CLOSED`. Anything else is `FATAL`.
- The recovery outcome is persisted atomically, so a second kill/reopen sees
  `ACCOUNTED`/`CLOSED`/`BLOCKED_UNKNOWN` and repeats no economic effect.

Evidence: `docs/audit/runs/run-20261025T141859Z-G-6/` — four real
`taskkill /F /T` terminations, two consecutive restarts, inconsistent and
corrupt books failing closed, a kill switch blocking the broker during
recovery, and a recovered position closed once at take-profit. Clean-export
verifier: 17/17, `FALSE_SUCCESS=0`.

What is still not true: `paper_cycle` and `autonomous.decision` remain two
engines, the data is synthetic, and the kill/recovery uses the same disk. No
exchange client or credential is constructed; `LIVE_NO_GO` and
`PRODUCTION_READY=false` are unchanged.

## 14. Addendum — G-7 real public market data (2026-10-25)

G-7 replaced the synthetic input of the G-5/G-6 evidence with a real public
capture, without adding a second runtime. The authoritative route is
unchanged; only the market-data source and the validation gate are new:

```text
PublicRestKlineSource (read-only public REST; no session, no credentials)
  → capture (bars + quotes + received_at)
      ├─ HISTORICAL_REPLAY: ReplayMarketDataSource at a pinned decision
      └─ FORWARD: same rows, consumed after the provider answered
  → validate_closed_bars (PIT, gaps, duplicates, freshness, OHLC)
  → UniverseScanner → CryptoAssetAgentRegistry
  → StrategyRouter.select_eligible_strategies
      → 0 SELECTED (ledger admits 0/24)
  → NO_TRADE:no_strategy_passed_gates
  → RiskManager / HotStopGate / DurablePaperBroker not reached
```

| Component | Classification | Evidence |
|---|---|---|
| `src/trading_bot/market_data/public_rest.py` | **RUNTIME_REACHABLE, data-only** | `scripts/start_paper_trading.py --provider public`; `scripts/audit/g7_real_paper.py`; endpoint allowlist has no order route. |
| `src/trading_bot/market_data/real_data_validation.py` | **RUNTIME_AUTHORITATIVE gate** | Both replay and forward snapshots are produced by `validate_closed_bars`; the cycle refuses non-`OK` snapshots. |
| `src/trading_bot/paper/eligibility.py` | **EVIDENCE_ONLY** | Reads `StrategyRegistry`/`StrategyRouter`; no mutation of ledger, registry or router. |
| `scripts/audit/g7_real_paper.py` | **EVIDENCE_DRIVER** | Uses `build_cycle_engine`, `PaperOrchestrator`, `DurablePaperBroker`, `StartupReconcilerV4`; does not implement a second engine. |
| `scripts/audit/verify_g7.py` | **VERIFIER, separate** | `git archive` export; runs replay/tests inside it; does not import the builder. |

Reachability checks that matter:

```bash
grep -n "PublicRestKlineSource\|ReplayMarketDataSource" scripts/start_paper_trading.py scripts/audit/g7_real_paper.py
grep -n "validate_closed_bars" src/trading_bot/market_data/public_rest.py
grep -n "execute_signal\|order" src/trading_bot/market_data/public_rest.py   # no order path
```

The measured outcome is `G7_BLOCKED_NO_ELIGIBLE_STRATEGY`: real data reached
the router, the router selected nothing, and the broker was not called. The
LIVE gate and `hot_stop.py` remain byte-identical (SHA-256 `edabd6d3…` and
`76cfca23…`). `paper_cycle` still does not import `autonomous.decision`; G-7
does not merge them and does not claim to.
