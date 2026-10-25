# RUNTIME AUTHORITY MAP — WP-EDGE-00

> Fecha: 2026-10-12 · Alcance: `WP-EDGE-00` (RFC-TAP-EDGE-001 / ROADMAP-TAP-EDGE-001)
> Método: inspección **directa del checkout** (no de la documentación) más **ejecución real**
> de los entrypoints en el HEAD actual. Cada afirmación de "alcanzable" está enlazada a una
> ejecución o a un import verificable; lo que no se pudo comprobar se declara `UNVERIFIED`.

```text
REPO_ROOT   C:/Users/GVLLFR0035/Downloads/bot freebuff
BRANCH      main (única rama local de trabajo)
LOCAL_HEAD  1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22
ORIGIN_MAIN 5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d   (2026-09-22)
MERGE_BASE  5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d   (== origin/main tip)
DIVERGENCIA local estrictamente por delante: 259 commits, 0 detrás
MODE        runtime.mode = "paper" · live_trading_enabled = false
TEST_TARGET == RUNTIME_TARGET: los entrypoints ejecutados son los del propio checkout
```

## 1. Leyenda de clasificación

| Clase | Significado |
|---|---|
| `RUNTIME_AUTHORITATIVE` | Está en el camino ejecutado por los entrypoints PAPER reales; sus decisiones tienen efecto sobre el ciclo. |
| `RUNTIME_REACHABLE` | Se importa desde el runtime (tipos, adaptadores, guardas) aunque no sea el núcleo de decisión. |
| `RUNTIME_GATE` | Test/contrato que certifica el camino de decisión del runtime y forma parte de la disciplina de release. |
| `TEST_ONLY` | Solo lo ejecutan tests o verificadores; no participa en el ciclo. |
| `RESEARCH_ONLY` | Simulación/experimento offline; escribe artefactos de research, nunca órdenes ni estado PAPER. |
| `EXPERIMENTAL` | Investigación en curso sin promoción (sin gate superado). |
| `LEGACY` | Camino antiguo conservado por compatibilidad; no lo invoca el runtime PAPER. |
| `ORPHAN` | Paquete/fichero sin consumidores verificables. |
| `STALE_VERIFIER` | Verificador que falla por haberse escrito contra un contrato anterior, no por defecto del runtime (ver §9.2). |

## 2. Entrypoints (verificados ejecutando)

| Entrypoint | Rol | Clase | Evidencia en esta ejecución |
|---|---|---|---|
| `scripts/start_paper_trading.py` | "The single entrypoint for the paper trading loop (FASE 6)". Compone `UniverseScanner → PaperSessionRunner → PaperCycleEngine → RiskManager → PaperBroker`. Imprime al final el JSON de estado con los contadores de ciclo. | `RUNTIME_AUTHORITATIVE` | Ejecutado en HEAD (fixture ledger, `--provider fake --max-cycles 1`): `contexts_built=3`, `router_invocations=3`, `strategy_invocations=3`, `orders_created=0`, `mode=paper`, `equity=10000.0`. Ver `reports/edge-recovery/runs/WP-EDGE-00-smoke-fixture/stdout_1cyc.log` |
| `scripts/autonomous_paper.py` | Runtime autónomo PAPER/SHADOW (decision layer + agentes + verificador independiente + PaperBroker + traces/outcomes/heartbeat/daily). Es el hijo `paper` de `start_paper_lab.py`. | `RUNTIME_AUTHORITATIVE` | Ejecutado en HEAD con datos reales (`--provider ccxt`, BTC,ETH,SOL, 2 ciclos): exit 0, 6 decisiones, 0 trades, `trace_chain OK`, `replay 6/6`, `production_actions=0`. Ver `reports/edge-recovery/runs/WP-EDGE-00-smoke-real/` |
| `scripts/start_paper_lab.py` | Supervisor del laboratorio PAPER: PAPER + collector + retention + strategy lab, con preflight de disco. | `RUNTIME_REACHABLE` | No ejecutado en WP-00 (lanzador; su hijo PAPER es el verificado arriba) |
| `scripts/wp9_runtime_rehearsal.py` | Ensayo de continuidad que **conduce** `autonomous_paper.py` y re-deriva comprobaciones de los artefactos persistidos. | `TEST_ONLY` | Productor de `reports/autonomous-paper/wp9-runtime-legs/` (run del 2026-10-11, commit 5348fcd) |
| `scripts/verify_l5_independent.py` | Verificador independiente L5 (VER-PO-L5-001) del ciclo CP-PO-002. | `STALE_VERIFIER` | Re-ejecutado en HEAD: 8/11 PASS, 3 FAIL (L5-08/09/10) por fixture con `status="CONFIRMED"` ya no admitido por el gate DEF-AUTO-4 (ver §9.2) |

