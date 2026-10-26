# VENUE_EXECUTION_FINAL_REPORT — VENUE-AND-EXECUTION-RESEARCH-V1 + AGGTRADES-MICROSTRUCTURE-V1

Fecha: 2026-09-27. JSON: `docs/VENUE_EXECUTION_FINAL_REPORT.json`.
HEAD de partida: `325892d`.

## 1. Veredicto

```text
MICROSTRUCTURE_V1 VERIFICATION:  VERIFIED (0 failures)
FINAL STATUS:                    VENUE_EXECUTION_RESEARCH_VERIFIED_NO_CANDIDATE
PAPER CANDIDATES:                0
FALSE_SUCCESS:                   0
```

## 2. Los tres hallazgos

### Hallazgo A — el modelo de coste estaba mal y ahora es parametrizable

`COST_MODEL_V2` (cuatro escalares) → `COST_MODEL_V3` (función de venue, producto,
tier, modo de pago, maker/taker, tipo de orden por pata, spread, slippage,
tamaño, liquidez, volatilidad, fill probability, fills parciales, adverse
selection, funding, holding). Cada número lleva una clase
`KNOWN/OBSERVED/ESTIMATED/ASSUMED` y **nunca se mezclan**.

Invariante clave: **a VIP0 en Binance Spot el maker NO es más barato** (10 bps =
10 bps), así que "hacerse maker" no reduce el fee; solo añade riesgo de no-fill.

### Hallazgo B — el bloqueo es el fee del venue, no una propiedad del spot

| escenario | RT cost taker |
| --- | ---: |
| Binance USD-M perp | 13.79 bps (fuera del runtime: margen/apalancamiento/funding) |
| **MEXC Spot** | **17.79 bps** |
| Binance Spot con BNB | 18.79 bps |
| **Binance Spot (runtime)** | **23.79 bps** |
| Bybit / OKX Spot | 23.79 bps |
| Kraken Pro Spot | 83.79 bps |

Existe una configuración spot con **la mitad** del coste (MEXC: fee maker 0%,
taker 5 bps). Pero **aun así** el mejor edge medido no la alcanza (§4). Esto
reorienta el problema: no es "el spot no sirve", es "**nuestro fee actual es 2×**
y el venue alternativo solo baja el umbral a 17.79 bps".

### Hallazgo C — el tick real NO añade edge sobre el agregado por kline

La fase V1 señaló explícitamente que `aggTrades` histórico estaba sin explotar.
Se explotó, con 42 archivos diarios reales (60,480 filas por minuto):

| medición | best gross tradeable |
| --- | ---: |
| kline-aggregated flow (V1) | **+2.36 bps** |
| tick-level flow A-01 | +0.48 bps |
| tick flow + breakout A-03 | +0.61 bps |
| BTC lead/lag tick A-06 | +0.55 bps |

**Más granularidad no añadió edge ejecutable: añadió ruido.** El agregado por
kline ya extraía la parte informativa del flujo agresor.

## 3. Modelo de ejecución

`EXECUTION_MODEL_V1` separa taker (determinista, `EVIDENCE_BACKED`) de maker
(distribucional, **`EXECUTION_MODEL_REQUIRED`**: sin `FillEvidence` no emite
número). Un fee maker 0% **no** produce coste 0: la adverse selection sigue ahí.
Los escenarios sintéticos se etiquetan `SYNTHETIC_STRESS_TEST` y **no** son
admisibles.

Consecuencia: la **puerta de maker está cerrada** (§13): no existe evidencia
alcanzable de fill para demostrar `effective maker RT < gross edge`.

## 4. Resultados aggTrades

| candidata | n | gross DEV | mejor net de cualquier split | status |
| --- | ---: | ---: | ---: | --- |
| A-01 tick flow | 4,420 | +0.481 | −23.31 | COST_KILLED |
| A-02 clips grandes | 5,943 | +0.031 | −23.76 | COST_KILLED |
| A-03 flow+breakout | 2,563 | **+0.614** | −23.18 | COST_KILLED |
| A-04 burst | 0 | n/a | n/a | INSUFFICIENT_DATA |
| A-05 VWAP reversión | 279 | −6.253 | −12.02 | NO_GROSS_EDGE |
| A-06 lead/lag | 12,012 | +0.553 | −23.24 | COST_KILLED |

**Ninguna candidata tiene net positivo en ningún split.** El mejor gross de la
fase (A-03, +0.614 bps) está ~39× por debajo del coste.

### Trampa documentada (A-05)

A-05 tiene DEV **negativo** y VAL/OOS **positivos** (+11.78 / +8.63 bps
brutos). Elegir el período o la dirección después de ver los datos la
convertiría en una candidata aparente. La regla pre-registrada (dirección
congelada de DEV, Filter 1 sobre DEV) la rechaza y **se mantiene el rechazo**.
4 de 6 candidatas cambian de signo entre splits; solo A-06 es estable.

## 5. Recolección forward

`scripts/microstructure_collector.py` evolucionado a
`FORWARD-COLLECTOR-V1`/`forward-record-v1`: tres relojes, sequence IDs,
detección de gaps/stale/duplicados/regresiones, persistencia append-only y
manifest derivable.

