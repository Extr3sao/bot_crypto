# G-4 — Runtime route matrix

**Commit medido:** `5478b6de417d1bb3cc66920f56685bd3d0368cc0`  
**Antes de la corrección:** `0a70514058f8deb36489e29a6c02e7050d3217a0`  
**Alcance:** entrypoints ejecutables del repositorio; se excluyen tests y
verificadores salvo que se declaren explícitamente como `TEST_ONLY`.

Clasificación:

- `AUTHORIZED`: la autoridad aplicable se evalúa antes del sink y un rechazo
  produce cero llamadas.
- `BYPASS_CONFIRMED`: el sink se alcanza con la autoridad en contra.
- `NOT_REACHABLE`: la ruta no produce una operación ni inicializa un cliente de
  ejecución (puede inicializar datos de mercado de solo lectura).
- `UNKNOWN`: no se pudo medir; no cuenta como PASS.

## 1. Rutas medidas

| ID | Entrypoint | Ruta | Sink | Autoridad | Clasificación | Evidencia |
|---|---|---|---|---|---|---|
| E1 | `trading-bot run --demo --once` | `_cmd_run` → `_run_single_iteration` → `_build_demo_scanner` → `market_data.fake` → `_print_demo_results` | ninguno | n/a — no hay operación | `NOT_REACHABLE` | `before_demo.json`, `after_demo.json`: `paper_cycle=0`, `paper_broker=0`, `futures_client=0`, `spot_client=0`, `live_source=0`, `exit=0` |
| E2 | `trading-bot run --mode paper --auto-trade --once` | mismo que E1; el flag no se usa en la rama paper | ninguno | n/a | `NOT_REACHABLE` | `before_demo_autotrade.json`, `after_demo_autotrade.json`: los cinco contadores a 0, `exit=0` |
| E3 | `trading-bot run --mode live` **sin** `--auto-trade` | `_cmd_run` → `_run_single_live_iteration` → `resolve_scanner_source` → `connector.load_markets` → scan | ningún sink de orden; cliente de datos read-only | modo live + configuración; no se construye una orden | `NOT_REACHABLE` (orden) | Código: `_run_single_live_iteration` no contiene `create_order`/`place_order`; no re-ejecutado en G-4 |
| E4 | `trading-bot run --mode live --auto-trade` | `_cmd_run` preflight → `_maybe_execute_live_*` → `_live_order_boundary` → `HotStopGate.order_boundary` → Bitunix/connector | `place_order` / `create_order` | hot stop + `--confirm-live` + 10 checks de `LiveTradingGate` + clasificador de orden | `AUTHORIZED` (heredado) | RFC-TAP-EXEC-SEC-002: 0 llamadas en cada rechazo, `exit 2`; no re-ejecutado aquí |
| E5 | `trading-bot run --mode shadow_live --auto-trade` | mismo que E4 | Bitunix/connector | mismo que E4 | `AUTHORIZED` (heredado) | RFC: `shadow_live` exige `--confirm-live` porque las funciones de orden miran `runtime.mode` |
| E6 | `trading-bot place-order` futures OPEN / spot buy | `_cmd_place_order` → pre-client → `_live_order_boundary` → sink | `place_order` / `place_spot_order` | hot stop + confirmación + gate + clasificador | `AUTHORIZED` (heredado) | RFC: 10/10 checks rechazados → 0 llamadas, `exit 2` |
| E7 | `trading-bot place-order` futures CLOSE `--reduce-only` con posición one-way | `_cmd_place_order` → `classify_order` → reduction payload guard → sink | mismo | `PROVEN_REDUCTION` revalidada en el payload | `AUTHORIZED` (exento de gate de apertura) | RFC: `reduceOnly=true`, `tradeSide=CLOSE`, `0 < qty <= position.qty` |
| E8 | `trading-bot place-order` spot `sell` / futures CLOSE sin `reduceOnly` | clasificador → `UNKNOWN` → gate de apertura | mismo | hot stop + gate | `AUTHORIZED` (no exento) | RFC: `UNKNOWN` nunca se reinterpreta como permiso |
| E9 | `trading-bot close-position` | `_cmd_close_position` → `classify_order` → flash-close por id | `flash_close_position` | posición observable; payload solo `positionId` | `AUTHORIZED` (reducción probada) | RFC; G-3: 1 llamada con GATE-004 rechazado |
| E10 | `trading-bot set-tpsl` | `_cmd_set_tpsl` → `UNKNOWN` → gate de apertura | `place_position_tpsl` | hot stop + gate | `AUTHORIZED` (no exento) | RFC: TP/SL no se trata como reducción |
| E11 | `trading-bot positions` | `_cmd_positions` → cliente de lectura | ninguno de órdenes | lectura | `NOT_REACHABLE` (orden) | `_cmd_positions` no llama a ningún método de envío |
| E12 | `trading-bot scan --demo` | `_cmd_scan` → `_run_single_iteration` → fake | ninguno | n/a | `NOT_REACHABLE` | mismo camino E1 |
| E13 | `trading-bot scan --no-demo` | `_cmd_scan` → `exit 2` antes de construir el conector | ninguno | rechazo explícito | `NOT_REACHABLE` | `app.py:1628-1641`; test de contrato CLI |
| E14 | `trading-bot config-check` / `status` | validación / stub | ninguno | n/a | `NOT_REACHABLE` | `status` en `NOT_IMPLEMENTED_SUBCOMMANDS` y `exit 2` |
| E15 | `trading-bot kill-switch --engage` | escribe `<run-dir>/KILL_SWITCH` | ninguno | operador | `NOT_REACHABLE` (control, no ejecución) | `write_control_file`; G-1/G-2 |
| E16 | `scripts/autonomous_paper.py` | `AutonomousPaperRuntime.run_cycle` → `DecisionEngine.decide` (rule 0) → `_execute_paper` → `HotStopGate.order_boundary` → `PaperBroker.execute_signal` | `PaperBroker.execute_signal` | hot stop + rule 0 + risk + admission + idempotency | `AUTHORIZED` (G-2) | `docs/audit/G-2.md`; `runtime.py` tiene un único dispatch |
| E17 | `scripts/start_paper_trading.py` | `PaperOrchestrator` → `PaperSessionRunner` → `PaperCycleEngine.run_cycle_sync` → `RiskManager.check_signal` → `_hot_stop_verdict` → `HotStopGate.order_boundary` → `PaperBroker.execute_signal` | `PaperBroker.execute_signal` | hot stop (marker/proceso) + risk + admission ledger + idempotency | `AUTHORIZED` **después de G-4** | `after_paper_marker.json`: 0 llamadas; `after_paper_clean.json`: 1; `test_g4_paper_hot_stop.py` 12/12 |
| E18 | `scripts/start_paper_lab.py` | supervisor → `scripts/autonomous_paper.py --continuous` | mismo que E16 | heredada del hijo | `AUTHORIZED` (vía E16) | `start_paper_lab.py` no compone broker propio |
| E19 | `scripts/ai_bots_run.py` | runner offline sobre barras grabadas → `PaperBroker` | `PaperBroker` | ninguna de runtime | `RESEARCH_ONLY` | No es entrypoint de producción; `mock`/`live` etiquetados como no-evidencia |
| E20 | `scripts/ai_vision_lane.py` | `VisionLane` → `PaperBroker.execute_signal` | `PaperBroker` | risk del lane | `RESEARCH_ONLY` | Replay offline de fixtures; no es runtime de paper |
| E21 | `scripts/edge15_paper_lane.py`, `edge16_paper_lane.py`, `exp_003p_baseline.py` | lanes de investigación → `PaperBroker` | `PaperBroker` | n/a | `RESEARCH_ONLY` | Datos grabados; no entrypoint de producción |
| E22 | `BitunixFuturesClient.create_order` | delegación legacy | REST interno | — | `LEGACY` (sin caller en `src/`) | G-3 E10 |
| E23 | `BitunixSpotClient.create_order` / `cancel_order` | lanza `UnsupportedConnectorOperationError` | — | — | `DEAD` (rechaza antes de enviar) | G-3 E11 |
| E24 | `scripts/audit/*`, `scripts/verify_*` | probes y verificadores | brokers instrumentados | n/a | `TEST_ONLY` | No se ejecutan en producción |