## 3. Cadena de decisión PAPER (código → evidencia)

```text
MarketData (read-only, público)
  src/trading_bot/market_data/{exchange_connector,multi_exchange,ohlcv_fetcher,candle_filter}.py
→ UniverseScanner (volumen, spread, ranking)            src/trading_bot/scanner/
→ PIT context (AssetContext + fingerprint + regime)     src/trading_bot/research/asset_intelligence/registry.py
→ StrategyRouter (freshness, data quality, admisión, régimen)  src/trading_bot/research/strategy_router.py
→ Familias (6 familias @5m: breakout, ema_crossover, mean_reversion, momentum, trend, volatility)
                                                        src/trading_bot/research/families/ + autonomous/agents.py
→ Propuesta (TradeProposal) + coste re-derivado (COST_MODEL_V3)   src/trading_bot/autonomous/contracts.py, costs.py
→ Agentes revisores → verificador independiente          src/trading_bot/autonomous/{agents,verifier,decision}.py
→ Decisión (TRADE/NO_TRADE con clasificación y causa)    src/trading_bot/autonomous/decision.py
→ RiskManager (sizing, límites, kill switch)             src/trading_bot/risk/manager.py
→ PaperBroker (fills simulados, fees/slippage del modelo) src/trading_bot/paper/broker.py
→ DecisionTrace + Outcome + Performance                  src/trading_bot/autonomous/{trace,outcomes,experience}.py
→ RUN_REPORT + PAPER_DAILY_REPORT + heartbeat            src/trading_bot/autonomous/{runtime,reporting,observability}.py
```

Cadena alternativa (hermana, para el harness/engine del ciclo):

```text
PaperSessionRunner → PaperCycleEngine (context→router→bar-gate→familia→candidatos→riesgo→broker)
  src/trading_bot/paper/{harness,paper_cycle,portfolio_manager,reconciliation}.py
```

Ambas cadenas comparten `StrategyRouter`, `RiskManager` y `PaperBroker`; ninguna puede alcanzar LIVE
(no existe adaptador de órdenes reales en ellas).

## 4. Inventario por componente

### 4.1 `src/trading_bot/`

