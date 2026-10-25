# G-4 — RUN REPORT

**Run:** `run-20261025T115139Z-G-4`  
**Fecha:** 2026-10-25  
**Rama:** `audit/mt0004-negative-controls`  
**BEFORE:** `0a70514058f8deb36489e29a6c02e7050d3217a0`  
**AFTER:** `5478b6de417d1bb3cc66920f56685bd3d0368cc0`  
**Evidencia verificada sobre:** `7e300af5c856c9665bf3b52635572e2ba2b69925` (mismo código de producto; solo cambia el probe)  
**Veredicto:** `G4_VERIFIED_SCOPED`  
**`FALSE_SUCCESS`:** `0` sobre 10 comprobaciones del verificador y 12 tests focales.

## 1. Objetivo

Determinar si `run --demo` u otros entrypoints alcanzables pueden generar
operaciones, inicializar clientes o modificar estado de ejecución sin pasar por
las autoridades del runtime; corregir solo los bypasses demostrados.

## 2. Gobierno

- `LIVE_NO_GO` se mantiene.
- `PRODUCTION_READY = false` se mantiene.
- No se usó ninguna credencial, no se llamó a ningún exchange y no se envió
  ninguna orden real.
- No se modificó `hot_stop.py` (sha256 `76cfca23…` idéntico a `a072da90`).
- No se relajó `RiskManager`, `LiveTradingGate`, `DecisionEngine` ni las
  políticas de `config/`.
- El único cambio de comportamiento en paper es el rechazo cuando el operador
  ya pidió la parada.

## 3. Método

1. Inventario de entrypoints desde `src/trading_bot/app.py` y `scripts/`.
2. Trazado de `run --demo` y de `run --mode paper --auto-trade` con sinks
   instrumentados.
3. Trazado de `scripts/start_paper_trading.py` hasta
   `PaperBroker.execute_signal`.
4. Reproducción del bypass con un marker real escrito por el mismo primitivo que
   usa el CLI (`<run-dir>/KILL_SWITCH`).
5. Corrección mínima: inyectar el `HotStopGate` existente en el dispatch de
   entradas del paper cycle.
6. Pruebas rojas antes / verdes después; regresión amplia; verificación separada
   sobre export limpio.

## 4. Hallazgos

### H-1 — `run --demo` no era una ruta de ejecución (defecto documental)

`_cmd_run` usa `_build_demo_scanner`, que compone `market_data.fake` y
`UniverseScanner`. No importa `paper_cycle`, no construye `PaperBroker` y no
construye clientes de exchange. `git log -S'PaperCycleEngine' --
src/trading_bot/app.py` no devuelve ningún commit. La afirmación contraria
estaba repetida en `runtime_authority_map.md`, `G-2.md` y `G-3.md`.

Medición: `before_demo.json` y `before_demo_autotrade.json` → `exit 0`, los
cinco contadores (`paper_cycle`, `paper_broker`, `futures_client`,
`spot_client`, `live_source`) a 0.

### H-2 — Bypass confirmado en el paper launcher (defecto real)

`scripts/start_paper_trading.py` → `PaperCycleEngine` llamaba
`PaperBroker.execute_signal` después de `RiskManager` pero sin consultar el
marker del operador ni el switch de proceso. Medición BEFORE:
`broker_execute_calls=1`, `orders_created=1`, `hot_stop_blocked=0` con
`KILL_SWITCH` presente.

Corrección: `PaperCycleEngine` recibe un `HotStopGate` opcional; el launcher
siempre lo construye con `process_kill_switch()` y `<run-dir>/KILL_SWITCH`.
La entrada se rechaza después de la aprobación de riesgo y bajo el lock de
`order_boundary`. La reducción (`close_position` por señal opuesta) queda fuera
del stop.

Medición AFTER: `broker_execute_calls=0`, `orders_created=0`,
`hot_stop_blocked=1`, `gate_engaged=true`.

### H-3 — El control positivo sigue vivo

Sin marker, el mismo ciclo crea exactamente 1 orden
(`after_paper_clean.json`). Un stop no se implementó rechazando todo el paper.

### H-4 — Adversariales

