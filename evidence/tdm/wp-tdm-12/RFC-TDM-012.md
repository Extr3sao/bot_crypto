# RFC-TDM-012 — Independent Closure & Alpha Candidate Triage

**Proyecto:** Trading Agentic Portable  
**Fecha:** 2026-10-25  
**Versión:** 1.0  
**Estado:** `PROPOSED` — pendiente de implementación y ejecución  
**Prioridad:** P0 (gobernanza de evidencias + recuperación de foco económico)  
**WPs:** `WP-TDM-12A`, `WP-TDM-12B`  
**Entorno autorizado:** análisis offline / backtest retrospectivo reproducible, sin órdenes de mercado  
**Principios:** `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION`; `FALSE_SUCCESS = 0`; `BUILDER != VERIFIER`.

## 1. CONTEXTO Y BASELINE

El reporte recibido de `WP-TDM-11` fija estos **resultados reportados, pendientes de comprobación directa**:

- Veredicto: `NO_GO_ALPHA` para la hipótesis SHORT-bajista. La ventana confirmatoria **no** se abrió.
- Revisión retrospectiva de una ventana DEV anterior a la selección: **115 operaciones**, edge bruto **−12,58 bps** e IC95 reportado **[−24,27, −0,39]**; edge neto a coste modelado de **23,79 bps**: **−36,37 bps**, IC95 **[−48,06, −24,18]**.
- Por activo, neto negativo: BTC **−31,98**, ETH **−43,07**, SOL **−34,63 bps**.
- La misma regla presentó **+13,29 bps brutos** en la ventana HOLD donde fue seleccionada. Esa ventana no es validación fuera de muestra.
- La premisa del RFC anterior «5 de 6 mejores cubetas SHORT en bajista» fue refutada como **3 de 6**; `regime_table.csv` carecía de columna de dirección.
- Control de fuga temporal: incorporar 12 barras futuras en la etiqueta de régimen cambia el bruto de **−12,58** a **+17,05 bps** (diferencia artificial de **29,63 bps**).
- Verificación reportada: 12/12 controles, 11/11 controles adversariales; manifiestos y hashes corregidos en `504256ec` de `evidence/tdm11`.
- Límite abierto: `INDEPENDENCE_NOT_DEMONSTRATED`, porque constructor y verificador fueron el mismo agente; financiación de perp SHORT no acreditada, maker fill asumido p=0,5 y spread estimado a 1 bp.
- Referencia de evidencia reportada: `evidence/tdm/wp-tdm-11/`. Estado base reportado del checkout compartido: `e67194e7` con 17 modificaciones preexistentes que **no deben tocarse**.

**Regla de interpretación:** `NO_GO_ALPHA` es válido como decisión de no promoción con la evidencia disponible; el informe no prueba por sí solo independencia de autor ni certifica todos los intervalos estadísticos. No tratar una evaluación retrospectiva, aunque sea temporalmente anterior, como evaluación prospectiva o confirmatoria. No trasladar el mínimo preregistrado de 36 operaciones de TDM-11 a otras estrategias.

## 2. PROBLEMA

La plataforma está produciendo resultados de ingeniería verificables, pero no ha acreditado todavía un candidato Alpha con ventaja **neta, estable y no contaminada**. Persisten dos riesgos:

1. **Cierre incompleto de gobernanza:** integridad de hashes y reimplementación estadística no equivalen a independencia de autor.
2. **Exploración indefinida:** crear nuevas estrategias o RFCs sin inventariar y descartar sistemáticamente lo ya ejecutable impide medir progreso hacia rentabilidad.

## 3. OBJETIVOS Y NO OBJETIVOS

### Objetivos

- Revisar el paquete TDM-11 con separación real entre constructor y revisor **cuando exista un revisor efectivamente distinto**; si no, conservar explícitamente `INDEPENDENCE_NOT_DEMONSTRATED`.
- Registrar la hipótesis SHORT-bajista como `REJECTED_ALPHA / NO_GO_ALPHA`, preservando muestras, errores y evidencias.
- Construir un **inventario de estrategias efectivamente alcanzables desde el runtime real**, separado de implementaciones de test, investigación, experimental, legacy y código huérfano.
- Revaluar de modo retrospectivo, comparable y reproducible candidatos ya existentes, **sin retocar parámetros**.
- Emitir como máximo **un candidato** a **prerregistro futuro**, o `NO_ELIGIBLE_CANDIDATE`. Ninguna selección implica Alpha validada.
- Publicar una recomendación económica accionable: qué se conserva, qué se descarta y cuál es la única prueba justificable siguiente.

