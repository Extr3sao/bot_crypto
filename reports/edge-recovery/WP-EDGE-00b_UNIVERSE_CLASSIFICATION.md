# WP-EDGE-00b — Clasificación del activo excluido (DEF-WP00-01)

| | |
|---|---|
| **WP** | WP-EDGE-00b — corrección del defecto `DEF-WP00-01` detectado en WP-EDGE-00 |
| **run_id** | `wp-edge-00b-universe-fix` |
| **commit del run** | `6a3a09047bdce13977e23b512dbe075dabaa75ee` |
| **entrypoint real** | `scripts/autonomous_paper.py` (proveedor `ccxt:binance`, datos de mercado reales) |
| **verificador** | `scripts/wp_edge_00b_verify.py` → **PASS 13/13 checks · 7/7 controles negativos · FALSE_SUCCESS = 0** |
| **estado** | `IMPLEMENTED` + `TESTED` + `RUNTIME_OBSERVED`. **No** es `PROFITABLE`, ni `PAPER_VERIFIED`, ni autoriza nada |

## 1. El defecto

El runtime **saltaba** la descarga de velas para un snapshot inactivo y luego intentaba construir el contexto del activo sin velas. El fallo del contexto se registraba como `CONTEXT_ERROR` → `NO_TRADE_DATA`:

```text
# ANTES (run real wp-edge-00-smoke-real, commit 1d2192b)
SOL | NO_TRADE | class=CONTEXT_ERROR | kind=NO_TRADE_DATA
      reason=context_error:AssetContextError: no bars at or before ts 1791795395133
      market_context: active=False, rejection_reason=volume_below_threshold

# DESPUÉS (run real wp-edge-00b-universe-fix, commit 6a3a090)
SOL | NO_TRADE | class=UNIVERSE_FILTERED | kind=NO_TRADE_UNIVERSE
      reason=scanner_rejected:volume_below_threshold
      market_context: active=False, rejection_reason=volume_below_threshold
```

Una **decisión de universo** (el scanner decidió no ofrecer el activo: liquidez insuficiente) se estaba reportando como **incapacidad de leer el mercado**. Es el mismo error que el módulo ya prohíbe en la dirección contraria: convertir una avería en una decisión de trading. Aquí convertía una decisión de selección en una avería.

Descartado a propósito: renombrar la exclusión como `NO_TRADE_STRATEGIC`. La clase estratégica significa "la ventaja no sobrevive al coste" (la estrategia fue el motivo); una exclusión de universo ocurre **antes** de que ninguna estrategia vea el activo, y mezclarlas borraría la diferencia entre "descarté el activo" y "descarté la señal".

## 2. El cambio

| Archivo | Cambio |
|---|---|
| [contracts.py](src/trading_bot/autonomous/contracts.py) | `NoTradeKind.NO_TRADE_UNIVERSE` (quinta clase honesta). Guarda de traza: un `NO_TRADE_UNIVERSE`/`NO_TRADE_DATA` no puede llevar `proposal` |
| [decision.py](src/trading_bot/autonomous/decision.py) | Clasificación `UNIVERSE_FILTERED`; `_UNIVERSE_CLASSIFICATIONS`; `UNIVERSE_REJECTION_REASONS` y `_DATA_REJECTION_REASONS`; `classification_for_scanner_rejection()`; `unclassified_scanner_rejections()`; `no_trade_kind_for("UNIVERSE_FILTERED") → NO_TRADE_UNIVERSE` |
| [runtime.py](src/trading_bot/autonomous/runtime.py) | `_evaluate_asset`: si el snapshot no está activo, se nombra la exclusión **antes** de construir el contexto (`classification`, `reason=scanner_rejected:<motivo>`, `no_trade_kind`, `failure_kind=None`) |
| [test_universe_exclusion_classification.py](tests/unit/autonomous/test_universe_exclusion_classification.py) | 15 tests nuevos: taxonomía + runtime + controles negativos |
| [test_contracts.py](tests/unit/autonomous/test_contracts.py) | 2 tests nuevos: traza de exclusión sin propuesta; `no_trade_kind` desconocido rechazado |
| [test_risk_observability.py](tests/unit/autonomous/test_risk_observability.py) | Matriz de clasificación ampliada con `UNIVERSE_FILTERED` |
| [wp_edge_00b_verify.py](scripts/wp_edge_00b_verify.py) | Verificador independiente (proceso e implementación separados; no importa el runtime) |

