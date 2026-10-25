<!--
Copia del RFC tal y como fue recibido (v0.1 — propuesta para implementación, 2026-10-21).
Añadido a este directorio porque RFC-EXP-003P §10 lo exige entre los entregables.
El ejecutor de EXP-003P no modificó el texto: la implementación y sus desviaciones están
declaradas en FINAL_REPORT.md (DEFECTS, BLOCKERS, límites).
-->

# RFC-EXP-003P — Paper Execution Lifecycle, Provenance & Reconciliation

| Campo | Valor |
|---|---|
| ID | `RFC-EXP-003P-PAPER-EXECUTION` |
| Versión | `0.1 — propuesta para implementación` |
| Fecha | `2026-10-21` |
| Proyecto | Trading Agentic Portable |
| Experimento | `EXP-003P-PAPER-EXECUTION-001` |
| Dependencia | `EXP-003O-INDEPENDENT-SIGNAL-VERIFICATION-001` |
| Estado | `PROPOSED / NOT_EXECUTED` |
| Modo autorizado | `OFFLINE_SIMULATED`; `VENUE_REPORTED_PAPER` solo con infraestructura paper previamente autorizada |
| Modos prohibidos | `LIVE`, capital real, promoción de estrategias, apertura de holdout |

> **Alcance de evidencia:** este RFC utiliza el resultado de 003O comunicado por el ejecutor y el documento `EXP_003P_PROMPT_CODEX.md`. No constituye una nueva inspección del repositorio ni una validación independiente de los artefactos en `127.0.0.1`. Codex deberá comprobar los archivos y los hashes originales antes de implementar.

## 1. Contexto, evidencia y problema

`EXP-003O` informa paridad técnica de señales: 275 724 claves comparadas, 52 848 señales por flujo, cero diferencias inexplicadas, cero violaciones point-in-time (PIT), 12/12 controles negativos, 174 tests y reproducción bit-idéntica en checkout limpio. Su cierre sigue siendo `PASS_PARTIAL_INCOMPLETE_REAL_DATA`. Dos celdas 4h no tuvieron instantes evaluables (276 barras disponibles frente a warm-up 744) y `organizational_independence=false` porque los tres programas fueron escritos por el mismo agente. `ECONOMIC_EDGE=NOT_EVALUATED`.

**Problema:** que dos generadores produzcan las mismas señales no demuestra que el sistema pueda transformar una propuesta válida en una orden paper segura, observar su estado real, manejar fills parciales, contabilizar posiciones y reconciliar con una fuente primaria. Tampoco demuestra rentabilidad. El proyecto necesita distinguir de forma verificable la ejecución simulada local de los eventos observados de un proveedor paper.

**Decisión de diseño:** instrumentar y probar el **runtime paper ya existente y efectivamente alcanzable**. No crear una segunda plataforma de ejecución, otro risk engine ni integrar un broker nuevo por conveniencia. Si no existe ruta paper con proveedor configurado, validar offline y declarar la parte externa bloqueada.

## 2. Objetivos y exclusiones

**Objetivos:**

1. Reconstruir la ruta real `signal → TradeProposal → decision/NO_TRADE → risk → order intent → paper adapter → order events → fills → accounting → reconciliation → evidence`.
2. Mantener correlación y procedencia inmutables desde la señal hasta la reconciliación, incluso tras reintentos, mensajes desordenados y reinicios.
3. Impedir que ACK, orden enviada, fill simulado y fill reportado por proveedor sean confundidos.
4. Garantizar idempotencia contable, protección ante duplicados, riesgo determinista y degradación *fail-closed*.
5. Acreditar lo que realmente fue ejecutado mediante logs, informes reproducibles y verificación separada.

**Fuera de alcance:** análisis de edge económico, optimización de estrategias, backtesting adicional para seleccionar ganadores, tuning sobre holdout, trading live, nuevos permisos/credenciales, cambios de capital o apalancamiento, sustitución del motor de riesgo, nuevas estrategias y certificación completa de 003O.

## 3. Autoridad, invariantes y límites

La jerarquía es `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > EXTERNAL_SOURCE > ASSUMPTION`. Los nombres de ficheros y contratos conceptuales no prueban alcanzabilidad real.

**Invariantes heredados, no negociables:**

