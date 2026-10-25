# G-4 — BEFORE / AFTER

**BEFORE:** `0a70514058f8deb36489e29a6c02e7050d3217a0`  
**AFTER:** `5478b6de417d1bb3cc66920f56685bd3d0368cc0`  
**Método:** `scripts/audit/g4_route_probe.py`, ejecutado con `PYTHONPATH`
apuntando a cada árbol. Los sinks son contadores; no se contacta ningún exchange.

## 1. Medición directa

| Escenario | BEFORE | AFTER | Cambio |
|---|---|---|---|
| `run --demo --once` | `exit 0`; `paper_cycle=0`, `paper_broker=0`, `futures_client=0`, `spot_client=0`, `live_source=0` | idéntico | ninguno — ya era `NOT_REACHABLE` |
| `run --mode paper --auto-trade --once` | `exit 0`; los cinco contadores a 0 | idéntico | ninguno — el flag no se usa en paper |
| Paper, sin marker (control positivo) | 1 `execute_signal`, 1 orden, 0 rechazos hot-stop | 1 `execute_signal`, 1 orden, 0 rechazos hot-stop | comportamiento legítimo intacto |
| Paper, marker `KILL_SWITCH` presente | **1 `execute_signal`, 1 orden**, 0 rechazos hot-stop | **0 `execute_signal`, 0 órdenes**, 1 rechazo `hot_stop` | **bypass cerrado** |
| Paper, switch de proceso activo sin marker | **1 `execute_signal`, 1 orden** | **0 `execute_signal`, 0 órdenes**, 1 rechazo `hot_stop:process` | **bypass cerrado** |
| Paper, marker tras construir el motor | no existía la comprobación; 1 orden | 0 llamadas; 1 rechazo | test de reproducción |
| Paper, marker entre risk y dispatch | no existía la comprobación; 1 orden | 0 llamadas; 1 rechazo | test adversarial |
| Paper, marker ilegible / `poll` lanza | no existía la comprobación | 0 llamadas; fail-closed | test adversarial |
| Paper, reducción con stop activo | `close_position` seguía disponible | `close_position=1`, `execute_signal` de entrada=0 | sin regresión |
| `start_paper_trading` construye gate | no | `engine.hot_stop.control_path = <run-dir>/KILL_SWITCH` | wiring comprobado |

Los JSON crudos están en `before_*.json` y `after_*.json`. El `before_paper_marker`
se generó con el probe actual sin `--attach-gate` sobre el árbol BEFORE; el
`after_paper_marker` se generó con `--attach-gate` sobre el árbol AFTER.

## 2. Salidas y códigos

```text
BEFORE  paper marker:  broker_execute_calls=1  orders_created=1  hot_stop_blocked=0
AFTER   paper marker:  broker_execute_calls=0  orders_created=0  hot_stop_blocked=1
BEFORE  process stop:  broker_execute_calls=1  orders_created=1  hot_stop_blocked=0
AFTER   process stop:  broker_execute_calls=0  orders_created=0  hot_stop_blocked=1
BEFORE  demo:          exit=0  calls={paper_cycle:0, paper_broker:0, futures_client:0, spot_client:0, live_source:0}
AFTER   demo:          exit=0  calls={paper_cycle:0, paper_broker:0, futures_client:0, spot_client:0, live_source:0}
```

## 3. Pruebas

| Fase | Comando | Resultado |
|---|---|---|
| Reproducción roja (BEFORE) | `pytest tests/unit/paper/test_g4_paper_hot_stop.py` sobre `0a705140` | 8 failed (el motor no aceptaba `hot_stop`; el launcher no aceptaba `run_dir`) — `before_pytest.txt` |
| AFTER focal | mismo comando sobre `5478b6de` | **12 passed** — `after_pytest.txt` |
| AFTER regresión | paper + e2e 001/002/003 + cert + app + autonomía | **244 passed** — `regression.txt` |
| AFTER regresión amplia | `tests/unit/autonomous`, `tests/unit/paper`, `tests/unit/cert`, app, live gate, order authorization, live hot stop | **678 passed** — `regression_broad.txt` |
| Contratos de auditoría | `tests/unit/test_audit_contracts_tracked.py` | **8 passed** — `audit_contracts.txt` |
| Verificador separado | `verify_g4.py --rev 7e300af5` sobre export limpio | **10/10**, `G4_VERIFIED_SCOPED`, `FALSE_SUCCESS=0` — `verification.json` |

## 4. Cambio mínimo

- `src/trading_bot/paper/paper_cycle.py`: +75 líneas. Un parámetro opcional
  `hot_stop`, un contador `hot_stop_blocked`, un precheck y el dispatch dentro de
  `order_boundary`. La reducción (`close_position`) queda fuera.
- `scripts/start_paper_trading.py`: +38 líneas. `--run-dir` (default
  `data/storage/paper`, override `PAPER_RUN_DIR`), construcción del
  `HotStopGate` y paso al motor.
- No se modificó `hot_stop.py`, `decision.py`, `runtime.py`, `RiskManager`, la
  política de riesgo ni ningún sink live.

## 5. Defectos confirmados

1. **Doc-vs-código:** la matriz afirmaba una ruta `run --demo → paper_cycle` que
   nunca existió (`git log -S'PaperCycleEngine' -- src/trading_bot/app.py` vacío).
   Corregido en `runtime_authority_map.md` y en este run.
2. **Bypass real:** `start_paper_trading.py` alcanzaba
   `PaperBroker.execute_signal` sin consultar el marker ni el switch de proceso.
   Corregido y reproducido con tests.

## 6. Falsos positivos evitados

- No se declaró "cerrado" el `run --demo`: se demostró que no llega al sink.
- No se bloqueó la reducción con el stop: se probó `close_position`.
- No se contó un rechazo genérico como PASS: el control positivo sin marker
  sigue creando 1 orden.
- No se afirmó que `paper_cycle` y `autonomous.decision` son un solo motor.