### Fuera de alcance

- Diseñar agentes, añadir frameworks, inventar señales, crear familias estratégicas, ajustar umbrales, refit, cherry-picking o entrenar modelos.
- Abrir o simular una muestra confirmatoria futura que aún no esté disponible.
- Enviar órdenes `PAPER`, `SHADOW`, `CANARY` o `LIVE`; cambiar tamaños, leverage, límites de riesgo, claves, permisos o configuraciones de producción.
- Reescribir el motor de costes/riesgo/ejecución o modificar `src/`, `tests/` o ficheros existentes del checkout compartido.
- Declarar `CERTIFIED`, `READY`, `PRODUCTION_READY` o prometer rentabilidad.

## 4. CONTRATOS Y ARQUITECTURA

```text
TDM-11 evidence + repo HEAD + runtime entrypoints + datasets
           |
           v
A. Evidencia / provenance audit ----> INDEPENDENT_REVIEW
           |                          | 
           |                          +--> VERIFIED / PARTIAL / FAILED
           |                          +--> INDEPENDENCE_DEMONSTRATED / NOT_DEMONSTRATED
           v
B. Runtime authority inventory --> Candidate registry
           |
           v
C. Point-in-time & cost eligibility gates
           |
           v
D. Frozen retrospective comparison (same inputs/costs/constraints where comparable)
           |
           v
E. Decision register --> [ONE PREREG_CANDIDATE | NO_ELIGIBLE_CANDIDATE]
           |
           v
Independent evidence check + RUN_REPORT.md / RUN_REPORT.json
```

**Restricción:** los agentes pueden analizar, criticar y recomendar; el cálculo de PnL, costes, temporalidad, risk gates y decisiones de elegibilidad verificables debe ser determinista. `NO_TRADE` y `NO_ELIGIBLE_CANDIDATE` son salidas válidas.

## 5. WP-TDM-12A — REVISIÓN Y CIERRE INDEPENDIENTE

**A1. Proteger estado.** Resolver HEAD, rama, árbol sucio, worktrees y hashes reales al inicio; trabajar con lectura o worktree aislado. No asumir que el checkout sigue en `e67194e7` ni que `504256ec` sea el HEAD actual. Nunca limpiar/revertir las 17 modificaciones heredadas.

**A2. Comprobar publicación.** Abrir `RUN_REPORT.json`, `PREREGISTRATION.md`, `DATASET_PROVENANCE.json`, `GOVERNANCE_RECONCILIATION.md`, `COST_MODEL_AUDIT.md`, `RETROSPECTIVE_LEDGER.csv` y `INDEPENDENT_VERIFICATION.md`. Resolver desde el árbol versionado; contrastar hashes con blobs y detectar manifestaciones ausentes o hashes circulares. Registrar faltantes como ERROR, no PASS.

**A3. Reproducir de forma independiente.** Si es viable, usar otro revisor y una implementación estadística separada para recalcular ledger desde datos fuente, conteo por activo, bruto, neto, diferencia HOLD/DEV, premisa 3/6 y look-ahead. El revisor no puede basarse únicamente en invocar los siete scripts originales; puede ejecutarlos como contraste adicional. Si no existe un actor independiente, registrar `INDEPENDENCE_NOT_DEMONSTRATED`; jamás cambiar la etiqueta usando solamente un nuevo prompt al mismo autor.

**A4. Estimar la incertidumbre adecuadamente.** Verificar si las 115 operaciones son aproximadamente independientes. Examinar operaciones solapadas, dependencia temporal, concentración por activo y períodos. Usar intervalos robustos a dependencia (p. ej. bootstrap por bloques de sesiones o días, con diseño declarado) y sensibilidad al tamaño del bloque; no afirmar que un IC ingenuo confirma rechazo estadístico si la dependencia lo invalida. Esto **no** habilita la estrategia: el gate conservador sigue siendo `NO_GO_ALPHA`.

**A5. Decisión.** Publicar `TDM11_CLOSURE_DECISION.json` con campos: `alpha_status=REJECTED_ALPHA`, `previous_verdict=NO_GO_ALPHA`, `integrity_status`, `reproduction_status`, `independence_status`, `statistical_limitations`, `cost_limitations`, `can_promote=false`, `evidence_refs`. Si se detecta un error que altere materialmente una afirmación, abrir hallazgo contradictorio; no modificar retroactivamente TDM-11 ni convertirlo en GO.