- `003O=PARTIAL`; `FULL_INDEPENDENT_CERTIFICATION=INCOMPLETE_REAL_DATA_COVERAGE`; `organizational_independence=false` en 003O.
- `ECONOMIC_EDGE=NOT_EVALUATED`, `STRATEGY_PROMOTION=DENIED`, `HOLDOUT=CLOSED`.
- `LIVE=DISABLED`, `live_orders=0` en toda 003P; ninguna ruta CLI, flag o adapter de 003P podrá alcanzar una orden real.
- Risk, sizing, límites, contabilidad y autorización de envío son deterministas. Ningún LLM puede cambiar límites, fijar libremente tamaño/apalancamiento ni invocar una orden.
- `data_time <= decision_time`; no usar datos stale ni HTF del futuro.
- Los archivos `config/runtime.yaml`, `config/risk.yaml`, `config/vision.yaml`, los sellos 003N/003O y el preregistro congelado 003O no deben alterarse para facilitar el experimento.
- La cobertura real ausente de `mean_reversion_vol_liq@4h` y `vol_regime_breakout@4h` no se presenta como evaluada; `vol_regime_breakout@1h` sí tuvo 1 083 evaluaciones y cero señales.
- `docs/agentic/EXECUTION_CHECKPOINT.md` puede contener modificaciones ajenas: no se sobrescribe ni se incluye en un commit sin aislar la autoría del diff.

## 4. Requisitos y criterios de aceptación

| REQ | Requisito | Criterio de aceptación (ACC) |
|---|---|---|
| `REQ-003P-01` | Autoridad de runtime | Mapa de entrypoints y de componentes clasificados; ruta paper alcanzable demostrada o bloqueo explícito. |
| `REQ-003P-02` | Procedencia | El 100 % de eventos incluidos tiene `provenance`, adapter, reloj y correlación; ninguna inferencia silenciosa del origen. |
| `REQ-003P-03` | Causalidad | `data_time <= decision_time <= order_intent_time`; violaciones detectadas, rechazadas y registradas. |
| `REQ-003P-04` | Riesgo determinista | Cero órdenes transmitidas sin `risk=PASS` y sin verificación de política; `NO_TRADE` termina sin orden. |
| `REQ-003P-05` | Ciclo de órdenes | Estados y transiciones válidas comprobados; `ACK != FILL`; terminales no reviven por reintentos. |
| `REQ-003P-06` | Idempotencia | Una misma clave de fill afecta contabilidad exactamente una vez, incluso en replay, retry o restart. |
| `REQ-003P-07` | Contabilidad | Cantidades, efectivo, posiciones, fees y PnL reconstruibles de eventos elegibles; discrepancia = fallo o incompleto explícito. |
| `REQ-003P-08` | Reconciliación | Comparación contra la fuente primaria disponible; ausencia de fuente primaria externa se declara, no se simula. |
| `REQ-003P-09` | Resiliencia | Caídas, timeouts y estados desconocidos no producen órdenes duplicadas ni fills inventados. |
| `REQ-003P-10` | Observabilidad | Cada run produce trazas, métricas, conteos por origen, errores y manifiesto verificable. |
| `REQ-003P-11` | Controles adversariales | Cada mutación dirigida falla con la clase esperada; no se admite PASS por un fallo colateral. |
| `REQ-003P-12` | Independencia | Verificador técnicamente separado y declaración honesta de independencia organizativa. |
| `REQ-003P-13` | Seguridad | `LIVE` inaccesible, sin secretos en reportes; flags y hashes de config preservados. |
| `REQ-003P-14` | Reproducibilidad | Dos reproducciones offline con mismos inputs/versiones generan el mismo estado y digest canónico, sin efectos externos. |

## 5. Arquitectura y runtime flow

```text
SOURCE DATA [timestamp/freshness/PIT]
  → SIGNAL [signal_id]
  → TradeProposal [proposal_id, evidence]
  → Decision [decision_id; TRADE | NO_TRADE]
  → Independent policy/evidence gate
  → Deterministic Risk / Sizing [hard veto]
  → OrderIntent [stable client_order_id; provenance]
  → Existing Paper Adapter [only if authorized/configured]
  → Provider ACK / reject / partial / fill / cancel / expiry
  → Durable Event Store [raw event + digest + dedupe key]
  → Order State Projection
  → Fill Ledger / Position & Cash Projection
  → Reconciliation [event vs ledger vs provider snapshot]
  → DecisionTrace / RUN_REPORT / seal
```