**Cero cambios de comportamiento de trading**: 0 órdenes antes y después, `production_actions = 0`, la rama no ejecuta ninguna estrategia (test que lo fija: `build_context` no se invoca para el activo excluido). Lo único que cambia es **cómo se nombra** la negativa.

## 3. Taxonomía: selección vs datos

El catálogo `RejectionReason` del scanner es un `Literal` cerrado. La taxonomía lo reparte explícitamente y falla si aparece un motivo sin clasificar:

| Motivo del scanner | Clase | Por qué |
|---|---|---|
| `not_whitelisted`, `volume_below_threshold`, `volume_below_threshold_for_live_min_10M`, `spread_above_threshold`, `atr_out_of_range`, `price_below_threshold` | `UNIVERSE_FILTERED` → `NO_TRADE_UNIVERSE` | Filtro determinista de **selección**: el activo no entra en el universo operable |
| `insufficient_history` | `NO_MARKET_DATA` → `NO_TRADE_DATA` | **Datos**: el scanner no pudo construir la historia que necesita; el runtime genuinamente no pudo decidir |
| fuera del catálogo (otro adaptador) | `UNIVERSE_FILTERED` (por defecto) | El hecho conocido es "el scanner lo excluyó"; el motivo crudo queda visible en `reason` y `market_context` |

`unclassified_scanner_rejections()` devuelve el conjunto de motivos del catálogo que la taxonomía no clasifica, y un test exige que sea vacío: añadir un motivo al scanner obliga a decidir aquí si es selección o datos.

## 4. Pruebas ejecutadas

```text
python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q
→ 402 passed · 0 failed · 0 skipped        (mismo conjunto que WP-00: 385 → +17 tests nuevos)

python -m pytest tests/unit/autonomous/test_universe_exclusion_classification.py -q
→ 15 passed

ruff check  (src/trading_bot/autonomous, tests/unit/autonomous, scripts/wp_edge_00b_verify.py) → OK
mypy        (contracts.py, decision.py, runtime.py, scripts/wp_edge_00b_verify.py)  → Success (strict)
```

Controles negativos que los tests fijan (y en qué dirección):

- `volume_below_threshold` → `NO_TRADE_UNIVERSE` (el arreglo).
- `insufficient_history` → sigue siendo `NO_TRADE_DATA` (no se blanquea un problema real de datos).
- Activo **activo** sin historia → sigue siendo `CONTEXT_ERROR` / `NO_TRADE_DATA` (el arreglo no se traga fallos de contexto).
- Avería del proveedor en activo activo → sigue siendo `PROVIDER_FAILURE`, no una decisión.
- Activo excluido → `order_created=False`, `failure_kind=None`, `proposal=None`, sin propuesta ni orden.

## 5. Ejecución real observada

```text
.venv/Scripts/python.exe scripts/autonomous_paper.py --assets BTC,ETH,SOL --timeframe 5m \
  --provider ccxt --cycles 2 --interval 15 --run-id wp-edge-00b-universe-fix \
  --run-root reports/edge-recovery/runs/WP-EDGE-00b-universe-fix \
  --state-path reports/edge-recovery/runs/WP-EDGE-00b-universe-fix/paper_state.json \
  --ledger config/strategy_admission.json --horizon-minutes 5.0 --size-usd 1000.0 --no-shadow
```