| Componente | Rol | Clase | Nota / evidencia |
|---|---|---|---|
| `autonomous/` (19 módulos) | Runtime autónomo: `runtime.py`, `decision.py`, `agents.py`, `verifier.py`, `trace.py`, `outcomes.py`, `experience.py`, `admission_ledger.py`, `strategy_state.py`, `paper_loop.py`, `cadence.py`, `supervisor.py`, `observability.py`, `reporting.py`, `costs.py`, `contracts.py`, `pit.py`, `pit_ledger.py`, `universe_preflight.py` | `RUNTIME_AUTHORITATIVE` | Ejecutado en el smoke real; traces con cadena de hash intacta |
| `paper/` (26 módulos) | Motor de ciclo, broker PAPER, reconciliación, kill switch, estado duradero, reporting | `RUNTIME_AUTHORITATIVE` | `PaperCycleEngine.run_cycle_sync` ejecutado vía `start_paper_trading.py` |
| `market_data/` (13 módulos) | Conector CCXT/Bitunix, fetcher PIT, filtro de velas, HTF PIT, fake provider | `RUNTIME_AUTHORITATIVE` | Smoke real `environment=ccxt:binance`, 100-120 velas por símbolo |
| `research/strategy_router.py` + `research/router_gates.py` + `research/types.py` | Router con gates (frescura, calidad, admisión, régimen) y contrato de señales | `RUNTIME_AUTHORITATIVE` | Importado por `autonomous/runtime.py` y `paper/paper_cycle.py` |
| `risk/manager.py` | Riesgo determinista (sizing, límites, kill switch, veto) | `RUNTIME_AUTHORITATIVE` | `risk_APPROVED=4` en el smoke real (advisory, sin orden por coste) |
| `scanner/` | Universo: volumen 24h, spread, ranking, filtros por modo | `RUNTIME_AUTHORITATIVE` | SOL rechazado por `volume_below_threshold` en el smoke real |
| `strategy_lifecycle/` (`runtime_bridge`, `portfolio`, estados) | Ciclo de vida de estrategias (DEF-AUTO-4) y puente al runtime | `RUNTIME_REACHABLE` | Importado por `autonomous/runtime.py` |
| `execution/` (`idempotency`, `cost_model`, `live_gate`) | Idempotencia de intents, cost model de ejecución, guarda LIVE | `RUNTIME_REACHABLE` | `IdempotencyGuard` en el ciclo; `live_gate` no es invocado por los entrypoints PAPER |
| `strategies/` (`types`, `protocols`, `pipeline`, `ema_crossover`) | Contrato de `Signal`/`Side` + familias legacy | `RUNTIME_REACHABLE` | `paper/broker.py`, `paper/signal_adapter.py`, `risk/manager.py` importan `strategies.types` |
| `backtesting/` | `BacktestResult`, `FoldReport`, `build_fold_report` | `RUNTIME_REACHABLE` | Importado por `paper/harness.py` (métricas de sesión) |
| `observability/` (`journal`), `domain/` (enums kill switch) | Journal de trades; enums de dominio | `RUNTIME_REACHABLE` | Importados por `paper/reconciliation.py`, `paper/kill_switch_v2.py` |
| `indicators/builtin` | EMA/ATR/RSI usados por las familias | `RUNTIME_REACHABLE` | Importado por `start_paper_trading.py` al componer el engine |
| `app.py` | CLI temprana (`config-check`, `scan --demo`, `run --mode live`, `place-order --confirm-live`) | `LEGACY` | Requiere `mode == live` y confirmación explícita; **no** forma parte del camino PAPER |
| `portfolio/__init__.py` | Docstring de responsabilidades, sin implementación | `ORPHAN` | El portfolio real vive en `paper/portfolio_manager.py` y `strategy_lifecycle/portfolio.py` |
| `charting/`, `feedback/`, `trade_journal/`, `market_structure/`, `utils/` | Utilidades de apoyo | `TEST_ONLY` / `LEGACY` | Sin import desde `paper/` ni `autonomous/` (grep de imports vacío) |
| `config/` | `Settings`, `TradingMode`, universo | `RUNTIME_AUTHORITATIVE` | `config/realdata/*.yaml` leídos en ambos smokes |
| `research/` (resto: `alpha*`, `swing/`, `experimental/`, `discovery/`, `diversified/`, `microstructure/`, `families/`, `governance/`, …) | Investigación y campañas económicas offline | `RESEARCH_ONLY` | Escriben `data/**`; no órdenes, no estado PAPER. `families/` sí es alcanzable **a través del router** |

### 4.2 `scripts/` (291 ficheros) — agrupado

