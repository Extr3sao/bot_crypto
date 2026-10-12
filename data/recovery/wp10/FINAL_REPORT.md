# WP-10 — INFORME FINAL
## Economic Edge Recovery & Execution Cost Discovery

> Documento de cierre de la lane WP-10. Todas las cifras de este informe provienen de los
> artefactos versionados en `data/recovery/wp10/` y fueron re-derivadas por un verificador
> distinto del constructor (`INDEPENDENT_VERIFICATION.json`: 53 comprobaciones, 0 fallidas,
> 12 controles negativos, 0 no detectados, `false_success = 0`).
>
> Clase de resultado: **RESEARCH_RESULT** (medición de coste). No es `BACKTEST_RESULT`, ni
> `REPLAY_RESULT`, ni `PAPER_RESULT`, ni `LIVE_RESULT`. No se declara `PROFITABILITY_VERIFIED`.
> Trading real: **DESACTIVADO**. Trades autorizados: **0**. PAPER_PROMOTION: **NOT_AUTHORIZED**.

---

## 1. Resumen ejecutivo

La pregunta de WP-10 era económica: *¿existe una oportunidad explotable después de todos los
costes?* La respuesta que la evidencia sostiene es **no con el registro actual, y el motivo no
es el que el propio modelo de costes hacía creer**.

1. Las seis cifras publicadas del registro (24 estrategias, 0 admitidas, 17 `NO_GROSS_EDGE`,
   7 `COST_KILLED`, mejor ventaja bruta 8.912 bps, planicie de admisión 23.3536 bps) **se
   reproducen desde fuentes primarias**, con 3 discrepancias declaradas y 16 métricas que el
   registro sencillamente no contiene (entre ellas el spread y el drawdown de cada celda).
2. De los 23.3536 bps de la planicie, **20.0 bps son fees de exchange KNOWN** (85.64 %) y solo
   3.3536 bps son términos `ESTIMATED`. E-1 midió esos términos sobre el libro forward
   capturado: el round trip medido es **0.0247 bps** de mediana en cuatro libros
   (BTC/ETH, spot y perp) con una cola peor de **4.586 bps**.
3. La planicie, por tanto, es conservadora en el centro y **no** lo es en la cola. Pero la
   conclusión económica no depende de eso: **los 20 bps de fees KNOWN, por sí solos, ya superan
   la mejor ventaja bruta del registro (8.912 bps)**. Ninguna mejora de ejecución disponible en
   esta captura admite ninguna de las 24 celdas.
4. La razón real por la que fallan las 24 estrategias es doble y distinta de la que sugiere la
   etiqueta `COST_KILLED`: **17 celdas no tienen ventaja bruta positiva en absoluto** (no hay
   nada que los costes puedan comerse), y **las 7 que sí la tienen la tienen demasiado pequeña**
   (máximo 8.912 bps) para superar un suelo de fees que ninguna condición de mercado puede
   bajar. Añadido a eso, la mejor celda se cotiza a partir de 196 operaciones con un intervalo
   del 95 % de **±12.01 bps**, es decir su ventaja no está resuelta.
5. **No hay hipótesis nueva con ventaja económica suficientemente respaldada** para merecer una
   campaña. Lo que hay es: (a) una decisión de nivel de fees que es de gobernanza y de cuenta,
   no de medición; (b) una evidencia de ejecución (orden límite / maker) que esta captura **no
   puede** producir, declarada `INSUFFICIENT_EVIDENCE`; y (c) una familia, `mean_reversion`, que
   es la única cuya mejor celda tiene un intervalo que excluye el cero y que por tanto merece
   investigación adicional — 17.88 bps por debajo de la planicie congelada.

---

## 2. Estado del WP-9 (fase 0)

- **Commit de la lane**: `90ed615b1b2514682bbf9a85834fdd81c45f0774` — *"Close WP-9 on its own
  files: the disk defect, the rehearsal, and the register."* (2026-10-12T00:57:50+02:00), con
  **73 archivos propios**. No incluye `data/st6/`, `evidence/real_decisions/` ni los informes
  raíz de otras lanes, que permanecen intactos.
