# RFC-EDGE-009 — Market Microstructure & Economic Edge Research

**Proyecto:** Trading Agentic Portable  
**Estado:** PROPOSED — pendiente de auditoría contra el repositorio real  
**Fecha:** 2026-10-14  
**Prioridad:** P0 para investigación económica; **no** autoriza PAPER ni LIVE  
**Dependencias:** RFC-EDGE-008 / WP-EDGE-08, runtime y registro de evidencias vigentes  
**Propietario de implementación:** Codex (builder)  
**Verificación:** proceso/implementación independiente del builder

## 1. Contexto y evidencia de partida

El último cierre comunicado de WP-EDGE-08 (`HEAD=ef5c8f2`, según Codex, sin verificación independiente desde este documento) informa de seis propuestas nuevas, tres descartadas por screening bruto y tres examinadas una sola vez en un corte transversal de AAVE/UNI/KSM/SNX/CRV/SUSHI (304.158 barras; digest reportado `fb32470f…`). Las tres examinadas tuvieron PnL neto negativo: `edge08_quality_breakout_daily` −166,61 USDT / 30 operaciones / 0,046 operaciones/día; `edge08_active_daybreak_1h` −474,09 / 103 / 0,158; `edge08_active_multiday_range_1h` −494,71 / 128 / 0,197. Los comparadores CURRENT también perdieron en el mismo corte: −415,83, −350,74 y −215,90 USDT. La variante tendencial de objetivo fijo 3×ATR había sido rechazada previamente en NEW_HOLDOUT (65 operaciones; −140,30 USDT). No existe estrategia con ventaja neta robusta demostrada ni permiso de promoción.

**Interpretación permitida:** estas familias y configuraciones no superaron sus criterios en las muestras indicadas. **Interpretación prohibida:** que toda estrategia horaria, toda microestructura o todos los mercados sean inviables. Las ventanas ya examinadas quedan registradas como **CONSULTED/SPENT** y nunca se presentan como holdout nuevo.

Los tests propios de WP-EDGE-08 y verificación selectiva se reportaron favorables; la suite completa `tests/unit/research` no terminó tras dos intentos de 600 s. La continuidad forward depende del almacenamiento; el volumen ha cruzado repetidamente los umbrales de seguridad. Estos son **hechos reportados por Codex**, que el primer WP debe contrastar con runtime, git y artefactos reales.

## 2. Problema

El descubrimiento de alfa se ha concentrado en familias OHLCV y variantes de reglas que no han demostrado transferencia económica. Antes de desarrollar nuevas estrategias debemos determinar: (a) qué datos point-in-time existen realmente; (b) qué hipótesis tienen mecanismo económico falsable; (c) si el movimiento capturable excede costes completos; (d) qué experimentos pueden hacerse sin contaminar nueva evidencia; y (e) si la plataforma puede reproducirlos en el runtime autoritativo.

## 3. Objetivos y no objetivos

### Objetivos

1. Inventariar y clasificar datos de mercado, metadatos de instrumentos y datos alternativos por proveedor, licencia, granularidad, timestamps, profundidad, costes, latencia y cobertura.
2. Formular hipótesis económicamente motivadas en microestructura, regímenes, relaciones entre activos y eventos, **solo si los datos las soportan**.
3. Construir un filtro de viabilidad antes de implementar simuladores o estrategias.
4. Reutilizar el motor autoritativo de costes, riesgo, ejecución simulada, campañas y evidencias; no construir otro motor de PnL.
5. Registrar hipótesis, múltiples ensayos y ventanas consultadas; evitar sobreajuste y falsos éxitos.
6. Diferenciar QUALITY de ACTIVE. ACTIVE conserva el objetivo de ≥3 **operaciones ejecutadas** al día agregado en el universo cripto 7/7, sin obligar al sistema a abrir operaciones.
7. Entregar una decisión auditable: `NO_VIABLE_DATA`, `NO_ECONOMIC_EDGE_FOUND` o `RESEARCH_CANDIDATE` (que **no** implica PAPER).

