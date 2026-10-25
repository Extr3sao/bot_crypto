# G-5 — BEFORE / AFTER

**Antes:** `0bc8a926` (cierre de G-4)  
**Después:** `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`  
**Método:** el mismo runner de evidencia se copió al export de `0bc8a926`
(`before_g5_evidence.json`) para que la comparación mida el mismo recorrido, no
dos guiones distintos. El ledger de admisión controlada también se copió; no se
tocó ningún fichero de política del árbol base.

## 1. Resumen

| Propiedad | BEFORE `0bc8a926` | AFTER `05b361f7` | Evidencia |
|---|---|---|---|
| Salida de `run --mode paper --auto-trade --once` | exit 0; sin aviso de que el ciclo paper no se ejecuta | exit 0; `paper_cycle=NOT_RUN`, `broker=NOT_CONSTRUCTED`, aviso de `--auto-trade` | `before_cli_synthetic_stdout.log` vs `cli_synthetic_stdout.log` |
| Reloj de las condiciones defensivas | reloj de pared; el replay fijado en miércoles fue bloqueado por ser domingo | mismo `now_fn` de la sesión; el replay de miércoles llega a riesgo y broker | `before_g5_evidence.json` vs `evidence.json` |
| Trade controlado | 0 órdenes; rechazo `weekend_trading: weekend (Sunday)` | 1 orden, 1 posición, 1 `cloid`, estado durable de 908 B | `scenarios/trade` |
| Restart | `RECOVERED` sin posición (no había trade que restaurar) | `RECOVERED` con 1 posición y 1 intent; 0 reaperturas; cierre TP +49,390016 | `scenarios/restart` |
| Kill switch | 0 órdenes, pero por `weekend_trading`; el stop no se ejercitó | `risk_accepted=1`, `hot_stop_blocked=1`, broker 0 llamadas, razón `kill_switch_active` | `scenarios/kill_switch` |
| NO_TRADE plano | 0 órdenes, `no_alpha_in_direction:ANY` | idéntico | `scenarios/no_trade` |
| Stale | 0 órdenes, `NO_TRADE:stale_context` | idéntico | `scenarios/stale` |
| Excepción de proveedor | 0 órdenes, `scanner_errors=1` | idéntico | `scenarios/provider_exception` |
| Verificación limpia | no existía | `G5_VERIFIED` 12/12, replay determinista | `verification.json` |

## 2. El defecto que se corrigió

`PaperSessionRunner` recibía `now_fn` y lo usaba para `started_at`, `ended_at` y
el resto de la sesión, pero `_market_conditions` construía `MarketConditions.at`
con `datetime.now(UTC)`. En un domingo, el replay determinista fijado en
miércoles quedaba bloqueado por `weekend_trading` antes de que la señal llegara
a riesgo o al stop. La consecuencia no era solo un test rojo: el mismo comando
podía atribuir a la política de fin de semana un rechazo que el operador creía
del stop, y no había forma de ejercitar el dispatch paper en un día no hábil.

Después, `_market_conditions` usa `self._now_fn()` (con el reloj de pared como
default). No se cambió la política: el fin de semana sigue bloqueando en
producción; lo que cambia es que el reloj inyectado gobierna todas las
decisiones de la sesión.

## 3. El defecto de la ruta CLI

Antes, `run --mode paper --auto-trade --once` imprimía `DEMO mode ... synthetic
data` y salía 0, pero no decía que `paper_cycle` no se ejecutaba. Un consumidor
del exit code podía leerlo como una ejecución paper. Después imprime:

```text
[run] AVISO: --auto-trade no se aplica al scan sintetico
      (paper_cycle=NOT_RUN, broker=NOT_CONSTRUCTED).
Synthetic scan only: paper_cycle=NOT_RUN, broker=NOT_CONSTRUCTED, state=NOT_WRITTEN
```

No se conectó esa rama al broker: G-4 REQ-G4-02 prohíbe esa conexión y la
conversión habría creado una ruta de ejecución sin el contrato de G-4. La ruta
real sigue siendo `scripts/start_paper_trading.py`.

## 4. Códigos de salida y llamadas observadas

| Comando | Exit | Llamadas observadas |
|---|---:|---|
| `run --mode paper --auto-trade --once` (after) | 0 | `PaperBroker.execute_signal=0`, `paper_cycle=NOT_RUN` |
| `start_paper_trading.py` con ledger comprometido | 0 | `contexts_built=1`, `strategy_invocations=0`, `orders_created=0` |
| `g5_paper_e2e.py` TRADE | 0 | `execute_signal=1`, `orders_created=1` |
| `g5_paper_e2e.py` RESTART | 0 | `execute_signal=0`, `orders_created=0`, 1 cierre TP |
| `g5_paper_e2e.py` KILL_SWITCH | 0 | `execute_signal=0`, `close_position=0`, `hot_stop_blocked=1` |
| `g5_paper_e2e.py` EXCEPTION | 0 | `execute_signal=0`, `scanner_errors=1` |

## 5. Regresiones

- G-5: 8/8 tests.
- Paper + autonomía + riesgo + scanner + app + E2E paper: **837 passed, 2
  failed**. Los 2 fallos (`tests/unit/risk/test_futures_independent_verifier.py`)
  se reproducen igual en el árbol base `0bc8a926`; no son de G-5.
- Suite unit completa: no se pudo colectar por
  `tests/unit/observability/test_vision_panel.py` (módulo
  `trading_bot.observability.vision_panel` ausente, ajeno a los ficheros
  cambiados). No se usa como evidencia.
- `ruff format/check` y `mypy` sobre los ficheros cambiados: PASS.
- `hot_stop.py`: SHA-256 `76cfca23…`, sin cambios.

## 6. Conclusión

El AFTER no solo añade tests: ejecuta una operación paper completa, la persiste,
la recupera tras un reinicio lógico y la reconcilia. El BEFORE no podía hacerlo
con un reloj determinista porque las condiciones defensivas ignoraban el reloj
de la sesión; además, la CLI no distinguía el scan sintético del ciclo paper.
Ambos defectos están corregidos y verificados sobre un export limpio.