- **Control de secretos**: `PASS` sobre los 73 archivos, con canario detectado (7 patrones:
  clave privada, clave tipo OpenAI, AWS, forma de clave Binance, password genérica, bearer,
  contenido de `.env`). Cero coincidencias.
- **Ensayo en checkout limpio** (worktree del commit, 9 pasos). Reproducen exactamente:
  `economics`, la evidencia del launcher (`preflight-refusal` exit 4, `preflight-refusal-default`
  exit 4, `preflight-autoscale` exit 0) y el test focalizado
  `tests/unit/research/test_wp9_disk_budget.py`. **No** reproducen desde el commit:
  `disk-audit` (exit 2), `readiness` (exit 1) y `verifier` (exit 1), y
  `WP9_ACTIVE_ECONOMIC_BLOCKERS.json` se regenera con digest distinto
  (`78632b74e3702f16` → `2522a22f3a88e819`).
- **Dictamen honesto**: `PARTIAL/FAIL — exit 4`. Es el mismo defecto de clase que WP-8B cerró
  para su propia lane copiando sus inputs a `evidence/inputs/`: **los artefactos de WP-9 son
  funciones de (este commit, inputs de campaña no versionados)**. El cierre queda *acotado*, no
  retirado: el ámbito y los secretos pasan, la evidencia del launcher y los tests reproducen, y
  los tres artefactos que consumen datos de campaña quedan **nombrados como no reproducibles**
  en lugar de reportados como idénticos a sí mismos. No se reescribió ninguna evidencia
  congelada y no se hizo `push`.

---

## 3. Commits

| commit | contenido | estado |
| --- | --- | --- |
| `90ed615` | cierre de WP-9 sobre sus propios archivos (73) | local, sin publicar |
| *(pendiente)* | artefactos y scripts de WP-10 (`scripts/wp10_*.py`, `tests/unit/research/test_wp10_lane.py`, `data/recovery/wp10/**`) | local, sin publicar |

- Rama: `main`. Cola sin publicar medida por el artefacto de bloqueos: **256 commits** en su
  propio head (`5348fcd`), **257** en el momento de la verificación. No se ha publicado nada y
  no se ha usado `force-push`.

---

## 4. Tests ejecutados

| suite | resultado |
| --- | --- |
| `tests/unit/research/test_wp10_lane.py` (nueva, 13 casos) | **13 passed** |
| `tests/unit/research/test_wp10_lane.py` + `test_wp9_disk_budget.py` + `test_active_recovery_wp.py` | **56 passed** |
| `test_cost_barrier_adversarial.py`, `test_cost_barrier_gate.py`, `test_cost_barrier_ci_parity.py`, `test_recovery_determinism.py`, `test_recovery_ci_parity.py` | **100 passed** (129 s), inamovible |
| paso `focused-tests` dentro del ensayo de checkout limpio | `PASS` |

Los tests nuevos no comprueban la forma del código: comprueban que **la decisión sea falsable**
(el mismo código debe admitir una celda que realmente supere la planicie, y no lo hace con la
real), que **una planicie manipulada haga fallar la construcción**, que el verificador **sobreviva
a un segmento truncado** (el defecto real de esta captura, que antes lo mataba), que el
convenio de hash de los pines sea el normalizado a LF, y que el verificador **no importe ningún
constructor**.

---

## 5. Evidencia económica nueva (fase 1)

`WP10_BASELINE_ECONOMIC_AUDIT.json` — reconstruido desde `config/strategy_admission.json`,
`reports/strategy-baseline/TIMEFRAME_AUDIT.json`, `docs/STRATEGY_DISCOVERY_V3_RESULTS.json`,
`data/recovery/ACTIVE_ECONOMIC_AUDIT.json` y `docs/STRATEGY_ADMISSION_CRITERIA.md`:

- Las seis cifras cabecera coinciden con las publicadas (`headline_agreement` todo `true`).
- 3 discrepancias declaradas, todas de redondeo en el ledger (p. ej. `breakout@5m`:
  −0.11 publicado vs −0.084 reconstruido).
- **16 celdas sin spread observado y sin drawdown**: esas dos métricas pedidas por el brief
  **no existen en el registro**. El audit lo declara en lugar de inventarlas.