La observación de eventos y el ledger son **proyecciones de hechos registrados**, no decisiones de agentes. El verificador previo a la orden no sustituye una revisión posterior de reconciliación. La ruta de `NO_TRADE` debe dejar trazabilidad sin crear `OrderIntent` enviable. Un fallo de risk, freshness, política o reconciliación impide nuevas órdenes relacionadas hasta resolución conforme a las reglas existentes.

### 5.1 Provenance tipada

`OFFLINE_SIMULATED`: evento generado localmente; acredita semántica de código, **no** broker paper.  
`REPLAY_CAPTURED`: repetición de una captura preexistente; acredita replay, **no** una nueva orden ni nuevo fill.  
`VENUE_REPORTED_PAPER`: evento recibido y preservado del proveedor verificablemente paper/testnet, con vínculo a orden y cuenta de ese entorno; acredita observación paper, **no** ejecución en mercado real.

Se registra también `provider_environment` (`OFFLINE`, `TESTNET`, `PAPER`, etc.) y, si existe, `provider_event_id`. El origen no puede elevarse por cambio de etiqueta o por inferencia basada en el tipo de adapter. Se conserva la prueba de que el endpoint/cuenta no es live, sin revelar credenciales o identificadores sensibles.

### 5.2 Contratos mínimos, adaptados al modelo real

**ExecutionEnvelope:** `schema_version`, `run_id`, `commit_sha`, `config_digest`, `decision_id`, `proposal_id`, `signal_id`, `client_order_id`, `venue_order_id?`, `event_id`, `asset`, `strategy_id`, `adapter_id`, `event_type`, `event_time_utc`, `received_time_utc`, `clock_source`, `provenance`, `provider_environment`, `payload_digest`, `correlation_parent_id?`.

**OrderIntent:** `side`, `order_type`, `quantity`, `limit_price?`, `time_in_force?`, `risk_evaluation_id`, `policy_verification_id`, `idempotency_key`, `decision_time_utc`, `data_cutoff_utc`. Se usan los campos originales si el proyecto ya tiene contratos compatibles.

**FillFact:** identificador durable por proveedor/orden/fill, `filled_quantity`, `fill_price`, `fee_amount`, `fee_currency`, `side`, `event_time_utc`, `provenance`, raw-event hash. No puede postearse en un ledger de ejecución observada si su origen es `OFFLINE_SIMULATED`.

**ReconciliationResult:** `run_id`, `source`, `as_of_time`, `local_order_state`, `provider_order_state?`, `local_qty`, `provider_qty?`, `cash_delta`, `position_delta`, `fee_delta`, `differences[]`, `result=PASS|FAIL|INCOMPLETE`, `evidence_refs[]`.

**Reglas de identidad:** idempotencia de envío por `client_order_id` estable y por identificador de intent; idempotencia de contabilización por clave del fill en su namespace de origen. Los reintentos no inventan nuevos identificadores para la misma intención. Si el proveedor no soporta consulta/idempotencia suficientes, la orden queda `UNKNOWN` y el envío se bloquea hasta conciliación.

### 5.3 Máquina de estados de órdenes

Estados semánticos mínimos: `CREATED`, `RISK_REJECTED`, `SUBMITTING`, `ACKNOWLEDGED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `REJECTED`, `EXPIRED`, `UNKNOWN`. Ajustar nombres al enum existente sin perder significados.

| Desde | Transición normal | Requisito |
|---|---|---|
| `CREATED` | `RISK_REJECTED` o `SUBMITTING` | `SUBMITTING` solo con política/risk aprobados. |
| `SUBMITTING` | `ACKNOWLEDGED`, `REJECTED` o `UNKNOWN` | Timeout sin confirmación → `UNKNOWN`; no es ACK. |
| `ACKNOWLEDGED` | `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `EXPIRED` o `UNKNOWN` | Fill requiere hecho de fill válido, no mera aceptación. |
| `PARTIALLY_FILLED` | `FILLED`, `CANCELED`, `EXPIRED` o `UNKNOWN` | Cantidad ejecutada se conserva si se cancela el remanente. |
| Terminal | Sin mutación arbitraria | Eventos posteriores contradictorios se auditan/reconcilian, no se aplican a ciegas. |
| `UNKNOWN` | Estado confirmado por fuente primaria | Resolver mediante consulta/reconciliación, no mediante suposición o reenvío automático. |

