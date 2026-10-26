# G-5 — Runtime route matrix

**Commit medido:** `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`  
**Base previa:** `0bc8a926` (G-4)  
**Alcance:** entrypoints ejecutables del repositorio. Los tests y verificadores
solo aparecen si se declaran `TEST_ONLY`.

Clasificación (la misma de G-4, para que las filas sean comparables):

- `AUTHORIZED`: la autoridad aplicable se evalúa antes del sink; un rechazo
  produce cero llamadas.
- `BYPASS_CONFIRMED`: el sink se alcanza con la autoridad en contra.
- `NOT_REACHABLE`: la ruta no produce una operación ni inicializa un cliente de
  ejecución.
- `UNKNOWN`: no se pudo medir; no cuenta como PASS.

Se añade una etiqueta de alcance, no una quinta clase: `SYNTHETIC_ONLY` significa
que la ruta existe y sale 0, pero solo ejecuta el scanner sintético.

## 1. Rutas medidas

| ID | Entrypoint | Ruta real | Sink | Autoridad | Clasificación | Evidencia |
|---|---|---|---|---|---|---|
| G5-E1 | `trading-bot run --demo --once` | `_cmd_run` → `_run_single_iteration` → `_build_demo_scanner` → `market_data.fake` → `_print_demo_results` | ninguno | n/a | `NOT_REACHABLE` / `SYNTHETIC_ONLY` | `cli_synthetic_stdout.log`; G-4 `after_demo.json` |
| G5-E2 | `trading-bot run --mode paper --auto-trade --once` | mismo que E1; el flag no se usa | ninguno | n/a | `NOT_REACHABLE` / `SYNTHETIC_ONLY` | `cli_synthetic_stdout.log`: `paper_cycle=NOT_RUN`, `broker=NOT_CONSTRUCTED`, aviso de `--auto-trade`; exit 0 |
| G5-E3 | `scripts/start_paper_trading.py --provider fake` con el ledger comprometido | `PaperOrchestrator → PaperSessionRunner → PaperCycleEngine → RiskManager → HotStopGate → PaperBroker` | `PaperBroker.execute_signal` | hot stop + risk + admission + idempotencia | `AUTHORIZED`, resultado `NO_TRADE` | `production_no_trade_stdout.log`: 1 contexto, 1 router, 0 estrategias, `no_strategy_passed_gates`, 0 órdenes, exit 0 |
| G5-E4 | `scripts/start_paper_trading.py` con el fixture de admisión de G-5 | mismo que E3; `ema_crossover@5m` es `PAPER_CANDIDATE` solo en el fixture | mismo | hot stop + risk + admisión controlada + idempotencia | `AUTHORIZED` / `CONTROLLED_PAPER_EVIDENCE` | `scenarios/trade`, `scenarios/restart`; no es admisión de producción |
| G5-E5 | `scripts/audit/g5_paper_e2e.py` | compone E3/E4 con datos deterministas y reloj fijado | mismo | mismas + broker instrumentado | `TEST_ONLY` / `CONTROLLED_PAPER_EVIDENCE` | `evidence.json`; verificador `12/12` |
| G5-E6 | `scripts/autonomous_paper.py` | `AutonomousPaperRuntime.run_cycle → DecisionEngine (rule 0) → _execute_paper → HotStopGate → PaperBroker` | `PaperBroker.execute_signal` | hot stop + rule 0 + risk | `AUTHORIZED` (G-2), no re-ejecutado aquí | `docs/audit/G-2.md` |
| G5-E7 | `scripts/start_paper_lab.py` | supervisor → `scripts/autonomous_paper.py` | mismo que E6 | heredada | `AUTHORIZED` (vía E6), no re-ejecutado | G-2/G-4 |
| G5-E8 | `scripts/ai_bots_run.py`, `ai_vision_lane.py`, `edge*_paper_lane.py`, `exp_003p_baseline.py` | replay offline sobre datos grabados → `PaperBroker` | `PaperBroker` | ninguna de runtime | `RESEARCH_ONLY` | no son entrypoints operativos; G-4 ya los declaró fuera de alcance |
| G5-E9 | `trading-bot run --mode live|shadow_live --auto-trade`, `place-order`, `close-position`, `set-tpsl` | clientes Bitunix | REST del venue | hot stop + `LiveTradingGate` + clasificador | `AUTHORIZED` (RFC), no re-ejecutado | `LIVE_NO_GO`; G-3/P0/RFC |

## 2. Qué cambió respecto de G-4

G-4 dejó `run --demo` como `NOT_REACHABLE` y cerró el stop de la ruta real E17.
G-5 no cambia esa arquitectura: añade la etiqueta explícita en la salida
sintética y demuestra por ejecución que E3/E4 completan el ciclo, incluido el
estado durable y la reconciliación.

La fila que no existe y que no se debe inventar es «`run --mode paper` ejecuta
el motor paper». Conectar esa rama al broker rompería REQ-G4-02 y convertiría
el scan sintético en una ruta de ejecución sin pasar por el contrato de G-4. La
corrección es decir la verdad en stdout y ofrecer un entrypoint real separado.

## 3. Cobertura del recorrido E3/E4

```text
scripts/start_paper_trading.py
  → PaperOrchestrator
      → PaperSessionRunner
          → UniverseScanner (fake o fixture)
          → FetcherBarReader (PIT)
          → PaperCycleEngine
              → CryptoAssetAgentRegistry
              → StrategyRouter
              → AlphaFamily (ema_crossover)
              → SignalAdapter
              → CandidatePortfolio
              → RiskManager.check_signal
              → HotStopGate.order_boundary
                  → PaperBroker.execute_signal
          → PaperBroker.reconcile_session
          → PaperStateStore.save
  → StartupReconcilerV4.reconcile (siguiente proceso)
```

## 4. Lo que no cubre la matriz

- No se ejerció el path live; sigue `LIVE_NO_GO`.
- No se ejerció el runtime autónomo; su autoridad es la de G-2 y no se reabre.
- No se añadió un gate al scan sintético porque no tiene sink que proteger.
- No se declara que `paper_cycle` y `autonomous.decision` sean el mismo motor.