- Descomposición del coste por celda, recuperada de la fuente primaria: fees ≈ 9.99–10.00 bps
  por operación (dos tramos de 5 bps/lado), slippage implícito 1.276–3.784 bps por operación.
- **Hallazgo estructural**: el *brazo de costes* del backtest que produjo la expectancy neta
  publicada usa **12 bps por round trip** (5 bps/lado de fee + 1 bp/lado de slippage, escenario
  `BASE` de `multi_family_backtest`), mientras que la decisión de admisión se tomó contra
  **23.3536 bps**. Las celdas fueron evaluadas con la mitad de fees con la que después se las
  juzgó. No cambia ningún signo, pero explica por qué la etiqueta `COST_KILLED` no describe la
  causa real del rechazo.
- Stake recuperado de la fuente primaria: 500 US$ (mediana; rango 498.4–500.9), no el stake de
  200 US$ del escenario de la planicie. El gross edge es lineal en el stake, así que la
  diferencia no altera ninguna conclusión; se declara en el artefacto.

---

## 6. Resultados de E-1 (fases 2 y 3)

Ventana sellada `paper-lab-continuous-02`: 2026-09-29T22:59:18 → 2026-09-30T03:08:51
(**4.1593 h**), `CONTROLLED_STOP`, motivo *disk budget*, continuidad `INCOMPLETE_DATA`,
verificación de replay `ok`/determinista sin acceso a red, 411 segmentos y 11 575 244 filas
contadas de forma independiente.

**Fiabilidad de la medición**

- 1 984 checkpoints (496 × 4 libros) **reproducidos** contra el top of book publicado, 0
  discrepancias; el verificador independiente reconstruyó 40 checkpoints por su cuenta: 40/40
  coinciden.
- **0 violaciones de look-ahead** en los 163 658 prints de agresor emparejados con la cita
  vigente más reciente (nunca posterior).
- 20 segmentos con cola truncada (el defecto de captura) **declarados**; el verificador se
  encontró los mismos y se comprobó que están contenidos en los declarados.
- Tres testigos independientes: las features publicadas por el propio colector
  (`spread_bps` en los checkpoints) se desvían de lo medido en ~2×10⁻⁶ relativo.

**Lo que cuesta ejecutar de verdad (200–2 000 US$)**

| libro | round trip mediano | walk más allá del mejor precio |
| --- | ---: | ---: |
| spot/BTCUSDT | 0.001198 bps | 0.0 bps |
| spot/ETHUSDT | 0.037406 bps | 0.0 bps |
| perp/BTCUSDT | 0.011986 bps | 0.0 bps |
| perp/ETHUSDT | 0.037427 bps | 0.0 bps |
| **mediana de los cuatro** | **0.024697 bps** | **0.0 bps** |

Coste **realizado** por takers reales: round trip 0.0657 bps (spot BTC) y 0.4872 bps (spot ETH);
p95 de 2.89 y 4.586 bps; peor checkpoint individual 0.368 bps; latencia de recepción mediana
113 ms (spot agg_trade) y 187 ms (perp book_ticker); funding 0.5985 bps por intervalo de 8 h
(1.796 bps/día si se mantiene posición).

**Dictamen E-1** (`WP10_E1_DECISION.json`, cinco planicies, ninguna admite nada):

| planicie | round trip | admitidas |
| --- | ---: | ---: |
| congelada (`BINANCE_SPOT_STANDARD_TAKER`) | 23.353553 bps | 0 |
| medida (fees + libro observado) | 20.024697 bps | 0 |
| medida en su cola (p95 del peor libro) | 24.586320 bps | 0 |
| brazo del propio backtest | 12.000000 bps | 0 |
| nivel de fees con descuento de token | 15.024697 bps | 0 |

- La planicie **sobreestima el centro** del coste observable (~136×) y **está por debajo de la
  cola** (4.586 bps > 3.3536 bps). Se comporta como una provisión de p95–p99, no como una
  mediana; por eso el artefacto no propone bajar nada.
- Para admitir la mejor celda haría falta un coste por lado de **4.4437 bps**, frente a los
  10 bps publicados (7.5 bps con descuento); y la ventaja bruta tendría que ser **20.0247 bps**,
  **2.247×** la mejor observada.