### No objetivos

- No activar trading real, alterar `risk.yaml`, aumentar apalancamiento, tamaño o exposición, ni operar con credenciales privadas.
- No descargar grandes datasets de pago ni incurrir en costes relevantes sin aprobación.
- No simular L2/order book, liquidaciones, funding u open interest con OHLCV como si fueran observaciones reales.
- No crear agentes LLM adicionales, orquestadores paralelos, frameworks completos o estrategias de producción por defecto.
- No relajar gates de WP-EDGE-08 ni reciclar holdouts consumidos.

## 4. Autoridad y baseline obligatorios

Orden: `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`.

Antes de editar, Codex debe: comprobar `git status`, HEAD, rama, remotos y worktrees; identificar entrypoints reales, scheduler, market-data, normalizadores, store, backtest, risk, costs, portfolio, ejecución paper/shadow, reconciliación, scripts y tests; clasificar rutas como `RUNTIME_AUTHORITATIVE`, `RUNTIME_REACHABLE`, `TEST_ONLY`, `RESEARCH_ONLY`, `EXPERIMENTAL`, `LEGACY`, `ORPHAN` o `DEAD_CODE`; crear/actualizar `runtime_authority_map.md`; preservar las entradas sucias de otros workstreams; y capturar un baseline reproducible con commits, entorno, disco, tests relevantes y digests.

No inferir que `HEAD=ef5c8f2` sigue siendo el actual: verificarlo.

## 5. Arquitectura propuesta

```text
Existing data providers / immutable market data
             |
             v
Data Capability Inventory + Point-in-Time Contracts
             |
             v
Economic Mechanism Registry + Hypothesis Pre-Registration
             |
             v
Data Feasibility Gate --(no reliable data)--> NO_VIABLE_DATA
             |
             v
Cost / Capacity / Frequency Feasibility Gate
             |--(no plausible net edge)-------> NO_ECONOMIC_EDGE_FOUND
             v
Discovery Sandbox (DEV only, isolated, read-only)
             |
             v
Validation / Multiplicity / Robustness (VAL, controlled)
             |--(failure)---------------------> REJECT / DEFER
             v
RESEARCH_CANDIDATE + Evidence Dossier
             |
             v
Existing Strategy Admission pipeline (separate future RFC/gates)
```

El **Trading Runtime Plane** mantiene control determinista de calidad de datos, riesgo, sizing, costes, simulación de ejecución, PnL y reconciliación. El **Research Plane** solo puede producir hipótesis, mediciones y candidatos; no puede escribir directamente en producción ni promover estrategias. Los LLM pueden sintetizar fuentes y criticar hipótesis, pero no decidir sizing, riesgo o ejecución.

## 6. Contratos de datos

### 6.1 `DataCapabilityRecord`

Campos mínimos: `dataset_id`, `provider`, `instrument`, `venue`, `market_type` (spot/perpetual/etc.), `data_type` (OHLCV/trades/quotes/L2/funding/OI/liquidations/event), `resolution`, `first_event_time_utc`, `last_event_time_utc`, `first_available_at_utc`, `availability_semantics`, `ingested_at_utc`, `coverage`, `gaps`, `duplicates`, `stale_rate`, `provider_failure_rate`, `license`, `retrieval_cost`, `storage_cost`, `source_version`, `sha256`, `authority_class`, `quality_verdict`.

**Regla PIT:** `event_time <= available_at <= decision_time` cuando corresponda; datos revisados/publicados posteriormente solo podrán usarse desde su disponibilidad real. No confundir timestamp de una vela con timestamp de disponibilidad de una observación externa. La ausencia de metadatos de disponibilidad impide afirmar causalidad PIT.

### 6.2 `EconomicHypothesis`