Eventos duplicados se registran como duplicados sin doble efecto. Eventos fuera de orden no deben descartar hechos verdaderos: conservar el evento bruto, detectar `OUT_OF_ORDER_EVENT` y recomputar una proyección causal solo con hechos autenticados. Un fill recibido antes de ACK dispara `FILL_WITHOUT_ACK` y requiere comprobación contra fuente primaria; no crear un ACK ficticio para completar la secuencia. Cantidad acumulada nunca negativa ni superior a la ordenada, salvo estado de anomalía explícita.

### 5.4 Contabilidad y reconciliación

El ledger registra aplicaciones exactamente una vez por fill, separando namespaces `OFFLINE_SIMULATED`, `REPLAY_CAPTURED` y `VENUE_REPORTED_PAPER`. Las comisiones conservan su moneda y precisión; si no hay tasa verificable para conversión, el PnL neto correspondiente es `NOT_AVAILABLE` en vez de asumir fee cero.

Invariantes: `cum_filled_qty = suma(unique fills)`, `0 <= cum_filled_qty <= ordered_qty`; efectivo y posiciones reflejan compras/ventas/fills/fees con reglas explícitas del producto; no se generan posiciones desde ACK ni intents; un cancel tras parcial preserva lo ya ejecutado. `unrealized_PnL` necesita marca de mercado point-in-time, o se declara `NOT_AVAILABLE`.

La reconciliación compara, cuando se dispone, eventos/estado de proveedor con log local, proyección de orden, fills y ledger. Debe distinguir `PASS`, `FAIL` e `INCOMPLETE` por falta de prueba primaria. Cualquier divergencia monetaria no explicada impide declarar PASS; no se fuerzan tolerancias para acomodar resultados observados.

### 5.5 Métricas

Conteos segregados por provenance: señales elegibles, `NO_TRADE`, intents, submits, ACK, parciales, fills, reject, cancel, expiradas, `UNKNOWN`, reintentos, deduplicados y fallos de reconciliación. Latencias: signal→intent, submit→ACK y ACK→fill, con reloj/medición identificados. Spread/slippage se calculan solo frente a referencia PIT disponible y comparable. Fees, fill ratio, coste por orden y latencia se reportan con unidades y denominadores. Si no existe evidencia: `NOT_AVAILABLE`, `NOT_PERFORMED` o `INSUFFICIENT_EVIDENCE`, nunca `0` por defecto.

## 6. Estrategia de ejecución y Work Packages

| WP | Trabajo | Evidencia mínima |
|---|---|---|
| `WP-003P-00` | Inventario read-only, mapa runtime, baseline Git/config, verificación hashes 003O y viabilidad del adapter paper. | `BASELINE.md`, `runtime_authority_map.md`, inventario de rutas/flags; decisión paper disponible o bloqueado. |
| `WP-003P-01` | Instrumentación end-to-end, contratos, transiciones, persistencia e idempotencia conectadas al runtime existente. | Esquemas, pruebas de alcanzabilidad y traces correlacionadas. |
| `WP-003P-02` | Tests unit/contract/integration/runtime y controles adversariales; codificación de fallos exactos. | Tests con exit codes, `NEGATIVE_CONTROLS.json`, matriz mutación→detector. |
| `WP-003P-03` | Rehearsal offline con datos congelados, sin red/órdenes externas, repetido dos veces. | `EXECUTION_TRACE.jsonl`, `RECONCILIATION.json`, digests y `RUN_REPORT`; `OFFLINE_SIMULATED`. |
| `WP-003P-04` | Observación paper **solo si** proveedor, endpoint, cuenta y credenciales ya están autorizados y configurados. | Eventos primarios de entorno paper, correlación, validación de fills y reconciliación; o `BLOCKED_NOT_CONFIGURED`. |
| `WP-003P-05` | Verificador separado, controles de falsificación, reproducción desde checkout limpio, sello y cierre. | `INDEPENDENCE_AUDIT.md`, `FINAL_REPORT.md`, `SHA256SUMS.txt` verificado. |

**Orden:** congelar `PROTOCOL.json` y reglas de éxito **antes** del primer ensayo significativo/comparación. Codex puede ejecutar WP00–03 y WP05 sin WP04 si no hay infraestructura autorizada; no solicitar credenciales nuevas para maquillar resultados. No detenerse tras redactar documentos cuando existe ruta técnica offline verificable.

## 7. Tests adversariales y oráculos exactos

