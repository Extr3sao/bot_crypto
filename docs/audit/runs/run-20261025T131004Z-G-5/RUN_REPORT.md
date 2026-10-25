# G-5 — RUN REPORT

**Veredicto:** `G5_VERIFIED` (scoped)  
**Commit de implementación:** `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`  
**Antes:** `0bc8a926` · **Rama:** `audit/mt0004-negative-controls`  
**Modo:** PAPER_ONLY · sin credenciales · sin clientes de exchange · sin órdenes reales  
**Estado global:** `LIVE_NO_GO` · `PRODUCTION_READY = false`

## 1. Qué se ejecutó

| # | Comando | Exit | Resultado |
|---|---|---:|---|
| 1 | `python -m trading_bot.app run --mode paper --auto-trade --once` | 0 | scan sintético; `paper_cycle=NOT_RUN`; 0 órdenes |
| 2 | `python scripts/start_paper_trading.py ... --provider fake` con el ledger comprometido | 0 | ciclo real; `contexts=1`, `router=1`, `strategy=0`, `orders=0`, `NO_TRADE:no_strategy_passed_gates` |
| 3 | `python scripts/audit/g5_paper_e2e.py --out <run>` | 0 | 6 escenarios; trade 1 orden; restart `RECOVERED` + cierre TP |
| 4 | `python scripts/audit/verify_g5.py --rev HEAD` | 0 | export limpio, dos replays, `G5_VERIFIED` 12/12 |

El comando (2) es el entrypoint operativo real. El comando (3) usa el mismo
`build_cycle_engine` y el mismo broker/riesgo/stop/estado, con datos sintéticos
y el fixture de admisión controlada; existe para poder medir TRADE, RESTART,
STALE, KILL_SWITCH y EXCEPTION de forma determinista.

## 2. Defectos confirmados y corregidos

### DEF-G5-01 — Las condiciones defensivas ignoraban el reloj de la sesión

`PaperSessionRunner` acepta `now_fn`, pero `_market_conditions` usaba
`datetime.now(UTC)`. En domingo, el replay determinista de miércoles quedaba
bloqueado por `weekend_trading` antes de llegar a riesgo o al stop. El BEFORE
muestra `trade_orders=0` con esa razón, y también `kill_switch` bloqueado por
fin de semana en vez de por el marker.

Corrección: `_market_conditions` usa `self._now_fn()`; el default sigue siendo
el reloj de pared. No se cambió `config/risk.yaml`.

### DEF-G5-02 — La CLI sintética no distinguía su alcance

`run --mode paper --auto-trade --once` salía 0 sin decir que no ejecutaba
`paper_cycle` ni que `--auto-trade` no se aplicaba. Corrección: banner
`paper_cycle=NOT_RUN`, `broker=NOT_CONSTRUCTED`, `state=NOT_WRITTEN` y aviso
explícito del flag. No se conectó la rama al broker: eso violaría G-4 REQ-02.

No se encontró ningún `BYPASS_CONFIRMED` en las rutas medidas. La ruta real ya
tenía el stop de G-4; G-5 demuestra el recorrido completo y corrige la
honestidad de la ruta sintética.

## 3. Evidencia económica

| Escenario | Órdenes | Posiciones | PnL | Estado | Identidades |
|---|---:|---:|---:|---|---|
| TRADE | 1 | 1 abierta | 0 | 908 B; 1 intent | PASS |
| RESTART | 0 | 0 | +49,390016 | 1.387 B; 1 cerrada | PASS |
| NO_TRADE | 0 | 0 | 0 | 476 B | PASS |
| STALE | 0 | 0 | 0 | 476 B | PASS |
| KILL_SWITCH | 0 | 0 | 0 | 476 B | PASS |
| EXCEPTION | 0 | 0 | 0 | 476 B | PASS |

En RESTART, `reconciliation_before` es `RECOVERED` con 1 posición y 1 intent;
la sesión no reabre (`same_side_skips=1`, `orders_created=0`), el precio sube y
`reconcile_session` cierra por `take_profit` con
`pnl=+49,390016` y equity `10.049,390016`. Las cinco identidades de
`accounting_snapshot` son verdaderas.

En KILL_SWITCH el orden observado es el que importa: `risk_accepted=1`,
`hot_stop_blocked=1`, `execute_signal=0`, `orders_created=0`. El stop no se
sustituye por un rechazo anterior a riesgo.

## 4. Pruebas

| Suite | Resultado |
|---|---|
| G-5 (`tests/integration/test_g5_paper_end_to_end.py`) | **8 passed** |
| Foco paper + E2E + app + cert | **200 passed** |
| Regresión amplia (paper, autonomía, riesgo, scanner, app, E2E paper) | **837 passed, 2 failed** |
| Suite unit completa | no colecta: `test_vision_panel.py` importa un módulo ausente, ajeno a G-5 |
| `ruff format --check`, `ruff check` | PASS en ficheros cambiados |
| `mypy` | PASS en fuente y scripts cambiados |

Los 2 fallos de la regresión amplia son
`tests/unit/risk/test_futures_independent_verifier.py::test_verifier_reproduces_a_real_approval`
y `::test_executed_artifacts_verify_when_present`. Se reproducen idénticos en
un worktree detached de `0bc8a926`: son preexistentes y no tocan el paper path.

## 5. Verificación independiente

`verification.json`: `G5_VERIFIED`, **12/12**, `FALSE_SUCCESS=0`.
El verificador exporta `05b361f7` con `git archive`, ejecuta la evidencia dos
veces y comprueba replay determinista (contadores y economía; excluye session
ids y timestamps), `hot_stop.py` sin cambios y todos los criterios de los seis
escenarios.

## 6. Límites

- Datos sintéticos y admisión controlada: se demuestra alcanzabilidad y
  contabilidad del recorrido, no edge ni rentabilidad.
- El ledger de producción no admite estrategias; el comando real termina en
  `NO_TRADE`.
- El restart es lógico (instancias nuevas, mismo proceso y disco), no un crash
  del sistema operativo.
- No se contactó ningún exchange; no se usaron credenciales.
- `paper_cycle` y `autonomous.decision` siguen siendo dos motores.
- La verificación es `PROCEDURALLY_SEPARATED`, no una segunda persona.

## 7. Artefactos

`RUNTIME_ROUTE_MATRIX.md`, `PAPER_END_TO_END.md`, `BEFORE_AFTER.md`,
`RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md`, `evidence.json`,
`verification.json`, `production_no_trade_stdout.log`,
`cli_synthetic_stdout.log`, `before_g5_evidence.json`,
`before_g5_evidence_stdout.log`, `before_cli_synthetic_stdout.log`,
`evidence_stdout.log`, `verification_stdout.log`.
