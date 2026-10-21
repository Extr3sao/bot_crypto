# RUNTIME AUTHORITY MAP — RFC-000

> Derived from the current HEAD `df95974` by reading the import graph, call sites
> and one real PAPER execution (see `reports/rfc000/RUNTIME_EXECUTION_REPORT.md`).
> Authority order: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC >
> EXTERNAL_SOURCE > ASSUMPTION`. A class on disk is NOT authority: reachability is
> demonstrated.

## Entrypoints

| id | path | kind | evidence |
| --- | --- | --- | --- |
| PRIMARY_RUNTIME_ENTRYPOINT | `scripts/autonomous_paper.py` | autonomous PAPER/SHADOW loop | executed: `--provider fake --cycles 2` → exit 0, 6 decisions, 6 traces |
| PRIMARY_PAPER_ENTRYPOINT | `scripts/autonomous_paper.py` | (same) | see above |
| PRIMARY_BACKTEST_ENTRYPOINT | `scripts/multi_family_backtest.py` | research backtest | static + tests |
| PRIMARY_RESEARCH_ENTRYPOINT | `scripts/paper_lab_research.py` | research | static |
| PRIMARY_DASHBOARD_ENTRYPOINT | `scripts/strategy_ecosystem_dashboard.py` | read-only observability | executed: HTTP 200 on `127.0.0.1:8790` |
| CLI | `trading-bot` → `trading_bot.app:main` | config-check / scan / run / place-order | static (live paths env-gated) |
| Legacy PAPER | `scripts/start_paper_trading.py` | earlier PAPER loop | static; superseded by autonomous runtime |
| Supervisor | `scripts/start_paper_lab.py` | campaign supervisor | static |

## Authoritative chain (PAPER)

```
scripts/autonomous_paper.py
  ├─ load_settings (config/realdata) + PairSpec universe
  ├─ AdmissionLedger.load(config/strategy_admission.json)      [fail-closed]
  ├─ StrategyRegistry.from_ledger                              [lifecycle states]
  ├─ build_scanner_factory → UniverseScanner (read-only market data)
  ├─ preflight_run_universe (configured ∩ provider ∩ strategy)
  ├─ FetcherBarReader (PIT history, closed-candle gate)
  ├─ PaperBroker(equity)  ← the ONLY execution boundary
  ├─ RiskManager(risk, equity)
  ├─ IdempotencyGuard + PaperStateStore + StartupReconcilerV4
  └─ AutonomousPaperRuntime(...)
        └─ per asset, per cycle:
             scanner snapshot → FetcherBarReader.get_ohlcv
             → CryptoAssetAgentRegistry.build_context (regime, PIT)
             → StrategyRouter.route(context, regime, strategy_map)
             → AlphaFamilies.generate (6 families)
             → _build_proposal (TradeProposal)
             → SpecialistAgent review (5 shared reviewers)
             → IndependentVerifier.verify (re-reads ledger)
             → DecisionEngine.decide
             → _risk_review  → RiskManager.check_signal   (risk #1)
             → _execute_paper → RiskManager.check_signal  (risk #2)
                              → PaperBroker.execute_signal
             → _reconcile / _process_outcomes
             → DecisionTraceStore.append + heartbeat + daily/RUN report
```

## Component classification

| component | path / symbol | classification | evidence |
| --- | --- | --- | --- |
| AutonomousPaperRuntime | `autonomous/runtime.py::AutonomousPaperRuntime` | RUNTIME_AUTHORITATIVE | executed (6 decisions) |
| UniverseScanner | `scanner/scanner.py` | RUNTIME_AUTHORITATIVE | executed (3 pairs/cycle) |
| FetcherBarReader | `paper/snapshot_history.py` | RUNTIME_AUTHORITATIVE | executed (candle_filter 95/100) |
| CryptoAssetAgentRegistry | `research/asset_intelligence/*` | RUNTIME_AUTHORITATIVE | executed (regime RANGE) |
| StrategyRouter.route | `research/strategy_router.py::StrategyRouter.route` | RUNTIME_AUTHORITATIVE | called at runtime.py:773 |
| AlphaFamilies (6) | `research/families/*` | RUNTIME_AUTHORITATIVE | constructed in entrypoint |
| StrategyRegistry | `autonomous/strategy_state.py::StrategyRegistry` | RUNTIME_AUTHORITATIVE | from_ledger, gates PAPER |
| AdmissionLedger | `autonomous/admission_ledger.py` | RUNTIME_AUTHORITATIVE | loaded at startup |
| SpecialistAgent review (5) | `autonomous/agents.py` | RUNTIME_AUTHORITATIVE | `_agents.review` at runtime.py:952; 5 agents printed |
| IndependentVerifier | `autonomous/verifier.py` | RUNTIME_AUTHORITATIVE | `_verifier.verify` at runtime.py:1005 |
| DecisionEngine | `autonomous/decision.py` | RUNTIME_AUTHORITATIVE | constructed at runtime.py:336 |
| RiskManager | `risk/manager.py` | RUNTIME_AUTHORITATIVE | check_signal ×2 (review + execute) |
| PaperBroker | `paper/broker.py` | RUNTIME_AUTHORITATIVE | only `execute_signal` boundary |
| IdempotencyGuard | `execution/idempotency.py` | RUNTIME_AUTHORITATIVE | wired in entrypoint |
| PaperStateStore | `paper/paper_state_store.py` | RUNTIME_AUTHORITATIVE | `paper_state.saved` emitted |
| StartupReconcilerV4 | `paper/reconciliation_v4.py` | RUNTIME_AUTHORITATIVE | `reconciliation=RECOVERED` |
| DecisionTraceStore | `autonomous/trace.py` | RUNTIME_AUTHORITATIVE | `traces.jsonl` (6 rows) |
| HeartbeatWriter / reporting | `autonomous/observability.py`, `reporting.py` | RUNTIME_AUTHORITATIVE | heartbeat + RUN_REPORT written |
| StrategyRouter.select_eligible_strategies | `research/strategy_router.py` | RUNTIME_REACHABLE | only under `--strategy-routing-mode LIFECYCLE` (default LEGACY) |
| StrategyRoutingMode (LEGACY/SHADOW/LIFECYCLE) | `strategy_lifecycle/runtime_bridge.py` | RUNTIME_REACHABLE | `--strategy-routing-mode` default LEGACY |
| strategy_lifecycle/** (pods, lifecycle, health, champion) | `strategy_lifecycle/*` | RESEARCH_ONLY / TEST_ONLY | no `StrategyPod(` construction in runtime path; imported by scripts/tests |
| StrategyEcosystemObservatory | `observability/ecosystem.py`, `topology.py` | OBSERVABILITY (read-only) | dashboard executed; not trading authority |
| Dashboard server | `scripts/strategy_ecosystem_dashboard.py` | OBSERVABILITY (read-only) | HTTP 200; GET-only |
| PaperCycleEngine (legacy) | `paper/paper_cycle.py` | LEGACY | used by `verify_l5_independent.py`, not by autonomous runtime |
| StartupReconciler V1 / recovery V3 / parity_gate / portfolio_manager / strategy_selector / trade_journal / validation | `paper/*` | ORPHAN | see `docs/runtime_authority_map.md` (2026-09-25) |
| `research/pair/*` (RFC-030) | `research/pair/*` | RESEARCH_ONLY | only self-imports + scripts + tests; `EXP-ARP-023 = BLOCKED_SHORT_DATA` |
| `research/experimental/*` | `research/experimental/*` | EXPERIMENTAL (untracked) | only `scripts/source_candidate_experiment.py` + tests |
| `market_data/htf_pit.py` | `market_data/htf_pit.py` | ORPHAN | zero `src/` importers; only untracked experimental + script |
| `market_data/bitunix*.py`, `app.py` live paths | CLI | RUNTIME_REACHABLE (env-gated) | out of PAPER scope |

## Risk unavoidability

There is **no** path `Strategy → Broker` or `Agent → Broker`. Every broker call site
outside tests is either the autonomous runtime (behind two `RiskManager.check_signal`
calls) or the legacy PAPER engine. `grep` for `.execute_signal` / `PaperBroker(` shows
only `autonomous/runtime.py:1422`, `paper/paper_cycle.py:425`, entrypoint
construction, and the L5 verifier script.

---

# RUNTIME AUTHORITY MAP — sesión durable (WP-PAPER-RESUME-001, 2026-10-20)

> Cierra el hueco que el mapa de salida de `roundtrip-5m` declaró abierto: «no hay
> persistencia del libro en esta ruta; un reinicio empieza plano». Ahora hay un libro en
> disco, y lo que sigue describe la cadena que lo escribe y la que lo recupera. Evidencia:
> `scripts/paper_resume_drill.py` (A/B sobre minutos reales archivados, con procesos
> terminados sin cierre ordenado) y `scripts/verify_paper_resume.py` (verificador
> independiente con controles negativos).

## Cadena de estado (visión, PAPER)

```
VisionLane.run
  ├─ _apply_recovery()            vis/lane.py
  │    └─ reconcile_book(book, contract, prefix, timeline)   vis/durable.py
  │         FRESH | RECOVERED | BLOCKED → RecoveryBlocked
  │         RECOVERED ⇒ PaperBroker.restore + RiskManager.restore_state + pending + marcas
  ├─ por vela: OPEN → gaps → mark → entradas → CLOSE → salidas → marks → decisiones
  │    └─ _commit(barrier_ms=ts)  → LaneBookStore.save (tmp+fsync+replace, .prev)
  │                               → BOOK_EVENTS.jsonl (COMMIT, fsync)
  └─ fin del dataset
       ├─ durable: `_commit(session_end=True)` y las opiniones en vuelo se CONSERVAN
       └─ no durable: RUN_ENDED_WITH_ORDER_PENDING (comportamiento histórico, intacto)

ProspectiveSession.run (durable=True, opt-in)
  ├─ _open_durable_book(): LaneBookStore(out/STATE) + SessionLock + load
  ├─ SESSION_START.durable = {recovered, barrier_ms, decision_from_ms, blocked}
  ├─ _decision_from_ms(): None si hay libro (la barrera acota el pasado), arranque si no
  ├─ _cycle_book(): relee el libro comprometido en cada ciclo
  └─ RecoveryBlocked ⇒ fila CYCLE status=RECOVERY_BLOCKED, 0 fills, sesión detenida
```

## Clasificación (sólo lo ejecutado)

| component | path / symbol | classification | evidence |
| --- | --- | --- | --- |
| `LaneBookStore.save/load` | `vision/durable.py` | RUNTIME_AUTHORITATIVE | 144 commits en la campaña A; `DRILL.json` con `state_digest` |
| `SessionLock` | `vision/durable.py` | RUNTIME_AUTHORITATIVE | relevo de un dueño muerto tras `TerminateProcess` (B) |
| `reconcile_book` | `vision/durable.py` | RUNTIME_AUTHORITATIVE | 9 checks; 8+1 controles negativos detectados |
| `VisionLane._commit` | `vision/lane.py` | RUNTIME_AUTHORITATIVE | `BOOK_EVENTS.jsonl` una fila por vela |
| `VisionLane._apply_recovery` | `vision/lane.py` | RUNTIME_AUTHORITATIVE | reanudación de B tras cada muerte |
| `PaperBroker.restore` | `paper/broker.py` | RUNTIME_AUTHORITATIVE (reutilizado) | posiciones con `position_id` y comisión devengada |
| `RiskManager.restore_state` | `risk/manager.py` | RUNTIME_AUTHORITATIVE (reutilizado) | `risk_equity == marked_equity` tras recuperar |
| `ProspectiveSession` modo durable | `vision/prospective.py` | RUNTIME_AUTHORITATIVE (opt-in) | 2 sesiones sobre el mismo `out_dir` en el test de integración |
| `ProspectiveSession` modo no durable | `vision/prospective.py` | RUNTIME_AUTHORITATIVE (default) | sin cambios: 11 tests previos siguen verdes |

## Autoridad del estado, en una línea

`STATE/BOOK.json` (barrera + libro + riesgo + pendientes) es la verdad económica; el ledger
de cada sesión es su proyección y se verifica contra el libro. Una fila `CLOSE` que no está
en `closed_trades` nunca ocurrió.

---

# RUNTIME AUTHORITY MAP — hueco de datos (WP-PAPER-QUOTE-GAP-002, 2026-10-21)

> Desbloquea el único veredicto terminal que dejó el WP anterior: `UNVERIFIED_GAP`. Un
> hueco de 5 m se puede cruzar si un feed de 1 minuto independiente observó **todos** sus
> minutos; lo que el hueco prueba se aplica, lo que no se prueba bloquea. Evidencia:
> `scripts/quote_gap_lab.py` (6 escenarios + 2 experimentos de muerte real) y
> `scripts/verify_quote_gap.py` (verificador independiente, 10 controles negativos).

## Cadena (sólo cuando el hueco existe)

```
VisionLane._apply_recovery
  ├─ _assess_gap(book, barrier, timeline)            vis/lane.py
  │    └─ gap_recovery.assess_gap(window, positions, feed, pending)
  │         CLEAR | RECONSTRUCT | BLOCKED  (+ evidencia por símbolo y minuto)
  └─ reconcile_book(..., gap=assessment)             vis/durable.py
       ├─ CLEAR       → RECOVERED, libro intacto
       ├─ RECONSTRUCT → RECOVERED + reconstruction{exits, minutes}
       └─ BLOCKED     → RecoveryBlocked(código, causa); el libro no se toca

VisionLane.run
  ├─ RUN  (publica `recovery.gap` y `recovery.reconstruction`)
  ├─ _apply_gap_plan(): por minuto → PaperBroker.check_positions_ohlc(gap_policy=open_on_gap)
  │    ├─ CLOSE con phase=GAP_RECONSTRUCTION, exit_ts_resolution=MINUTE_WINDOW
  │    ├─ risk.reset_daily() si el minuto cae en otro día UTC
  │    └─ _commit(): el cierre es durable cuando está en el libro
  └─ primera vela real (resume_from_ms), procesada con normalidad
```

## Clasificación (sólo lo ejecutado)

| component | path / symbol | classification | evidence |
| --- | --- | --- | --- |
| `assess_gap` | `vision/gap_recovery.py` | RUNTIME_AUTHORITATIVE | 20 tests unitarios + 4 sobre minutos reales del archivo |
| `MinuteBarQuoteFeed.minute_bars_between/series_digest` | `vision/quotes.py` | RUNTIME_AUTHORITATIVE | cobertura y rangos del archivo versionado |
| `reconcile_book(gap=...)` | `vision/durable.py` | RUNTIME_AUTHORITATIVE | `GAP_LAB.json`: CLEAR, RECONSTRUCT, AMBIGUOUS, NOT_COVERED |
| `VisionLane._apply_gap_plan` | `vision/lane.py` | RUNTIME_AUTHORITATIVE | cierre reconstruido con el mismo precio que la corrida continua |
| `LaneBookStore.save` (copia antes del replace) | `vision/durable.py` | RUNTIME_AUTHORITATIVE | 12 muertes reales durante la escritura, 12 libros legibles |
| `SessionLock` (relevo con guardián) | `vision/durable.py` | RUNTIME_AUTHORITATIVE | segundo tomador rechazado; guardián abandonado reemplazable |
| `scripts/quote_feed_source.py` | — | PROVENANCE | el fixture se re-deriva de `data.binance.vision` y coincide byte a byte |

## Límite declarado

El hueco se resuelve **en la barrera**. Una vela que falta *después* de reanudar la salta el
bucle de velas: `check_positions_ohlc` sólo ve velas presentes. Corregirlo cambia la
semántica de `DATA_GAP` que otros tests fijan y queda como WP siguiente, no como hecho.