| Caso inyectado | Clase esperada o resultado obligatorio |
|---|---|
| ACK sin fill | Sin incremento de posición; `ACK_NOT_FILL` o aserción equivalente. |
| Fill parcial → total | Estado, cantidad y fees acumulados correctos. |
| Cancelación tras parcial | Remanente cancelado; fills previos preservados. |
| Rechazo de orden | Cero fills y cero contabilización. |
| Duplicado del mismo fill | `DUPLICATE_FILL`; sin doble contabilización. |
| Retry tras timeout/restart | Misma identidad; `UNKNOWN` hasta reconciliar; cero nuevos submits no autorizados. |
| Evento cronológicamente fuera de orden | `OUT_OF_ORDER_EVENT` y reparación auditable o cuarentena. |
| Fill sin ACK | `FILL_WITHOUT_ACK`; consulta a fuente primaria, sin ACK inventado. |
| Fee/precio/cantidad alterados | `LEDGER_MISMATCH` o `DATA_INTEGRITY_FAIL`. |
| Provenance alterada o evento reemplazado | `PROVENANCE_MISMATCH` / `INTEGRITY_FAIL`, hard fail. |
| Slippage sin cotización PIT | `NOT_AVAILABLE`, nunca 0 calculado. |
| Provider caído | `UNKNOWN` / `INCOMPLETE`, sin éxito supuesto. |
| Barra stale, duplicada, timestamp futuro, HTF futuro | Gate de datos deniega orden; PIT/freshness detectable. |
| Cambio hacia LIVE o adapter live | `LIVE_MODE_FORBIDDEN`; 0 órdenes reales. |
| Risk no aprobado, notional/exposición fuera de límites | `RISK_GATE_VIOLATION`; sin submit. |
| Diferencia proveedor-estado-ledger | `RECONCILIATION_FAIL`; estado no certificado. |
| Señal con `NO_TRADE` | 0 intents enviables y decisión trazada. |

Cada control negativo debe cambiar **un** defecto de un caso originalmente válido y exigir detección **de esa clase concreta**, no simplemente cualquier excepción. Reportar `detected`, `expected_class`, `observed_class`, `unexpected_differences` y veredicto. Ejecutar los gates relevantes sobre el commit final; documentar errores preexistentes sin silenciarlos como si fueran green global.

## 8. Condiciones de certificación y máquina de veredictos

Evaluar por separado:

| Dimensión | Condición de `PASS` | En caso contrario |
|---|---|---|
| `IMPLEMENTATION` | Código conectado a entrypoint realmente alcanzable, contratos y commits propios. | `INCOMPLETE`/`FAIL`. |
| `TESTS` | Suites pertinentes y controles adversariales superados en commit registrado. | `FAIL`/`INCOMPLETE`; no esconder fallos globales. |
| `OFFLINE_RUNTIME_VALIDATION` | Ensayo offline realmente ejecutado, determinista, eventos simulados etiquetados y ledger reconciliado. | `NOT_PERFORMED`/`FAIL`. |
| `PAPER_VALIDATION` | Proveedor paper autenticado como tal, eventos originales observados, al menos un fill paper verificable del ciclo bajo evaluación, causalidad y reconciliación aceptadas. | `BLOCKED_NOT_CONFIGURED`, `INCOMPLETE_FILL_OBSERVATION`, `INCOMPLETE` o `FAIL`. |
| `INDEPENDENT_VERIFICATION` | Re-derivación con implementación/programa distinto y prueba de controles; registrar `program_independence` y `organizational_independence` por separado. | `PARTIAL` cuando mismo autor/agente o falta evidencia. |
| `FALSE_SUCCESS` | 0 claims no respaldados; controles contra falsos verdes pasan. | `FAIL`. |
| `LIVE` | `DISABLED`, `live_orders=0` y controles contra acceso live. | `FAIL` y parada inmediata. |

`FINAL_STATUS=PASS` de la fase solo puede considerarse si las dimensiones exigidas por el protocolo congelado son PASS, incluida `PAPER_VALIDATION` cuando el objetivo es certificar paper observado. En ausencia de fill paper, el máximo es `TECHNICAL_PASS / PAPER_INCOMPLETE` con `FINAL_STATUS=PARTIAL` o `BLOCKED` según causa. Un `OFFLINE_RUNTIME_VALIDATION=PASS` **jamás** se promueve automáticamente a `PAPER_VALIDATION=PASS`.

La independencia entre *programas* de un mismo autor no constituye independencia organizativa. `003P` no corrige retrospectivamente la falta de cobertura ni la independencia de `003O`.