| Grupo | Ejemplos | Clase |
|---|---|---|
| Runtime PAPER | `start_paper_trading.py`, `autonomous_paper.py`, `start_paper_lab.py` | `RUNTIME_AUTHORITATIVE` / `RUNTIME_REACHABLE` |
| Ensayos y verificadores de runtime | `wp9_runtime_rehearsal.py`, `wp9_ci_audit.py`, `clean_checkout_rehearsal.py`, `cost_barrier*.py` | `TEST_ONLY` |
| Verificador L5 histórico | `verify_l5_independent.py` | `STALE_VERIFIER` |
| Campañas económicas | `alpha00*_run/verify`, `alpha_expansion_v1`, `alpha_recovery_*`, `wp10_*`, `cap00*`, `sprint00*`–`sprint033*`, `rfc0*` | `RESEARCH_ONLY` / `EXPERIMENTAL` |
| Observabilidad/scheduler ST-6 | `st6_*` | `RESEARCH_ONLY` (scheduler de observación, `get-only`) |
| Lane SWING (no publicada) | `swing_preregister.py`, `swing_run.py`, `swing_verify.py` | `RESEARCH_ONLY`, sin commit (ver `git_divergence_report.md`) |
| Herramientas | `system_daily_report.py`, `strategy_lifecycle_report.py`, `strategy_ecosystem_dashboard.py` | `TEST_ONLY` |

### 4.3 Tests

| Ruta | Rol | Clase |
|---|---|---|
| `tests/unit/cert/test_paper_smoke_decision_path.py` | **Puerta de contrato del smoke**: `exit 0 + contexts/router/strategy == 0` NO es PASS (`SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED`) | `RUNTIME_GATE` |
| `tests/integration/test_paper_e2e_00{1,2,3}.py` | End-to-end PAPER sobre componentes canónicos | `RUNTIME_GATE` |
| `tests/unit/{autonomous,paper}/` | Contratos del runtime y del ciclo | `TEST_ONLY` |
| `tests/integration/` (resto), `tests/bdd/`, `tests/regression/` | Replay/qualification históricos | `TEST_ONLY` |
| `tests/unit/research/` | Contratos de investigación (acciones, costes, swings) | `TEST_ONLY` |

Resultado focalizado en este WP: `pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q` → **385 passed, 0 failed** (28.59 s).

### 4.4 Datos y artefactos

| Ruta | Contenido | Tamaño | Uso |
|---|---|---|---|
| `data/raw/` | Corpus histórico multi-símbolo (incluye `alpha001/…`) | 137 MB | research/backtests |
| `data/recovery/` | WP-7/8/9/10: auditorías, verificación independiente, matrices | 2.1 MB | evidencia de campañas |
| `data/st6/` | Scheduler ST-6: ventanas, ledger, raw (gzip), snapshots | 18 MB | observación forward |
| `data/swing/` | Lane SWING (11 artefactos, sin commit) | 4.3 MB | research, ver `git_divergence_report.md` |
| `reports/autonomous-paper/` | Runs PAPER (incl. `wp9-runtime-legs`) | 29 MB | evidencia PAPER |
| `reports/strategy-baseline/` | Datos base de la evaluación de estrategias | 41 MB | research |
| `config/strategy_admission.json` | Ledger de admisión (24 estrategias) | 28 KB | **entrada del router** (`sha256 6c4dd0be…`) |

Estado del ledger: `NO_GROSS_EDGE=17`, `COST_KILLED=7`, `PAPER_CANDIDATE=0`, `admitted_for_paper=0`.
Consecuencia verificada en runtime: `paper-executable on 5m: NONE` → el comportamiento correcto es `NO_TRADE`.

## 5. Qué resultados previos son reproducibles