## 2. La fila que estaba mal documentada

Las versiones anteriores de `runtime_authority_map.md` (y `G-2.md`, `G-3.md`)
decían que `run --demo` alcanzaba `paper/paper_cycle.py`. No hay ningún commit
que lo demuestre:

```bash
git log -S'PaperCycleEngine' --oneline -- src/trading_bot/app.py   # (vacío)
grep -n "paper_cycle\|PaperBroker\|execute_signal" src/trading_bot/app.py  # (sin coincidencias)
```

`app.py` sí importa `BitunixFuturesClient` y `BitunixSpotClient`, pero solo los
construye en la rama `run --mode live|shadow_live --auto-trade` y en
`place-order`/`close-position`/`set-tpsl`. El probe de G-4 reemplaza esas clases
por centinelas que fallan si se construyen: E1/E2 salen 0 con cero
construcciones.

Por tanto, G-4 no "añade un gate a `run --demo`": retira una fila falsa de la
matriz y cierra la ruta real, E17.

## 3. Cobertura de la ruta E17

```text
scripts/start_paper_trading.py
  → run_dir = args.run_dir or data/storage/paper; mkdir
  → HotStopGate(kill_switch=process_kill_switch(), run_dir=run_dir)
  → PaperCycleEngine(..., hot_stop=gate)
      → por candidato, después de RiskManager.check_signal:
          _hot_stop_verdict()
            ├─ marker comprometido → rechazo, 0 execute_signal
            └─ proceso activo     → rechazo, 0 execute_signal
          HotStopGate.order_boundary()   [lock held]
            ├─ marker apareció después del precheck → rechazo
            └─ permitido → PaperBroker.execute_signal
      → la señal opuesta y close_position quedan FUERA del stop
```

Un marker escrito antes del ciclo, después de construir el motor o entre la
aprobación de riesgo y el dispatch produce 0 llamadas. Un marker ilegible y un
`poll` que lanza también producen 0. El control positivo sin marker produce
exactamente 1 orden.

## 4. Lo que no es una ruta de producción

`scripts/ai_bots_run.py`, `scripts/ai_vision_lane.py`, los `edge*_paper_lane.py`
y `exp_003p_baseline.py` usan `PaperBroker` sobre datos grabados. Se declaran
`RESEARCH_ONLY` porque no son entrypoints del runtime de paper y no tienen un
proceso operativo ni un `run_dir`. Añadirles un gate inventaría una autoridad que
nadie ejerce. Si alguno se promociona a entrypoint operativo, la matriz debe
cambiar y G-4 deja de cubrirlo.

## 5. Límites

- No se contactó ningún exchange; los sinks live son los de los audits G-3/P0/RFC.
- No se ejerció un venue en hedge mode.
- No se demuestra que `paper_cycle` y `autonomous.decision` sean el mismo motor:
  siguen siendo dos implementaciones. G-4 cierra el stop, no la duplicación.
- El campo `boundary` de `HotStopGate.stats()` sigue diciendo
  `autonomous.runtime._execute_paper -> broker.execute_signal`, porque
  `hot_stop.py` es byte-idéntico a `a072da90`. La evidencia de G-4 usa el
  `control_path` y el contador del broker, no ese texto.