## 9. Riesgos, seguridad, fallos y rollback

- **Orden duplicada por timeout:** clave persistente; consultar fuente primaria antes de reintentar; si no es posible, `UNKNOWN` y bloqueo.
- **Eventual consistency del proveedor:** conservar hechos y timestamps, conciliar contra snapshot con política de espera declarada de antemano; nunca tomar ausencia instantánea por rechazo definitivo.
- **Eventos irreconciliables:** congelar nuevos envíos paper afectados y retener evidencia bruta; no reajustar ledger silenciosamente.
- **Fugas de datos:** redactar claves, tokens, identificadores de cuenta, URLs firmadas y payloads sensibles; sellar solo artefactos sanitizados.
- **Riesgo de cambio colateral:** inspeccionar git dirty y scopes antes/después; no `git add .`, `reset --hard` ni tocar trabajo ajeno; si hay conflictos, publicar diff propuesto aislado.
- **Rollback:** desactivar instrumentación con mecanismo reversible existente si lo hay, detener nuevas órdenes paper, preservar eventos y ledger inmutable, y volver al entrypoint anterior tras verificar compatibilidad. No borrar hechos ya observados.
- **Promoción y capital:** este RFC no autoriza trading real, cambios de límites, credenciales nuevas ni costes relevantes. Esas decisiones requieren autorización explícita separada.

## 10. Entregables, evidencia y cierre

Destino sugerido, sujeto al naming canónico real: `reports/ai-bots/EXP-003P-PAPER-EXECUTION-001/`.

`BASELINE.md`; `runtime_authority_map.md`; `RFC-EXP-003P-PAPER-EXECUTION.md`; `WORK_PACKAGES.md`; `PROTOCOL.json` y explicación del preregistro; `ORDER_EVENT_SCHEMA.md/json`; `STATE_MACHINE.md`; `EXECUTION_TRACE.jsonl`; `ORDER_LIFECYCLE.csv/json`; `RECONCILIATION.json`; `METRICS.json`; `NEGATIVE_CONTROLS.json`; `INDEPENDENCE_AUDIT.md`; `RUN_REPORT.md`; `RUN_REPORT.json`; `FINAL_REPORT.md`; `SHA256SUMS.txt`.

Los archivos no producidos se registran explícitamente como `NOT_PERFORMED` o `BLOCKED`, sin rellenarlos con simulaciones atribuidas a venue. Cada run report incluye `run_id`, commit, versión/config hash, entorno, rutas realmente ejecutadas, número de órdenes y fills **por provenance**, tests, errores, métricas, resultado, fuentes de evidencia y decisiones.

El informe final usa: `PHASE / COMMITS / IMPLEMENTED / TESTS / RUNTIME_VALIDATION / PAPER_VALIDATION / FALSE_SUCCESS / DEFECTS / BLOCKERS / EVIDENCE / ARCHITECTURE_STATUS / RFC_STATUS / NEXT_PHASE`. Añadir `CLAIM / SOURCE / EVIDENCE / DECISION`, tabla de trazabilidad `REQ → ACC → RFC → WP → IMP → TEST → EXEC → EVID` y declaración de límites.

**No declarar `CERTIFIED`, `READY` o `PRODUCTION_READY`** hasta demostrar los requisitos correspondientes con evidencia independiente. El cierre de 003P no implica edge económico ni autorización de producción.

## 11. Secuencia posterior (condicional a evidencia)

- Si 003P termina con `OFFLINE_RUNTIME_VALIDATION=PASS` y `PAPER_VALIDATION=BLOCKED`, resolver exclusivamente el bloqueo de infraestructura/autorización paper, sin renombrar el ensayo offline como paper.
- Si hay paper observado y reconciliado, iniciar una fase distinta de **observación prospectiva paper**, midiendo costes, slippage, calidad de fills, estabilidad y resultados sobre una ventana preregistrada. Esto seguiría sin probar por sí solo rentabilidad futura.
- Abrir un trabajo independiente para cubrir las dos celdas 4h de 003O con ventana real suficiente y autor distinto, sin resellar indebidamente el experimento cerrado ni abrir holdout.

**Decisión RFC:** `PROPOSED — ADOPT_P0` para la instrumentación y verificación del ciclo paper existente; `DEFER` para cualquier integración nueva de venue o infraestructura no disponible; `REJECT` para ejecución live, cambios de estrategia/edge o certificación basada únicamente en simulaciones.