`hypothesis_id`, `version`, `family`, `mechanism`, `economic_rationale`, `assets`, `venues`, `timeframes`, `regimes`, `required_data[]`, `signal_spec`, `counter_hypothesis`, `expected_gross_move_bps`, `cost_model_id`, `capacity_assumptions`, `minimum_viable_net_edge`, `invalidation`, `pre_registered_metrics`, `multiple_testing_family`, `experiment_budget`, `window_policy`, `owner`, `created_at_utc`, `code_commit`, `status`.

Estados: `PROPOSED → DATA_CHECKED → FEASIBLE → DEV_TESTED → VAL_TESTED → RESEARCH_CANDIDATE`; salidas terminales `NO_VIABLE_DATA`, `NO_ECONOMIC_EDGE_FOUND`, `REJECT`, `DEFER`. Transiciones append-only con motivo y evidencia.

### 6.3 `ExperimentLedger`

`experiment_id`, `hypothesis_id`, `dataset_fingerprints[]`, `window_id`, `window_role` (`DEV`, `VAL`, `CONSULTED_OOS`, `FRESH_OOS`, `FORWARD`), `first_read_utc`, `config_digest`, `commit`, `execution_target`, `risk_contract`, `cost_contract`, `trade_count`, `net_pnl`, `gross_pnl`, `fees`, `slippage`, `funding`, `turnover`, `exposure`, `max_drawdown`, `profit_factor`, `expectancy`, `uncertainty`, `daily_trade_distribution`, `failure_reason`, `verifier_id`, `artifact_digests[]`.

Toda lectura de holdout se registra antes de la evaluación; una lectura fallida también consume el estado que efectivamente se inspeccionó. La repetición para reproducibilidad conserva rol `CONSULTED`, nunca vuelve a `FRESH`.

## 7. Hipótesis iniciales (no aprobadas)

| Familia | Mecanismo a contrastar | Datos mínimos | Criterio de parada temprana |
|---|---|---|---|
| Spreads y liquidez | Captura neta condicionada por spread/profundidad | Trades + bid/ask y, para profundidad, L2 con PIT | Sin datos o coste de ejecución mayor que oportunidad |
| Regímenes | Momentum/reversión solo en regímenes observables en tiempo real | OHLCV PIT, volatilidad, volumen | Segmentación inestable o fuga temporal |
| Cross-asset | Liderazgo/rezago BTC-ETH-altcoins | Barras sincronizadas PIT, venue y reloj consistentes | Desfase desaparece con latencia/costes |
| Funding/OI | Desequilibrios y cambios de posicionamiento | Histórico de funding/OI con tiempo de publicación real | Backfill sin disponibilidad histórica demostrable |
| Eventos | Reacción postevento capturable | Feed de eventos con timestamps de publicación | Solo timestamps retrospectivos o datos revisados |

No implementar las cinco familias automáticamente. Seleccionar como máximo las justificadas por datos y presupuesto experimental; el resto `DEFER/REJECT` con evidencia.

## 8. Gate económico previo a simulación

Para cada hipótesis estimar, con supuestos conservadores y trazables:

`net_edge_bps = expected_capturable_gross_bps - fees_bps - spread_crossing_bps - slippage_bps - market_impact_bps - funding_bps - other_costs_bps`.

No sumar dos veces componentes que el runtime ya modele; identificar costes maker/taker, ejecución parcial, latencia, límites de capacidad, fallos y cancelaciones. Medir sensibilidad base, adversa y estrés con los escenarios ya congelados en el runtime. Si los datos no permiten una estimación defendible, el estado es `UNKNOWN/DEFER`, **no** cero coste.

Para ACTIVE medir operaciones **realmente ejecutables por día calendario UTC**, por activo y agregadas, porcentaje de días con ≥3 operaciones, distribución p10/p50/p90, días sin operaciones y PnL neto; no sustituir por media mensual. La frecuencia nunca compensa expectativa negativa.

## 9. Protocolo estadístico y prevención de sobreajuste