**Salidas posibles:** `REVIEW_VERIFIED`, `REVIEW_PARTIAL`, `REVIEW_FAILED`; independencia separada como `INDEPENDENCE_DEMONSTRATED` / `INDEPENDENCE_NOT_DEMONSTRATED`. No simular un certificado de independencia.

## 6. WP-TDM-12B — INVENTARIO Y CRIBADO DE CANDIDATOS

**B1. Identificar realidad runtime.** Localizar entrypoints reales, registro/router de estrategias, market data, validación PIT, motor de costes, ejecución offline y scripts de campañas. Clasificar cada estrategia:
`RUNTIME_AUTHORITATIVE / RUNTIME_REACHABLE / TEST_ONLY / RESEARCH_ONLY / EXPERIMENTAL / LEGACY / ORPHAN / DEAD_CODE`.

**B2. Registro reproducible.** Crear `CANDIDATE_REGISTRY.csv` y `.json`, una fila por candidato existente con:
`candidate_id`, `strategy_id`, `family`, `runtime_class`, `entrypoint`, `source_commit`, `assets`, `timeframes`, `regimes`, `parameter_hash`, `datasets`, `data_fingerprint`, `selection_history`, `cost_model`, `cost_verification_status`, `sample_coverage`, `trades_by_day`, `edge_gross_bps`, `edge_net_bps`, `drawdown`, `robustness`, `lookahead_gate`, `stale_data_gate`, `promotion_state`, `reason`, `evidence_refs`.

**B3. Gobernanza de periodos.** Crear `DATA_WINDOW_REGISTRY.json`: nombre de ventana, rango UTC, hash, si fue utilizada para construir/seleccionar/afinar una regla, activos, timeframe, estado de reutilización y etiqueta `DEVELOPMENT / SELECTION_EXPOSED / RETROSPECTIVE_REVIEW / FUTURE_CONFIRMATORY_SEALED`. Una ventana examinada después de comparar candidatos deja de ser confirmatoria. No usar HOLD ni DEV de TDM-11 como prueba confirmatoria nueva. Proteger `data_time <= decision_time` en cada decisión.

**B4. Filtrar sin reoptimizar.** Aplicar a cada candidato requisitos de ejecutabilidad real, integridad y frescura de datos, ausencia de fuga temporal, parámetros congelados, evidencia de ejecución, costes coherentes, ausencia de fallos silenciados y muestra suficiente según un diseño de potencia **específico del candidato**. Los que fallen salen como `REJECTED`, `DEFERRED` o `INSUFFICIENT_EVIDENCE`, con motivo explícito.

**B5. Comparación justa.** Solo si el runner actual permite ejecución offline/reproducible, evaluar los candidatos elegibles con ventanas comparables y restricciones comunes donde proceda; declarar cualquier asimetría de activos, periodos, ejecución o costes. Desglosar gross/net, BTC/ETH/SOL u otros activos presentes, concentración temporal, costes, costes no verificados, drawdown, sensibilidad por régimen y consistencia por subperiodos. Ajustar el nivel de confianza por selección múltiple / data snooping, o, si no es posible, etiquetar el ranking como puramente exploratorio. No usar resultado del propio conjunto de selección como prueba de generalización.

**B6. Dos pistas, sin mezclar objetivos.** `ACTIVE`: objetivo operativo de referencia de **≥3 operaciones ejecutadas por día, 7 días por semana** para el portfolio multi-activo, sin forzar operaciones ni comprometer rentabilidad o risk gates. Medir distribución diaria y días sin operaciones; no declarar elegibilidad ACTIVE solo por una media de ≥3. `QUALITY`: módulo de menor frecuencia separado, evaluado por net edge/robustez, sin exigir frecuencia ACTIVE. Ningún ajuste automático para alcanzar la cifra.

**B7. Selección limitada.** Ordenar por elegibilidad y evidencia verificable, no por el mejor PnL aislado. Emitir `PREREG_CANDIDATE` para **como máximo uno** (identificando pista ACTIVE o QUALITY) o `NO_ELIGIBLE_CANDIDATE`. Exigir que toda candidatura futura especifique hipótesis falsable, parameters/commit congelados, costes, periodo confirmatorio futuro todavía no observado, controles adversariales, potencia/tamaño de muestra justificados, umbrales de GO/NO_GO y stop conditions **antes** de abrir la ventana. Si se necesita otra fase para construir ese prerregistro, no abrirla ahora.

## 7. PRUEBAS Y CONTROLES OBLIGATORIOS