Smoke real (40 s): 5,214 registros, 0 duplicados, 0 out-of-order, 0 gaps > 15 s.
**Limitación medida y declarada**: el polling REST de `aggTrades` **pierde
prints en bursts** (1 hueco, `worst_step = 19` en BTC). Una captura forward de
calidad requiere WebSocket. No se declara ningún resultado sobre datos forward
que aún no existen (§63).

## 6. Integridad y disciplina

* **PIT**: `available_at = open_time + 300,001 ms`; `available_at <= decision_time`.
* **Ventanas rolling dentro del día** (muestra discontinua) → sin fuga entre días.
* 0 días ausentes; unidades temporales verificadas (µs) en los 42 archivos.
* `net = gross − cost` y `net <= gross` comprobados fila a fila por el verificador.
* `ZERO_COST` nunca usado; ningún bruto presentado como neto.
* Core runtime **intacto** (§50): RiskManager, PaperBroker, Portfolio,
  StartupReconciler, StrategyRouter sin tocar.
* No se fabricó libro histórico (§16).

## 7. Verificación independiente (BUILDER != VERIFIER)

`scripts/research_verification.py` no confía en ningún número commiteado:

| check | resultado |
| --- | --- |
| artefactos MICROSTRUCTURE-V1 reproducen byte a byte (SHA-256) | PASS |
| coste de admission rederivado del módulo | PASS (23.5 bps V2) |
| tabla V1: `net == gross − cost` en todas las filas | PASS |
| `ZERO_COST` no es modelo de admission | PASS |
| `COST_MODEL_V3`/`VENUE_EXECUTION_MATRIX_V1`/`EXECUTION_MODEL_V1` regeneran idénticos | PASS |
| salidas aggTrades reproducen byte a byte | PASS |
| los 42 `AGG_*.json` cuadran con su hash de procedencia | PASS |
| `net == gross − cost`, `net <= gross` | PASS |
| ningún `PAPER_CANDIDATE` salta los filtros congelados | PASS |
| splits temporales no vacíos | PASS |
| rolling within-day | PASS |

## 8. Divergencia declarada respecto al informe V1

El informe de MICROSTRUCTURE-V1 afirmaba **`ruff` limpio**. La verificación
independiente sobre HEAD `325892d` encontró **4 errores de ruff**, todos en
`scripts/microstructure_collector.py` (UP017, F841, RUF100 ×2). El colector se
reescribió para la fase forward y los cuatro quedan **corregidos**. Ningún
resultado histórico se alteró por ello. `mypy` sí estaba limpio (264 ficheros) y
`pytest` pasa (656 tests en estado commiteado).

## 9. Decisiones (§58-59, §69)

```text
SPOT_INTRADAY_COST_BLOCKED
DERIVATIVES_RESEARCH_JUSTIFIED
NEXT RECOMMENDED PHASE: VENUE-AND-EXECUTION-RESEARCH-V1 (continuación)
```

Matiz obligatorio: no está bloqueado "el spot" en abstracto, está bloqueado
**nuestro fee actual**. MEXC demuestra que hay spot a 17.79 bps. Por eso la
siguiente fase es de venue/ejecución y de captura forward de libro — **no** más
variantes de señales: la evidencia de esta fase dice que el problema dominante
es el fee y la ausencia de un modelo de ejecución medido.

## 10. Blockers de producción

| id | blocker |
| --- | --- |
| PB-01 | 0 estrategias con net edge positivo tras coste realista |
| PB-02 | fee de Binance Spot VIP0 = 10 bps/lado; el modelo del proyecto asumía 5 |
| PB-03 | sin modelo de fill medido → ningún camino maker es admisible |
| PB-04 | sin histórico de libro → M-02 no testeable (requiere captura forward) |
| PB-05 | sin decisión de gobernanza sobre mover venue o aceptar el fee |

## 11. Entregables

Docs: `MICROSTRUCTURE_V1_INDEPENDENT_VERIFICATION.md/.json`,
`COST_MODEL_V3.md/.json`, `VENUE_EXECUTION_RESEARCH_V1.md`,
`VENUE_EXECUTION_MATRIX_V1.json`, `EXECUTION_MODEL_V1.md/.json`,
`MICROSTRUCTURE_FORWARD_COLLECTION_V1.md`, `AGGTRADES_HYPOTHESES_V1.md`,
`AGGTRADES_EXPERIMENTS_V1.md`, `AGGTRADES_RESULTS_V1.md/.json`,
`VENUE_EXECUTION_FINAL_REPORT.md/.json`, `source_registry.md`.

Código: `src/trading_bot/research/microstructure/{cost_model_v3,execution_model_v1}.py`,
`scripts/{venue_execution_research,fetch_aggtrades_microstructure,aggtrades_experiments,research_verification}.py`,
colector reescrito, y tests en `tests/unit/microstructure/`.

## 12. Regla final

El hallazgo de V3 fue `OHLCV EDGE <= EXECUTION COST`. Esta fase respondió con
**economía real de ejecución + información nueva**, no con más indicadores. El
resultado es que la economía real es **peor** de lo asumido, que existe **una**
configuración spot con la mitad de coste pero que ni esa alcanza, y que la
información nueva a resolución de tick **no añade** edge sobre el agregado ya
explotado.

```text
DO_NOT_ADOPT.
```