- Mantener DEV, VAL y ventanas ya consultadas explícitamente separadas; reservar nuevas ventanas sin leer cuando existan.
- Registrar familia de hipótesis, número de pruebas, ajustes y resultados negativos; aplicar controles de multiplicidad y sensibilidad al data snooping adecuados al tamaño muestral.
- Usar validación temporal purgada/embargada cuando haya solapamiento de posiciones, etiquetas o horizontes; no usar shuffle aleatorio de trades dependientes.
- Reportar incertidumbre con métodos sensibles a dependencia temporal (p. ej. bootstrap por bloques cuando sea apropiado), concentración de ganadores, drawdown y sensibilidad a costes.
- Comprobar robustez por activo, régimen, época y venue; **seis símbolos no permiten generalización universal**.
- Ninguna cifra de DEV o VAL se etiqueta como forward; la ventana de 60 días forward se cuenta únicamente desde observación prospectiva elegible.
- La decisión `RESEARCH_CANDIDATE` requiere evidencias suficientes para seguir investigando, no prueba de rentabilidad futura ni admisión a PAPER.

## 10. Work packages

### WP-EDGE-09A — Runtime & data authority baseline

Auditar entrypoints, datasets y pipelines, mapa de autoridad, baseline, cobertura PIT, datos disponibles y ausentes, fuentes y digests. **Salida:** `DATA_CAPABILITY_REGISTRY.md/json`, `runtime_authority_map.md`, `BASELINE.json`. No descargar datos todavía.

### WP-EDGE-09B — Source & feasibility registry

Crear `source_registry.md` (`SOURCE_ID`, URL, tipo, versión/commit, patrón, evidencia, fiabilidad, coste/licencia), verificar proveedores y semántica de disponibilidad; matriz `PROJECT != PATTERN != IMPLEMENTATION`. Proponer datasets opcionales sin contratar ni descargar datos de coste relevante. **Salida:** `DATA_FEASIBILITY_MATRIX.md/json`.

### WP-EDGE-09C — Economic mechanism & pre-registration

Formalizar hipótesis falsables y controles negativos, identificar datos mínimos, presupuestos de experimentos y ventanas permitidas. **Salida:** `HYPOTHESIS_REGISTRY.json`, `EXPERIMENT_PLAN.md`, `WINDOW_LEDGER.jsonl` (append-only). Congelar planes antes de DEV/VAL.

### WP-EDGE-09D — Cost, capacity & frequency screening

Reutilizar costes y constraints autoritativos; estimar cotas económicas y de frecuencia. Si ningún candidato es viable, **terminar aquí con `NO_ECONOMIC_EDGE_FOUND` o `NO_VIABLE_DATA`**. **Salida:** `ECONOMIC_FEASIBILITY_REPORT.md/json`, `COST_CAPACITY_FREQUENCY_MATRIX.md`.

### WP-EDGE-09E — Minimal controlled experiments (conditional)

Solo para hipótesis que superen 09D: adaptadores mínimos aislados, DEV y VAL, comparadores CURRENT con mismo corpus/costes, pruebas de robustez, registro de todos los ensayos, sin abrir nuevos holdouts salvo que haya una justificación y un protocolo pre-registrado separado. No introducir rutas LIVE. **Salida:** `EXPERIMENT_LEDGER.jsonl`, `RESULTS_MATRIX.md/json`.

### WP-EDGE-09F — Independent verification & decision

Verifier distinto del builder: recalcular hashes, PIT, ventanas, costes, trades, ausencia de promociones, reproducibilidad y reportes; sabotajes dirigidos; informar fallos globales heredados y tests no ejecutados. **Salida:** `VERIFICATION.json/md`, `RUN_REPORT.json/md`, `FINAL_REPORT.md`, `INFORME_EJECUTIVO.md` desde snapshot único.

## 11. Criterios de aceptación (ACC)