- **T-01** Preflight: branch/commit/worktree/dirty files documentados; archivos ajenos intactos.
- **T-02** Provenance: hashes de entregables y fuentes verificables contra objetos versionados; ningún hash huérfano.
- **T-03** Independencia: identidad/aislamiento de revisor documentados; si falta, estado de independencia no demostrado.
- **T-04** Ledger: rederivación reproducible; discrepancias nunca se silencian ni se redondean para PASS.
- **T-05** Regime: dirección SHORT demostrada por campo/datos reales, sin inferirla por nombre de cubeta.
- **T-06** Temporalidad: si el contexto de decisión usa datos futuros, el candidato es inelegible. Incluir prueba adversarial de las 12 barras futuras.
- **T-07** Estadística: documentar dependencia, supuestos de IC y sensibilidad; prohibido reportar potencia sin fundamento.
- **T-08** Costes: maker/taker, spread, slippage, funding/borrow (si aplican) desglosados como observado, modelado o desconocido; sin valor inventado.
- **T-09** Inventario: cada candidato seleccionado corresponde a entrypoint real; `TEST_ONLY`/`RESEARCH_ONLY` no entra en ranking ejecutable.
- **T-10** Sesgo de selección: intervalos que participaron en discovery no se reclasifican como OOS limpio; registrar número de comparaciones.
- **T-11** Consistencia: mismos inputs y versión => artefactos deterministas; incluir hashes de salidas.
- **T-12** Sin acciones: órdenes `PAPER/LIVE=0`, credenciales/permiso de trading no utilizados, cero cambios a risk/strategy/runtime.
- **T-13** Fallo visible: ausencia de dataset, comando, suite o control => `BLOCKED` o `INCOMPLETE`, nunca PASS.
- **T-14** Reconstrucción: decisiones trazables `CLAIM + SOURCE + EVIDENCE + DECISION`.

Ejecutar tests relevantes efectivamente presentes en el repositorio y validar `TEST_TARGET == RUNTIME_TARGET`. No imponer comandos ni rutas supuestos; descubrir y registrar los reales. Si no se ejecuta la suite completa, consignar alcance y motivo, sin afirmar cobertura completa.

## 8. EVIDENCIAS Y ENTREGABLES

Publicar en una ruta versionable, preferentemente `evidence/tdm/wp-tdm-12/` (confirmar que no se ignora en Git):

1. `RFC-TDM-012.md` (especificación aprobada para la ejecución técnica).
2. `BASELINE_AND_SCOPE.md` (estado Git, worktree, rutas y límites).
3. `INDEPENDENT_REVIEW.md` y `TDM11_CLOSURE_DECISION.json`.
4. `RUNTIME_AUTHORITY_MAP.md`.
5. `CANDIDATE_REGISTRY.csv` y `CANDIDATE_REGISTRY.json`.
6. `DATA_WINDOW_REGISTRY.json`.
7. `COST_AND_BIAS_AUDIT.md`.
8. `RETROSPECTIVE_TRIAGE_REPORT.md`.
9. `DECISION_REGISTER.json` (incluso si no hay candidato).
10. `RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md`.

`RUN_REPORT.json` debe contener al menos `run_id`, `commit`, `environment`, `inputs`, `datasets/hashes`, `agents/reviewer`, `strategies`, `tests`, `decisions`, `errors`, `metrics`, `result`, `evidence`, `false_success`, `independence_status`, `paper_orders=0`, `live_orders=0`. El informe final debe separar **evidencia comprobada** de **declaraciones heredadas**, declarar faltantes y marcar `NOT_RUN` para gates no ejecutados. Hashes comparados con los blobs realmente versionados, tras el commit, no solo con el directorio de trabajo.

## 9. CRITERIOS DE ACEPTACIÓN

- **ACC-01:** No se altera el checkout compartido ni archivos previos; cero órdenes y cero modificaciones de estrategias, riesgo o ejecución.
- **ACC-02:** Hipótesis TDM-11 marcada `NO_GO_ALPHA / REJECTED_ALPHA`; no hay reapertura silenciosa ni nueva confirmación.
- **ACC-03:** Integridad y reproducibilidad revisadas; independencia de autor documentada honestamente. `INDEPENDENCE_NOT_DEMONSTRATED` impide `CERTIFIED`, pero no obliga a promover ni retestar Alpha.
- **ACC-04:** Catálogo completo *dentro del alcance de entrypoints investigados*, con exclusiones y cobertura explícitas. No afirmar inventario exhaustivo si faltan componentes.
- **ACC-05:** Reglas de point-in-time, coste y sesgo de selección verificadas; anomalías producen `BLOCKED` / `INCOMPLETE` / `REJECTED` según corresponda.
- **ACC-06:** Salida de cribado: exactamente un candidato máximo `PREREG_CANDIDATE` o `NO_ELIGIBLE_CANDIDATE`, sin considerarlo validado.
- **ACC-07:** Informes versionados, hashes íntegros, tests con alcance trazable y `FALSE_SUCCESS=0` **dentro de lo comprobado**, sin atribuirlo al sistema completo.
- **ACC-08:** Un siguiente paso claro basado en evidencia, no en añadir capacidades por defecto.

