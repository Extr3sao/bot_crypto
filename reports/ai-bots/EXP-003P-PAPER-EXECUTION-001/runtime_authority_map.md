# RUNTIME AUTHORITY MAP — EXP-003P

> Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE >
> ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`. A class on disk is not authority.

## Entrypoints

| id | path | kind | evidence |
| --- | --- | --- | --- |
| `PRIMARY_PAPER_RUNTIME` | `scripts/autonomous_paper.py` | autonomous PAPER/SHADOW loop | documented in docs/runtime/runtime_authority_map.md; not executed by 003P |
| `LEGACY_PAPER_LOOP` | `scripts/start_paper_trading.py` | PaperOrchestrator loop | static; superseded per docs/runtime/runtime_authority_map.md |
| `VISION_LANE_REPLAY` | `scripts/exp_003p_rehearsal.py` | frozen-bar replay through VisionLane | executed by 003P (EXECUTION_TRACE.jsonl) |
| `LIFECYCLE_SCENARIO` | `scripts/exp_003p_rehearsal.py` | offline venue scenarios through LifecycleEngine | executed by 003P (SCENARIO_TRACE.jsonl) |
| `LIFECYCLE_CONTROLS` | `scripts/exp_003p_controls.py` | adversarial controls | executed by 003P (NEGATIVE_CONTROLS.json) |

## Component classification

| component | path | classification | evidence |
| --- | --- | --- | --- |
| `trading_bot.paper.broker.PaperBroker` | `src/trading_bot/paper/broker.py` | RUNTIME_AUTHORITATIVE (execution boundary) | executed by this baseline probe and the rehearsal |
| `trading_bot.paper.lifecycle.PaperBrokerRecorder` | `src/trading_bot/paper/lifecycle/recorder.py` | RUNTIME_AUTHORITATIVE (instrumentation, added by 003P) | executed: emits ORDER_CREATED..ORDER_FILLED from real broker fills |
| `trading_bot.paper.lifecycle.LifecycleEngine` | `src/trading_bot/paper/lifecycle/engine.py` | RUNTIME_AUTHORITATIVE (event construction, added by 003P) | executed: refusal and scenario paths in the controls |
| `trading_bot.vision.lane.VisionLane` | `src/trading_bot/vision/lane.py` | RUNTIME_AUTHORITATIVE | executed by the rehearsal on frozen bars |
| `trading_bot.risk.manager.RiskManager` | `src/trading_bot/risk/manager.py` | RUNTIME_AUTHORITATIVE | executed inside VisionLane; risk refusals recorded by the controls |
| `trading_bot.paper.lifecycle.venue.SimulatedPaperVenue` | `src/trading_bot/paper/lifecycle/venue.py` | TEST_DOUBLE (not an execution platform) | executed by the scenario phase; every event is OFFLINE_SIMULATED |
| `trading_bot.execution.* live adapters` | `src/trading_bot/execution/` | OUT_OF_SCOPE (live) | not imported by any 003P entrypoint; asserted by the verifier |

## Authoritative chain (003P, paper)

```text
frozen 1m klines (003K dataset)
  → complete 1h bars only
  → VisionLane decision (signal provider, PIT window)
  → RiskManager.check_signal (sizing, stop policy)
  → PaperBroker.execute_signal  ← the execution boundary
       ├─ PaperBrokerRecorder → LifecycleEngine → DurableEventStore
       │                                           └─ FillLedger
       └─ PaperBroker book (positions, closed trades, accounting_snapshot)
  → projection (state machine) → reconciliation (ledger vs book)
  → EXECUTION_TRACE.jsonl / ORDER_LIFECYCLE.csv / RECONCILIATION.json
```

The scenario phase uses the same engine, store, ledger and reconciliation against a
declared offline venue double, so partial fills and timeouts are reachable facts of
the evidence rather than clauses in a document.

## Reachability of a live adapter from 003P

None. `trading_bot.execution` is not imported by any 003P entrypoint, every
envelope is validated against a paper provenance/environment pair, and the verifier
re-checks that no persisted event claims `LIVE`.