| ID | Criterio | Evidencia mínima |
|---|---|---|
| ACC-01 | Baseline y mapa de autoridad corresponden a HEAD/runtime real | Hashes, comandos, rutas y trazas |
| ACC-02 | Datos inventariados con cobertura, disponibilidad y licencia | Registry + pruebas de muestra |
| ACC-03 | No se atribuye microestructura a OHLCV sin datos de microestructura | Contract tests + sabotaje |
| ACC-04 | PIT sin futuro, stale ni timestamps fabricados | Tests causales y adversariales |
| ACC-05 | Ventanas consumidas de EDGE-07/08 quedan bloqueadas | Ledger y tests de doble lectura |
| ACC-06 | Hipótesis y criterios se congelan antes de experimentos | Commit/orden temporal verificable |
| ACC-07 | Costes completos se calculan con motor autoritativo | Comparación de contratos y trace |
| ACC-08 | Capacidad y frecuencia ACTIVE medidas por día y universo | Distribución diaria reproducible |
| ACC-09 | Todos los intentos, incluidos descartes, constan en ledger | Contabilidad de ensayos |
| ACC-10 | Comparación CURRENT/PROPOSED con mismos datos y costes | Matriz pareada |
| ACC-11 | Robustez temporal y por activo/regímenes; incertidumbre | Resultados y metodología |
| ACC-12 | Gate temprano detiene trabajo cuando faltan datos o edge | Test `NO_VIABLE_DATA/NO_ECONOMIC_EDGE_FOUND` |
| ACC-13 | Ningún código de investigación puede enviar órdenes o alterar riesgo | Test de permisos y diff |
| ACC-14 | Verificador independiente detecta sabotajes de datos/ledger/reportes | Self-tests con salida no cero |
| ACC-15 | Informes MD/JSON derivan de snapshot único, con `as_of_utc` | Digests y prueba de consistencia |
| ACC-16 | Tests de unidad, contrato, integración y runtime aplicables ejecutados | Comandos, exits, fallos y cobertura |
| ACC-17 | Forward continúa sin atribuir backfill como prospectivo | Ledger de días elegibles |
| ACC-18 | Resultado final distingue cierre técnico y edge económico | Decisión y gates explícitos |

`PASS` global inválido si se omiten verificaciones exigibles, se reutiliza holdout, se declara runtime sin ejecutarlo o se oculta una anomalía. Las limitaciones ambientales deben reflejarse como `BLOCKED` o `NOT_TESTED`, no `PASS`.

## 12. Pruebas adversariales obligatorias

1. Barra futura insertada en señal; 2. `available_at` posterior a decisión; 3. evento backfilled presentado como histórico disponible; 4. L2 sintético etiquetado real; 5. costes omitidos o doble contabilizados; 6. ledger con ensayo eliminado; 7. holdout consumido reetiquetado fresco; 8. duplicado de trade/fill; 9. reloj y venue desalineados; 10. informe Markdown divergente de JSON; 11. snapshot alterado; 12. promoción/orden invocada desde investigación; 13. frecuencia promediada ocultando días vacíos; 14. dependencia temporal ignorada; 15. dato stale/proveedor caído tratado como señal válida; 16. espacio bajo el suelo ignorado.

El verificador debe fallar **por la causa esperada**, no por un error incidental, y conservar evidencias de cada sabotaje.

## 13. Operación, fallos y seguridad

- Conservar scheduler/forward existente y protecciones de disco; no modificar ni borrar evidencias autoritativas.
- Investigación pesada separada del scheduler; pausar tareas opcionales cuando disco <5 GiB o al alcanzar el umbral sano vigente, sin relajar el mínimo crítico.
- Fallos de proveedor, rate limits, timestamps inciertos, costes desconocidos y licencia no permitida generan `BLOCKED/DEFER`, nunca datos inventados.
- Mantener credenciales fuera de artefactos y logs; usar únicamente APIs públicas/autorizadas sin gastos relevantes.
- Los artefactos y resultados son append-only o versionados; no regenerar certificados congelados para forzar PASS.
- No borrar temporales de otros workstreams ni archivos externos al repositorio sin aprobación explícita.