**DO NOT PASS** si: falta evidencia sustantiva, hay error oculto, se prueba código inalcanzable, se usa futuro en features, se declara independencia no demostrada, se altera una muestra confirmatoria o el reporte implica rentabilidad sin validación. No aceptar un PASS fabricado a partir de artefactos formales.

## 10. RIESGOS, ROLLBACK Y SEGURIDAD

- **Riesgo estadístico:** operaciones serialmente dependientes, variación por régimen y múltiples pruebas pueden crear falsas señales de Alpha. Mitigar con análisis de dependencia y etiqueta exploratoria.
- **Riesgo económico:** costes no observados (funding, slippage, maker fill) invalidan net edges optimistas. Mitigar con bandas de sensibilidad y estatus `UNVERIFIED_COST`.
- **Riesgo de independencia:** mismo agente / misma historia no alcanza separación real. Mitigar registrándolo como limitación verificable.
- **Riesgo de contaminación:** ver datos que luego se llaman «confirmatorios». Mitigar con `DATA_WINDOW_REGISTRY` append-only y preregistro antes de uso.
- **Riesgo de alcance:** convertir el WP en rediseño perpetuo. Mitigar limitando entregables, una sola selección y cero cambios funcionales.
- **Rollback:** si se generan scripts auxiliares, mantenerlos solo en worktree aislado; revertir exclusivamente los artefactos nuevos de este RFC si falla, preservando evidencias de fallo. No borrar logs, experimentos existentes ni modificaciones ajenas.

## 11. DECISIÓN Y SIGUIENTE GATE

El RFC autoriza **únicamente investigación, verificación y cribado retrospectivo seguro**, no la promoción ni implementación de nuevas estrategias. Siguiente gate:

- Si `NO_ELIGIBLE_CANDIDATE`: detener incorporación de estrategias y publicar obstáculos medibles (datos, costes, validez temporal, runtime o edge neto). Un nuevo RFC necesitará hipótesis específica respaldada por esos obstáculos.
- Si `PREREG_CANDIDATE`: preparar en otro WP su preregistro congelado y verificación independiente, y esperar datos futuros suficientes antes de plantear GO/NO_GO de Alpha. Nada de paper/live automático.

## 12. PROMPT DE EJECUCIÓN PARA CODEX

> Implementa **RFC-TDM-012 v1.0** en Trading Agentic Portable, con máxima autonomía técnica **dentro del alcance offline**. Primero descubre y registra runtime real y estado Git, luego ejecuta `WP-TDM-12A` y `WP-TDM-12B`. No supongas rutas o comandos no encontrados. Trabaja en worktree aislado; protege checkout compartido y archivos ajenos; no toques estrategias, parámetros, `src/`, `tests/`, riesgo, costes productivos, ejecución ni credenciales; no uses órdenes PAPER/LIVE ni una ventana confirmatoria. Revisa las evidencias TDM-11 de `504256ec`, rederiva cálculos cuando haya datos y declara `INDEPENDENCE_NOT_DEMONSTRATED` si no hay autor/verificador realmente separados. Identifica solo candidatos ya existentes y runtime-reachables, congela sus parámetros, registra contaminación de ventanas, ejecuta comparaciones retrospectivas reproducibles si existen entrypoints seguros, evalúa costes y dependencia estadística. Produce como máximo un `PREREG_CANDIDATE` o `NO_ELIGIBLE_CANDIDATE`, sin reclamar Alpha validada. Publica todos los entregables y `RUN_REPORT.md/.json` más `FINAL_REPORT.md` con hashes verificados **contra el commit final**, pruebas realizadas/no realizadas, errores, riesgos y siguiente gate. Si algo impide demostrar un control, informa `BLOCKED` o `INCOMPLETE`, nunca falso PASS. No inicies otro WP.
