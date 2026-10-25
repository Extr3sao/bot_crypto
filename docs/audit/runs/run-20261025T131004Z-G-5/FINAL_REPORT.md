# G-5 — FINAL REPORT

**Estado:** CLOSED (scoped)  
**Implementación:** `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`  
**Base previa:** `0bc8a926` (G-4)  
**Veredicto del verificador:** `G5_VERIFIED` 12/12 · `FALSE_SUCCESS = 0`  
**Global:** `LIVE_NO_GO` · `PRODUCTION_READY = false`

## 1. Resultado

El runtime paper del repositorio ejecuta un ciclo completo y medido:

```text
datos deterministas → scanner → PIT → contexto → router → ema_crossover
→ adapter → portfolio → RiskManager → HotStopGate → PaperBroker
→ contabilidad → estado durable → StartupReconcilerV4
```

La operación de evidencia abre 1 orden paper, deja 1 posición y 1 intent
durables; un reinicio lógico restaura ambos, no reabre y cierra por
`take_profit` con PnL neto **+49,390016 USDT** y equity **10.049,390016**.

No se encontró un `BYPASS_CONFIRMED` en las rutas medidas. La ruta sintética
`run --mode paper` no es una ruta de ejecución y ahora lo dice; la ruta real
sigue siendo `scripts/start_paper_trading.py`.

## 2. Hallazgos

1. **Motor canónico identificado por ejecución:** `PaperCycleEngine`, compuesto
   por `scripts/start_paper_trading.py::build_cycle_engine` y conducido por
   `PaperOrchestrator → PaperSessionRunner`. El comando real ejecuta el ciclo
   con el ledger comprometido y termina en `NO_TRADE` porque no hay estrategia
   admitida; eso es correcto y observable.
2. **DEF-G5-01:** `_market_conditions` usaba el reloj de pared en vez del
   `now_fn` de la sesión. En domingo bloqueaba el replay determinista por
   `weekend_trading` antes de riesgo/stop. Corregido sin cambiar la política.
3. **DEF-G5-02:** la CLI sintética salía 0 sin declarar que no ejecutaba el
   ciclo paper y que `--auto-trade` no se aplicaba. Corregido con banner y
   aviso explícitos; no se conectó al broker (G-4 REQ-02).

## 3. Evidencia por escenario

| Escenario | Órdenes | Hecho observado | Evidencia |
|---|---:|---|---|
| TRADE | 1 | `risk_accepted=1`, 1 fill, 1 posición, 908 B, 1 intent | `evidence.json` |
| RESTART | 0 | `RECOVERED` 1 posición/1 intent; `same_side_skips=1`; TP close +49,390016; 1.387 B | `evidence.json` |
| NO_TRADE | 0 | `no_alpha_in_direction:ANY` | `evidence.json` |
| STALE | 0 | `NO_TRADE:stale_context` | `evidence.json` |
| KILL_SWITCH | 0 | `risk_accepted=1`, `hot_stop_blocked=1`, broker 0 llamadas | `evidence.json` |
| EXCEPTION | 0 | `scanner_errors=1`, 0 snapshots | `evidence.json` |

Las cinco identidades de `PaperBroker.accounting_snapshot` son verdaderas en
todos los escenarios.

## 4. Criterios de aceptación

| ID | Estado | Evidencia |
|---|---|---|
| ACC-G5-01 | PASS | `cli_synthetic_stdout.log`: banner y aviso; exit 0 |
| ACC-G5-02 | PASS | `production_no_trade_stdout.log`: ciclo real, `no_strategy_passed_gates`, 0 órdenes |
| ACC-G5-03 | PASS | `trade`: 1 orden, 1 fill, 1 posición, `execute_signal=1` |
| ACC-G5-04 | PASS | `state_after`: 1 posición, 1 intent; identidades verdaderas |
| ACC-G5-05 | PASS | `restart`: `RECOVERED`, 1/1, 0 reaperturas, TP +49,390016 |
| ACC-G5-06 | PASS | `no_trade`: 0 señales/órdenes, razón observable |
| ACC-G5-07 | PASS | `stale`: 0 órdenes, `stale_context` |
| ACC-G5-08 | PASS | `kill_switch`: `risk_accepted=1`, `hot_stop_blocked=1`, broker 0 |
| ACC-G5-09 | PASS | `provider_exception`: `scanner_errors=1`, 0 órdenes |
| ACC-G5-10 | PASS | `verification.json`: 12/12, dos replays deterministas, `FALSE_SUCCESS=0` |
| ACC-G5-11 | PASS | `hot_stop.py` SHA-256 `76cfca23…` |
| ACC-G5-12 | PASS | `LIVE_NO_GO`; `PRODUCTION_READY=false` |

## 5. Pruebas

- G-5: **8/8**.
- Foco paper/E2E/app/cert: **200/200**.
- Regresión amplia: **837 passed, 2 failed**; los dos fallos son preexistentes en
  `tests/unit/risk/test_futures_independent_verifier.py` y se reproducen igual
  en `0bc8a926`.
- La suite unit completa no colecta por un módulo ausente en
  `tests/unit/observability/test_vision_panel.py`, ajeno a G-5; no se presenta
  como PASS.
- `ruff` y `mypy` sobre los ficheros cambiados: PASS.

## 6. Límites

- Datos sintéticos y admisión `CONTROLLED_TEST_FIXTURE`: se demuestra el
  recorrido y la contabilidad, no edge ni rentabilidad.
- El ledger de producción no admite ninguna estrategia; el comando real
  termina en `NO_TRADE`.
- El restart es lógico (nuevas instancias, mismo proceso y disco), no un crash
  del sistema operativo.
- No se contactó ningún exchange, no se usaron credenciales y no se envió
  ninguna orden real.
- `paper_cycle` y `autonomous.decision` siguen siendo dos motores; G-5 no los
  unifica.
- La verificación es `PROCEDURALLY_SEPARATED`, no una segunda persona.

## 7. Artefactos

`RUNTIME_ROUTE_MATRIX.md`, `PAPER_END_TO_END.md`, `BEFORE_AFTER.md`,
`RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md`, `evidence.json`,
`verification.json`, `production_no_trade_stdout.log`,
`cli_synthetic_stdout.log`, `before_g5_evidence.json`,
`before_g5_evidence_stdout.log`, `before_cli_synthetic_stdout.log`,
`evidence_stdout.log`, `verification_stdout.log`.