- **1 de 7** celdas positivas tiene un intervalo que excluye el cero (`mean_reversion@30m`);
  la mejor celda por ventaja bruta (`volatility@30m`, 8.912 bps) tiene ±12.01 bps.

---

## 7. Estado de E-2 (fase 4)

`WP10_E2_PREREGISTRATION.json`: **`SPEC_ONLY`, gate `CLOSED`**. RFC-050 no está registrado ni
autorizado (el registro de RFC no contiene el número 050). Ventana reservada a partir de
2026-10-12T00:00:00Z, partición fijada **antes** de cualquier observación (60 % desarrollo, resto
validación), períodos quemados declarados (W1–W7, el día de paper 2026-09-25, y la ventana
sellada medida por E-1). **No se leyó ninguna ventana de mercado**: no existe el dato forward
para E-2 y no se fabricó ninguno. Se ejecutaron **5 pruebas de contrato** sobre series
sintéticas, incluida la que rechaza una serie con cambio de signo entre desarrollo y validación.

---

## 8. Familias y estrategias: qué merece investigación (fase 5)

| familia | celdas | clasificación | motivo |
| --- | ---: | --- | --- |
| `mean_reversion` | 4 | **RESEARCH_MORE** | su mejor celda (`mean_reversion@30m`) tiene un intervalo que excluye el cero; aun así queda 17.88 bps por debajo de la planicie congelada |
| `trend` | 4 | INSUFFICIENT_EVIDENCE | el intervalo (±4.772 bps) es más ancho que la ventaja (2.206 bps) |
| `volatility` | 4 | INSUFFICIENT_EVIDENCE | el intervalo (±12.010 bps) es más ancho que la ventaja (8.912 bps) |
| `breakout`, `ema_crossover`, `momentum` | 12 | REJECT | ventaja bruta a coste cero no positiva: no hay nada que los costes puedan comerse |

- **0 familias alcanzan `ADOPT_FOR_NEW_EXPERIMENT`**, y no puede alcanzarlo ninguna sin un
  `PROMOTE` en la ventana forward reservada.
- La frecuencia **no** es el cuello de botella: 200.08 operaciones/día en las 24 celdas
  (44.55/día en las positivas) frente al objetivo de 3/día. El objetivo ACTIVE no se cumple
  porque la expectancy neta no existe, no porque falten oportunidades.
- `R6 P2 QUALITY` se mantiene **separado** y sin mapear: esa etiqueta no existe en el repositorio.
  `RFC-049 Discovery 2` no se reabre (sus dos hipótesis cayeron en desarrollo/validación) y
  `M-03/M-07` siguen tras el gate de historia forward.

---

## 9. Defectos y bloqueos (fase 6)

| bloqueo | estado | evidencia |
| --- | --- | --- |
| Certificación remota de GitHub Actions | **BLOCKED** | 3 workflows trackeados y presentes en disco, pero la cola sin publicar impide que exista una ejecución; no hay CLI de GitHub ni token en este checkout |
| Cola sin publicar | **BLOCKED** | 256 commits en el head del artefacto, 257 ahora; requiere autorización operativa |
| Terminación no reconstruida de la segunda ventana | **OPEN, acotado** | `paper-lab-continuous-03` (no sellada, 12 873 668 eventos): última supervisión 5.8866 h con estado `HEALTHY`, los cuatro hijos `RUNNING`, 0 reinicios, cola truncada en 4 streams y **sin artefactos de salida** (`LAB_RUN_REPORT/SNAPSHOT` ausentes), plan con duración 0.0 (ilimitada) y `stop_reason` nulo. Se **excluyen** por evidencia el disco (31.5 GB libres, nivel NORMAL, guard no disparado, 1.737 GB de 7.0 GB de válvula) y la petición de parada documentada. No se atribuye a falta de disco |
| Presupuesto real del volumen | **OPEN** | 88.69 h pagables con 17.051 GB al ritmo planificado; hoy 14.851 GB ≈ 77 h. 72 h y 168 h **no** caben con estrés 1.5×: no se lanzaron |
| M-03 / M-07 | **OPEN** | historia forward admisible = **4.1593 h selladas** (mínimo M-03: 24 h, 1 000 checkpoints). Añadidas desde WP-9: 0.0 h. La ventana no sellada **no cuenta** |
| PAPER_PROMOTION | **NOT_AUTHORIZED** | gobernanza leída del state view |
| Deriva de estado detectada por la verificación | **informada** | (1) 256 → 257 commits; (2) volumen libre 17.051 → 14.851 GB; (3) `data/st6/ST6_HEALTH_STATUS.json`, fichero no versionado que otra lane reescribe, ya no coincide con el pin del state view. Los pines usan hash normalizado a LF (13 de 14 reproducen ese convenio) |
| Defecto de reproducibilidad heredado | **OPEN** | los artefactos de WP-9 que consumen datos de campaña no se reconstruyen desde el commit (fase 0) |