| Métrica | Valor |
|---|---|
| Entorno / datos | `ccxt:binance`, velas 5m cerradas, **datos reales** (read-only) |
| Ciclos / evaluaciones | 2 / 6 |
| Decisiones | 6 · **TRADES 0** · `no_trade_kind` = `{NO_TRADE_STRATEGIC: 4, NO_TRADE_UNIVERSE: 2}` |
| `NO_TRADE_DATA` | **0** (antes: 2, el defecto) |
| Órdenes / acciones de producción | 0 / 0 |
| Cadena de trazas | `{"ok": true, "records": 6, "broken_at": null}` (re-derivada por el verificador) |
| PnL bruto / fees / slippage / neto | 0.0 / 0.0 / 0.0 / 0.0 USDT — `ZERO_BY_NO_TRADE`: no se abrió posición, **no es beneficio** |

Evidencia: [RUN_REPORT.md](reports/edge-recovery/runs/WP-EDGE-00b-universe-fix/wp-edge-00b-universe-fix/RUN_REPORT.md), [RUN_REPORT.json](reports/edge-recovery/runs/WP-EDGE-00b-universe-fix/wp-edge-00b-universe-fix/RUN_REPORT.json), [traces.jsonl](reports/edge-recovery/runs/WP-EDGE-00b-universe-fix/wp-edge-00b-universe-fix/traces.jsonl), [stdout.log](reports/edge-recovery/runs/WP-EDGE-00b-universe-fix/stdout.log).

## 6. Verificación independiente

`scripts/wp_edge_00b_verify.py` (proceso separado, implementación propia, sin importar `trading_bot`) re-deriva el resultado de tres fuentes que el constructor no puede falsificar a la vez: los artefactos persistidos, el **texto fuente** de la capa de decisión (rama y mapeo deben existir en los ficheros) y la taxonomía re-implementada. Resultado: [WP-EDGE-00b_INDEPENDENT_VERIFICATION.json](reports/edge-recovery/WP-EDGE-00b_INDEPENDENT_VERIFICATION.json) → **PASS 13/13**, 7/7 mutaciones detectadas, `FALSE_SUCCESS = 0`. Cada control falla exactamente el chequeo que le corresponde (comprobado uno a uno: neutralizar la rama falla `UNIVERSE_BRANCH_PRESENT`; mover `UNIVERSE_FILTERED` a las clases de datos falla `TAXONOMY_NOT_CONFLATED`; inyectar una orden falla `UNIVERSE_TRACES_CLEAN` + `NO_ORDERS_NO_TRADES`).

## 7. Consecuencia sobre la evidencia congelada de WP-00

No se reescribió ningún artefacto de WP-00: su certificación (`INDEPENDENT_VERIFICATION.json`, run `wp-edge-00-smoke-real`) pertenece al commit `6a3a090` y sigue intacta en ese commit. Pero su chequeo `RUN_COMMIT_IS_ANCESTOR` exige que **nada de código de runtime haya cambiado desde el smoke**, y este WP cambia código de runtime: al commitear, ese chequeo pasa a `FAIL` **por diseño**, y significa exactamente lo que dice — la evidencia de WP-00 ya no describe `HEAD`. El smoke equivalente para el nuevo estado es el run de este WP (`wp-edge-00b-universe-fix`). No se debilitó el chequeo para que siguiera verde.

## 8. Límites (lo que este WP NO demuestra)

- **No es rentabilidad**: 0 operaciones, PnL 0 por no haber posición. Nada aquí dice si alguna estrategia gana dinero.
- **No es PAPER productivo**: son 2 ciclos de ~20 s de datos reales, no una sesión continuada.
- **No hay validación OOS** ni promoción: `PAPER_PROMOTION` y `LIVE_TRADING` quedan donde estaban (cerrado/deshabilitado).
- La rama se alcanza con `active=False`; si un adaptador futuro marcara `active=False` con datos buenos, el activo dejaría de evaluarse (igual que `run_cycle`, que ya le negaba las velas) — coherencia con el scanner, no una decisión nueva de este WP.
- Los chequeos de fuente son lecturas estáticas de tres ficheros: prueban que la rama y el mapeo existen, no que todos los caminos de llamada la alcancen.
- El verificador es un proceso y una implementación separados, **no** una persona ni un agente distinto.