## 14. Definition of Done, evidencia y trazabilidad

`SOURCE → INSIGHT → REQ → ACC → ARCH → RFC → WP → IMP → TEST → EXEC → EVID`.

Cada fase genera `RUN_REPORT.md` y `RUN_REPORT.json` con `run_id`, commit, entorno, datasets/digests, hipótesis, tests, decisiones, errores, métricas, resultado y artefactos. `FINAL_REPORT.md`: `PHASE / COMMITS / IMPLEMENTED / TESTS / RUNTIME_VALIDATION / PAPER_VALIDATION / FALSE_SUCCESS / DEFECTS / BLOCKERS / EVIDENCE / ARCHITECTURE_STATUS / RFC_STATUS / NEXT_PHASE`.

Las métricas económicas deben incluir gross/net, desglose de costes, trades, expectancy, drawdown, profit factor, concentración, incertidumbre, dependencia, robustez, frecuencia por día y coste de investigación. Publicar también los resultados negativos.

**Veredictos permitidos:**
- `NO_VIABLE_DATA`: no hay datos causales suficientes para probar hipótesis seleccionadas.
- `NO_ECONOMIC_EDGE_FOUND`: el cribado/experimentos no muestran ventaja económica defendible.
- `RESEARCH_CANDIDATE`: hipótesis merece validación futura separada; **NO** `PAPER_READY`.
- `BLOCKED` / `CLOSED_WITH_OPEN_ITEMS`: obstáculos operativos o pruebas pendientes.

## 15. Rollback

Revertir exclusivamente commits del paquete sin alterar workstreams paralelos; conservar ledgers y evidencias; deshabilitar adaptadores de investigación mediante feature flag; comprobar que scheduler, riesgo, ejecución y datos existentes permanecen invariantes. Prohibido `git reset --hard` indiscriminado, force push o borrar registros de experimentos.

## 16. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Sobreajuste y múltiples ensayos | Pre-registro, ledger exhaustivo, corrección de multiplicidad |
| Look-ahead y timestamp falso | Contrato PIT + pruebas adversariales |
| Simulación de microestructura sin datos | Gate de capacidad de datos |
| Costes subestimados | Motor autoritativo y escenarios adversos |
| Generalización falsa | Validación por activo, época y régimen |
| Disco lleno / scheduler detenido | Preservar guardrails y aislar research pesado |
| Falsa certificación | Builder != verifier; tests runtime y evidencias |
| Scope creep | Gates 09B/09D; detenerse si no hay hipótesis viable |

## 17. Instrucción ejecutiva para Codex

> Implementa RFC-EDGE-009 como WP-EDGE-09A→09F con máxima autonomía y mínimo alcance necesario. Primero audita el estado real y comprueba si existen trabajos previos; no dupliques. Congela contratos e hipótesis antes de experimentar. Ejecuta 09E **solo** si 09D justifica datos y ventaja potencial. Usa exclusivamente el runtime/costes autoritativos; no consumas holdouts gastados, no fuerces tres operaciones diarias y no promociones estrategias. Entrega informes desde una lectura consistente, verificación independiente, sabotajes, resultados negativos, commits aislados y push seguro sin force. Si los datos o la economía no sostienen las hipótesis, detente con `NO_VIABLE_DATA` o `NO_ECONOMIC_EDGE_FOUND`. No solicites aprobaciones para acciones técnicas reversibles; sí para costes, credenciales, borrados ajenos, cambios de riesgo o trading real.

---

**Criterio de éxito de esta fase:** mejorar la calidad de las decisiones de investigación, **no** producir obligatoriamente una estrategia ganadora. Sin ventaja económica robusta demostrada: `DO_NOT_ADOPT`.