Ninguno de estos bloqueos impide trabajo económico offline ya autorizado: E-1 se ejecutó
íntegramente sobre segmentos ya sellados, sin red, sin procesos y sin claves.

---

## 10. Verificación independiente (fase 7)

`INDEPENDENT_VERIFICATION.json` — constructor ≠ verificador:

- **53 comprobaciones, 0 fallidas**; **12 controles negativos, 0 no detectados**;
  `false_success = 0`.
- No importa ningún constructor (comprobado por test y en el propio JSON).
- Re-deriva la planicie desde `COST_MODEL_V3`, re-ejecuta la re-adjudicación desde el registro,
  reconstruye un libro por su cuenta, empareja trades con citas por su cuenta y re-implementa la
  regla de decisión de E-2 desde el documento.
- Controles negativos que **sí** fallan cuando deben: cabecera inflada en 5 bps, afirmación de
  estrategia admitida, unión con cita futura, planicie no congelada, familia con `ADOPT` sin
  `PROMOTE`, veredicto de E-2 manipulado, serie con cambio de signo, horizonte que el volumen no
  puede pagar, ventana no sellada contada como historia, gobernanza con promoción autorizada, y
  **una celda que sí supera la planicie debe ser admitida** (la prueba de que el «0 admitidas»
  no es un artefacto del código).

---

## 11. Entregables

En `data/recovery/wp10/` (no se sobrescribió ningún informe de otra lane):

| archivo | contenido |
| --- | --- |
| `WP10_BASELINE_ECONOMIC_AUDIT.md` / `.json` | reconstrucción del registro de 24 celdas y de las seis cifras cabecera |
| `WP10_EXECUTION_COST_DISTRIBUTION.md` / `.json` | E-1: distribuciones de coste medidas contra la planicie congelada |
| `WP10_E1_DECISION.md` / `.json` | las seis preguntas económicas con separación observado/supuesto |
| `WP10_E2_PREREGISTRATION.md` / `.json` | pre-registro del cribado de deriva a 30 min, gate cerrado |
| `WP10_ACTIVE_RECOVERY_MATRIX.md` / `.json` | clasificación de las 6 familias y capa de coste medida |
| `WP10_OPEN_BLOCKERS.md` / `.json` | bloqueos operativos y qué no bloquean |
| `WP10_PHASE0_WP9_CLOSURE.md` / `.json` | acta del cierre de WP-9 con el ensayo en checkout limpio |
| `RUN_REPORT.md` / `.json` | informe de ejecución plegado desde todos los artefactos |
| `INDEPENDENT_VERIFICATION.json` | verificación independiente con controles negativos |
| `FINAL_REPORT.md` | este informe |
| `evidence/E1_MEASUREMENTS.json` | la medición cacheada (657.6 s) de la que se derivan las tablas |

Scripts: `scripts/wp10_baseline_economic_audit.py`, `wp10_e1_cost_reality.py`,
`wp10_e1_decision.py`, `wp10_e2_preregistration.py`, `wp10_active_recovery.py`,
`wp10_open_blockers.py`, `wp10_phase0_wp9_closure.py`, `wp10_run_report.py`, `wp10_verify.py`
y `tests/unit/research/test_wp10_lane.py`.

---

## 12. Próxima decisión

La decisión que WP-10 entrega al operador es **una sola**, con tres caminos excluyentes:

1. **(a) Nueva hipótesis al nivel de fees actual.** El listón es 20 bps de round trip; la mejor
   ventaja bruta del registro es 8.912 bps. Es un factor 2.25× de mejora de señal, no de coste,
   y la familia donde mirar primero es `mean_reversion` (única con intervalo que excluye el cero).
2. **(b) Cambiar el nivel de fees que la planicie asume.** Es una decisión de gobernanza y de
   cuenta (descuento por token, nivel VIP), **sin medición asociada**: la planicie congelada no
   se modifica por encontrar un libro barato, y aun con el nivel descontado (15.02 bps) el
   registro seguiría sin admitir nada. Si se elige esta vía, el cambio debe hacerse por el
   contrato de gobernanza, no por este informe.
3. **(c) Capturar evidencia a nivel de orden** (ciclo de vida de órdenes, cola, ejecuciones
   parciales). Es la **única** forma de que la ejecución maker llegue a poder valorarse, y es la
   única medición que WP-10 no pudo hacer con lo que existe. Hoy es `INSUFFICIENT_EVIDENCE`, no
   una recomendación de resultados.

Recomendación del verificador y del constructor, en ese orden: **(c) como medición, (b) como
decisión de gobernanza si el operador quiere mover el listón, y ninguno de los tres sin antes
resolver la publicación de la cola de commits**, porque sin ella no hay CI remota ni historia
forward certificable.

---

## 13. Estimación de costes y recursos para la siguiente fase

Medida, no estimada de oído, a partir de lo ejecutado:

| recurso | consumo medido en WP-10 | extrapolación a una ventana de 24 h |
| --- | --- | --- |
| Medición E-1 de una ventana | **657.6 s** (11 min) para 4.1593 h: reconstrucción de libros 540.5 s, trades realizados 86.3 s, condiciones 22.5 s, cobertura 7.8 s | **≈ 64 min** de lectura/CPU (una sola pasada, cacheada y reanudable) |
| Volumen de segmentos | 411 segmentos / 11.58 M filas por 4.16 h | **≈ 4.61 GB** a 192.25 MB/h |
| Espacio libre necesario | budget de 800 MB por ventana fue el defecto que paró la ventana | 24 h + margen 1.5×: **≈ 6.9 GB**; hoy hay 14.851 GB libres (≈ 77 h pagables) → **una** ventana de 24 h cabe, 72 h no |
| Reconstrucción del libro | 1 984 checkpoints en 540 s | ~4.6× si se re-mide todo; el caché de la medición lo evita |
| Dinero real | **0** | 0 (offline, sin red, sin claves, sin órdenes) |

Coste de las alternativas: (b) es administrativo y no consume volumen; (c) exige una captura
nueva con un stream que hoy no existe (ciclo de vida de órdenes) y, por tanto, un cambio de
colector antes de que ninguna medición maker sea posible.

---

## 14. Límites de este informe y cosas que no se hicieron

- No se reabrió ninguna estrategia rechazada, no se admitió ninguna, no se modificó la planicie
  congelada, ningún criterio ni el modelo de coste. Contadores en cero en todos los artefactos.
- No se lanzó ninguna ventana de 72 h ni de 168 h: el presupuesto de volumen no las paga.
- No se ejecutó ninguna operación, ni se usaron credenciales, ni se capturaron datos de pago.
- E-1 mide BTC y ETH en **una** sesión de 4.16 h (régimen único, parada por válvula de disco) y
  solo spot/perp; no cubre SOL, no cubre alts ilíquidas y no cubre regímenes de estrés. El walk
  del libro es estático: una orden real llega a un libro que se mueve, y la latencia medida
  (113–187 ms de mediana) es el tamaño de ese movimiento.
- Los costes medidos son **estimaciones de lo que habría pagado una orden**, nunca ejecuciones.
  Maker, posición en cola, ejecuciones parciales y probabilidad de fill: `INSUFFICIENT_EVIDENCE`.
- La verificación se ejecutó en un árbol de trabajo compartido con otras lanes activas: la deriva
  de estado (commits, espacio libre, un pin de otra lane) queda declarada en
  `INDEPENDENT_VERIFICATION.json` y en `RUN_REPORT.md`, no suavizada.