| Resultado | Artefactos | Reproducible hoy | Nota |
|---|---|---|---|
| Smoke PAPER con decisión observable | este WP: `reports/edge-recovery/runs/…` | **Sí** (ejecutado) | Datos reales + fixture |
| WP-9 runtime legs (3 legs, cadence, stop/resume) | `reports/autonomous-paper/wp9-runtime-legs/` (commit 5348fcd) | Parcial | El ensayo completo está diseñado para 24 h; los legs cortos sí son repetibles |
| WP-10 coste de ejecución / planicie de admisión | `data/recovery/wp10/*` (HEAD 49ca773) | Sí (offline) | Resultado de tipo RESEARCH (no backtest) |
| RFC-049 Discovery 2 (cerrada, rechazada) | `data/recovery/RFC049_POST_CLOSURE_REPORT.md`, `data/rfc049/*` | Sí (offline) | OOS sellado cancelado; no reabrir |
| Certificación cost-barrier | `.ci/*` (sin commit) + `reports/` | Parcial | Los `.ci/*` no están versionados; ver divergencia |
| `verify_l5_independent.py` 11/11 | — | **No en HEAD** | 8/11 por fixture obsoleta (ver §9.2) |

## 6. Gate de decisión viva (control negativo del propio WP)

| Comprobación | Resultado |
|---|---|
| `exit 0` con ciclo muerto no pasa | `tests/unit/cert/test_paper_smoke_decision_path.py::test_exit_zero_without_contexts_is_not_strategy_path_verified` PASS |
| `exit 0` real sin órdenes SÍ es evidencia válida | Smoke real: 6 decisiones, 4 `NO_TRADE_STRATEGIC` con causa de coste, 2 `NO_TRADE_DATA`; 0 órdenes; 0 acciones de producción |
| Estrategia rechazada no puede operar | `test_a_rejected_strategy_never_reaches_the_family` PASS (con `strategy_invocations == 0`) |
| LIVE inalcanzable desde los entrypoints | `production_actions = 0`; `mode = paper`; sin claves ni órdenes reales |

## 7. Hallazgos

1. **`SOL` inactivo genera `NO_TRADE_DATA` con causa de contexto** — el scanner lo rechaza por
   `volume_below_threshold` (24h ≈ 4.9 M USDT) pero el ciclo intenta construir contexto y falla con
   `AssetContextError: no bars at or before ts …`. Es fail-closed (no hay orden) pero **la
   clasificación es engañosa**: es una decisión de universo, no una caída de datos.
   Evidencia: `reports/edge-recovery/runs/WP-EDGE-00-smoke-real/wp-edge-00-smoke-real/PAPER_DAILY_REPORT.md`.
2. **`verify_l5_independent.py` obsoleto** (`STALE_VERIFIER`), ver §9.2. No es un defecto del runtime;
   es un certificado que dejó de corresponder al contrato vigente (DEF-AUTO-4).
3. **`provider_verified=false`** en el preflight del smoke real: la comprobación de mercados del
   proveedor (best-effort) no confirmó el universo. No bloquea (el preflight declaró `ok=true`
   con `provider_supported=null`), pero queda registrado como no verificado.
4. **259 commits locales sin publicar** y ~123 entradas de árbol sucio (detalle en
   `git_divergence_report.md`). Ninguna se ha borrado, mezclado ni descartado en este WP.

## 9.2 Root cause del `STALE_VERIFIER` (evidencia dura)

- El script construye su propio `strategy_map` con `"status": "CONFIRMED"`.
- El router actual (`src/trading_bot/research/strategy_router.py`, gate DEF-AUTO-4) solo acepta
  estados de `PAPER_EXECUTABLE_STATUS_NAMES`; `CONFIRMED` ya no está en ese conjunto.
- Resultado: `router.no_trade_reason="no_strategy_passed_gates"` → 0 órdenes →
  3 FAILs (L5-08/09/10). La parte PIT de L5-09 (`trim keeps 100/130`, futuro excluido) sí se cumple;
  lo que falla es la aserción de orden.
- Evidencia: `reports/edge-recovery/diagnostics/verify_l5_independent_HEAD.stdout.txt`
  y `src/trading_bot/research/strategy_router.py` (gate `require_confirmed`).
- Recomendación (WP-EDGE-01, no ejecutada aquí): re-basar el verificador sobre el ledger de admisión
  (como hace `tests/unit/cert/test_paper_smoke_decision_path.py`) o retirarlo como certificado activo.
