# G-4 — FINAL REPORT

**Veredicto:** `G4_VERIFIED_SCOPED`  
**Commit implementado:** `5478b6de417d1bb3cc66920f56685bd3d0368cc0`  
**Export verificado:** `7e300af5c856c9665bf3b52635572e2ba2b69925`  
**BEFORE:** `0a70514058f8deb36489e29a6c02e7050d3217a0`  
**`FALSE_SUCCESS`:** 0  
**`LIVE_NO_GO`:** mantenido  
**`PRODUCTION_READY`:** `false`

## Qué se demostró

`run --demo` **no** era una ruta de ejecución. `_cmd_run` solo compone el scanner
sintético (`market_data.fake`) y imprime snapshots. No importa `paper_cycle`, no
construye `PaperBroker` y no construye ningún cliente de exchange. La matriz, G-2
y G-3 afirmaban lo contrario; `git log -S'PaperCycleEngine' --
src/trading_bot/app.py` está vacío. El defecto era documental y se corrigió en
`runtime_authority_map.md`.

La ruta real era `scripts/start_paper_trading.py` → `PaperCycleEngine` →
`PaperBroker.execute_signal`. Tenía `RiskManager` y admission ledger, pero no
consultaba el `KILL_SWITCH` del operador ni el switch de proceso. Con un marker
presente, el ciclo BEFORE abrió una orden (`broker_execute_calls=1`,
`orders_created=1`). Ese era el bypass.

La corrección inyecta el `HotStopGate` **existente** en el dispatch de entradas
del paper cycle. La comprobación ocurre después de la aprobación de riesgo y
bajo el lock de `order_boundary`; el launcher construye el gate con
`process_kill_switch()` y `<run-dir>/KILL_SWITCH`. La reducción
(`close_position` por señal opuesta) queda fuera del stop para no atrapar el
libro.

## Qué se midió

- Marker presente: **0** llamadas al broker, **0** órdenes, **1** rechazo
  `hot_stop` (AFTER) frente a **1/1/0** (BEFORE).
- Sin marker: **1** orden, igual que antes.
- Switch de proceso sin marker: **0** llamadas.
- Marker tras construir el motor, tras la aprobación de riesgo, marker ilegible
  y `poll` que lanza: **0** llamadas.
- Reducción con stop: `close_position=1`, entrada=0.
- `run --demo` y `run --mode paper --auto-trade`: `exit 0`, cinco contadores de
  sinks a 0, antes y después.

## Pruebas

| Conjunto | Resultado |
|---|---|
| Reproducción BEFORE | 8 failed |
| Focal AFTER | 12 passed |
| Regresión paper/e2e/cert/app/autonomía | 244 passed |
| Regresión amplia | 678 passed |
| Contratos de auditoría | 8 passed |
| Verificador sobre export limpio | 10/10, 192 tests, `FALSE_SUCCESS=0` |

## Límites

No se contactó ningún exchange, no se usaron credenciales y no se envió ninguna
orden. Hedge mode no se ejercitó. `paper_cycle` sigue sin pasar por
`autonomous.decision`: G-4 cierra el stop, no unifica los dos motores. El campo
`boundary` de `HotStopGate.stats()` conserva el nombre del runtime autónomo
porque `hot_stop.py` es byte-idéntico a `a072da90`; la evidencia usa el
`control_path` y el contador del broker. El marker está limitado al `run_dir`.
Los lanes de investigación (`ai_vision_lane`, `edge*_paper_lane`,
`exp_003p_baseline`) no son entrypoints operativos y se declaran
`RESEARCH_ONLY`. La verificación es `PROCEDURALLY_SEPARATED`, no una segunda
persona.

## Bloqueos pendientes

`D-6`, `DEF-P0-03` y la configuración `GATE-009/010` no se abren en este run.
No queda ningún bypass de parada demostrado en el alcance medido.