| Caso | Resultado |
|---|---|
| Marker antes del motor | 0 llamadas |
| Marker después de construir el motor | 0 llamadas |
| Marker escrito entre `check_signal` y dispatch | 0 llamadas |
| Marker ilegible (directorio) | 0 llamadas, gate engaged |
| `poll` lanza `OSError` | 0 llamadas, fail closed |
| Switch de proceso activo sin marker | 0 llamadas |
| Reducción con stop activo | `close_position=1`, entrada=0 |

## 5. Pruebas ejecutadas

```text
BEFORE  tests/unit/paper/test_g4_paper_hot_stop.py        8 failed  (reproducción)
AFTER   tests/unit/paper/test_g4_paper_hot_stop.py        12 passed
AFTER   paper + e2e 001/002/003 + cert + app + autonomía  244 passed
AFTER   unit/autonomous + unit/paper + unit/cert + app
        + live gate + order authorization + live hot stop 678 passed
AFTER   tests/unit/test_audit_contracts_tracked.py        8 passed
AFTER   verify_g4.py sobre export limpio                 10/10, FALSE_SUCCESS=0
```

Entorno: Windows, CPython 3.11.15, `.venv` del worktree, `PYTHONPATH=src`.
Los archivos de salida están en este mismo directorio (`*.txt`).

El verificador corrió sobre un `git archive` del commit `5478b6de`, comprobó
`TEST_TARGET == RUNTIME_TARGET` (import desde el export, no del worktree) y
ejecutó **192 tests** dentro del export. No se reutilizó el resultado del
worktree.

## 6. Criterios

| ID | Estado | Evidencia |
|---|---|---|
| ACC-G4-01 | PASS | `after_demo.json` |
| ACC-G4-02 | PASS | `after_demo_autotrade.json` |
| ACC-G4-03 | PASS | `after_paper_marker.json`; `test_a_marker_blocks...` |
| ACC-G4-04 | PASS | `after_paper_clean.json` |
| ACC-G4-05 | PASS | `test_a_marker_written_after_risk_approval...` |
| ACC-G4-06 | PASS | `test_a_marker_written_while_the_engine_is_alive...` |
| ACC-G4-07 | PASS | tests de marker ilegible y `poll` exception |
| ACC-G4-08 | PASS | `after_paper_process.json` |
| ACC-G4-09 | PASS | `test_a_stop_does_not_trap_a_reduction` |
| ACC-G4-10 | PASS | `test_the_paper_launcher_wires_the_gate...`; AST launcher |
| ACC-G4-11 | PASS | sha256 de `hot_stop.py` = `a072da90` |
| ACC-G4-12 | PASS | 244 + 678 + 192 tests |
| ACC-G4-13 | PASS | `verification.json` 10/10 |
| ACC-G4-14 | PASS | G-4 §1 y este informe |

## 7. Bloqueos y límites

- **No verificado contra un exchange:** no hay llamada real; los sinks live
  siguen siendo los audits G-3/P0/RFC, no una nueva ejecución.
- **Hedge mode:** no ejercitado; el RFC lo rechaza como `UNKNOWN`.
- **Dos motores:** `paper_cycle` no importa `autonomous.decision`. G-4 cierra el
  stop, no unifica los motores. Es un cambio arquitectónico fuera de alcance.
- **Etiqueta del gate:** `HotStopGate.stats().boundary` conserva el texto del
  runtime autónomo porque `hot_stop.py` no se toca. La evidencia usa el
  `control_path` y las llamadas al broker.
- **Scopes:** el marker vive en `<run-dir>`; otro `--run-dir` es otro scope y
  arranca operativo. No hay latch global.
- **Lanes de investigación:** `ai_vision_lane`, `edge*_paper_lane` y
  `exp_003p_baseline` no son entrypoints operativos; se declaran `RESEARCH_ONLY`,
  no `AUTHORIZED`.
- **Independencia:** la verificación es `PROCEDURALLY_SEPARATED` (script
  distinto, mismo autor), no una segunda persona.
- **D-6, DEF-P0-03, GATE-009/010:** no se abren ni se cierran aquí.
