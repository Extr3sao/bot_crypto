# WP-051-02K (operativo) — FINAL REPORT

**Paquete:** WP051-02K Operational Unblock · **Generado:** 2026-10-24T07:30Z
**Dictamen:** `BLOCKED_WITH_EVIDENCE` — el guard vuelve a sonar y el espacio sobra, pero la lane no puede observar ni una barra.

---

## HEAD / WORKTREE

| | |
|---|---|
| Árbol principal | `Downloads/bot freebuff` · `0e13160a` → `c94b1a2b` → `941a524b` (herramientas, evidencias e informes de este paquete) |
| Árbol de campaña | `Downloads/exp004a-recovery-02k` · rama `recovery/exp004a-02k-9983b050` |
| HEAD antes | `9983b050` |
| HEAD después | **`688c5805`** |
| Commits | `0e41566d` «Make the EDGE-04 alarm survive the case it exists for» (+14/−1) · `688c5805` «Give the observer's own cadence an action that exists» (lanzador, 12 líneas) |
| Estado del árbol | limpio salvo artefactos de 02K de la sesión anterior, que este paquete no toca |

El guard recuperado quedó **arreglado**, no sustituido: mismo fichero sellado, mismo contrato de salida, misma política.

## SOURCE

- Código: el commit huérfano `9983b050`, anclado en la rama anterior; byte-idéntico a sus blobs.
- Corpus 1h: re-derivado del mismo endpoint público que el productor que sigue versionado (`scripts/fetch_alpha_expansion_history.py`), aceptado **solo** al coincidir con `FROZEN_SHARD_SHA256`.
- Corpus 15m: sin fuente. El productor nunca se versionó y no existe en ningún árbol.

## RECOVERY

| Componente | Estado | Evidencia |
|---|---|---|
| Guard (`edge04_watchdog.py`) | `FOUND_VALID` + **1 defecto reparado** | `0e41566d`, sha256 `74f75c34…` |
| Tareas del planificador (3) | `FOUND_BROKEN` → **REPAIRED** | watchdog 0, alarma 0, forward probada y aparcada |
| Corpus 1h (BTC/ETH/SOL) | **`RESTORED_AND_PINNED`** | digests en `EVIDENCE.json` |
| Corpus 15m (BTC/ETH/SOL) | `ABSENT` · `NOT_REPRODUCIBLE` | 116/36/72 B cortos, sha ≠ |
| Store de campaña anterior | `ABSENT` (permanente) | buscado por nombre, huella, worktrees, 91 commits colgados |
| Store nuevo | `CREATED` (identidad nueva) | `edge04r01` / `edge03r01`, `run_id` `FWD-EDGE04-20261024T071500Z` |

Lo que se restauró, se restauró **con su propia prueba**: los tres digests 1h coinciden con el pin, y ningún componente se ha inventado para tapar un hueco.

## INTEGRITY

| Comprobación | Resultado |
|---|---|
| `assert_frozen_corpus()` | **REFUSES** — `FileNotFoundError: …/data/raw/alpha003/price/BTCUSDT_15m.json` |
| Corpus 1h vs pin | 3/3 coinciden (62 724 / 62 724 / 48 646 barras) |
| Corpus 15m vs sha publicado | 0/3 coinciden |
| Guard: 6 casos de fallo | 6/6 con el par (estado, salida) documentado |
| Recibo de alerta en `BLOCKED` | `receipt: true` (leído del historial del sistema) |
| Marcador `ATTENTION_REQUIRED.txt` | se levanta en `BLOCKED`/`UNREADABLE`, se retira al recuperar |
| Lease del observador | liberado tras el fallo |
| Filas corruptas en `runs.jsonl` | 0 |

## TESTS

| Suite | Resultado | ¿Regresión? |
|---|---|---|
| Arnés del guard | 6/6 | no |
| `test_edge04_autonomous.py` | 5 fallos, 44 pasan | **no**: idéntico con el guard revertido a `9983b050` |
| `02h`+`02i`+`02j` | 1 fallo, 62 pasan | **no**: `COVERAGE_CEILING` 6408 vs 6456 también en `9983b050` |
| `test_edge04r_continuity.py` + `02k_continue` | pasan (dentro de 104) | no |
| pytest del verificador 02K | 32 pasan, salida 0 | no |

`TEST_RESULT != CAMPAIGN_READINESS`. Los 5 fallos de la lane son el pin negándose, no el arreglo del guard: 62 tests pasan, incluido el que carga el módulo del guard.

## RUNTIME

| Ejecución | Código | Resultado |
|---|---|---|
| `schtasks /run` watchdog | 0 | `WATCHDOG.json` = `OK`, 39.48 GiB libres, sin motivos |
| `schtasks /run` alarma | 0 | `SUPERVISOR.json` = `WATCHDOG_ALIVE`, antigüedad 19 s |
| Transiciones | — | `UNREADABLE → RECOVERED → OK` |
| Tick del observador (manual) | **1** | `RUNTIME_EXCEPTION`, 21.7 s, 0 corruptas |
| Tick del observador (por el planificador) | **1** | `mode=SCHEDULED`, misma ranura, misma `run_id`, fila persistida |
| Filas en `runs.jsonl` | — | 3, todas `RUNTIME_EXCEPTION`, **0** observaciones |

Ninguna orden, ninguna credencial, ningún mercado real: el tick no llegó a pedir una barra.

Con la cadencia aparcada, el guard pasará a `STALE` en cuanto el último tick supere los 45 minutos de tolerancia. Eso es lo correcto: la lane no está observando y la alarma debe decirlo. La luz verde de hoy sólo certifica que el guard funciona.

## VERIFIER

| Verificador (sellado en `9983b050`) | Salida | Veredicto |
|---|---|---|
| `exp004a_wp051_02k_verify.py` | 1 | 11/18 PASS, 7 FAIL |
| `edge04_verify.py` | 1 | 7/15, `VERIFY_FAIL` |

`BUILDER != VERIFIER`. Los siete fallos del 02K tienen causa conocida: cuatro por el almacén ausente, dos porque el host tiene hoy 39 GiB libres donde el informe de 02K declaraba 1.50 GiB, y uno por la limpieza de 209 directorios que 02K sí ejecutó. El verificador de la lane confirma lo que importa: la estructura del almacén es sana (`SLOT_DISCIPLINE`, `OUTCOMES_AND_EXIT_CODES`, `NO_ORDER_PATH_OR_PROMOTION`, `HEALTH_FOLLOWS_THE_LOG`) y no hay evidencia de observación porque no la hay.

## SPACE

| | |
|---|---|
| Presupuesto congelado | 15 638 712 264 B = 14.5647 GiB (`wp051_02j/CAPACITY_PLAN.json`) |
| Libre mínimo muestreado | **39.3457 GiB** |
| Peor margen | **+24.781 GiB** (12 muestras / 220 s) |
| Peor caída entre muestras | 0.4703 GiB |
| Cambio neto en la ventana | −1.4581 GiB |
| Veredicto | `CAPACITY_OK` |
| Borrados | **0** |

No hacía falta borrar nada y no se borró nada. Cachés derivadas reclamables identificadas y **no** tocadas: 0.1153 GiB. El margen es real pero no eterno: el volumen perdió 1.46 GiB en 220 s, y ahora hay un guard que lo mira cada 15 minutos.

## FALSE_SUCCESS

Rechazos explícitos, para que nadie los lea como logros:

1. **`WATCHDOG.json = OK` no es una campaña viva.** Significa que el observador escribió un tick reciente. Ese tick terminó en `RUNTIME_EXCEPTION`: la lane está vigilada, no operativa.
2. **Restaurar el corpus 1h no es tener el corpus.** El pin sigue negándose por el shard de 15m; con tres cuartas partes del ancla no se mide nada.
3. **Un `run_id` nuevo no es una observación.** Hay almacén persistente, reanudable y verificable, y cero barras dentro.
4. **62 tests pasando no son readiness.** Ni 104, ni los 32 del verificador.
5. **Una tarea habilitada no es una cadencia.** `TradingAgentic-EDGE04-Forward` llevaba desde el 13 de octubre con salida `2` cada 15 minutos: era el intérprete diciendo «no encuentro el fichero», no el observador diciendo «ya estoy corriendo».
6. **`BLOCKED_WITH_EVIDENCE` no es un fracaso del paquete**: los criterios 1, 2, 5 y 6 se cumplen y están medidos; el 3 y el 4 no, y se dice por qué.

## BLOCKERS

| ID | Bloqueo | Estado |
|---|---|---|
| BLK-01 | Store de campaña anterior ausente | **superado** — identidad nueva, sin reutilizar la perdida |
| BLK-02 | Corpus congelado 15m ausente en todo el host | **abierto y decisivo** |
| BLK-03 | Productor del shard 15m nunca versionado | **abierto** — causa raíz de BLK-02 |
| BLK-04 | Cifras de capacidad de 02K desmentidas por el host | **abierto, cosmético** — el informe de 02K ya no describe el volumen |

## DEFECTS

| ID | Severidad | Estado |
|---|---|---|
| DEF-02K-OPS-01 — el guard moría con `FileNotFoundError` si faltaba la raíz | alta | **reparado** (`0e41566d`) |
| DEF-02K-OPS-04 — la salida `2` del intérprete colisiona con `ALREADY_RUNNING` del observador | alta | **registro reparado** (`688c5805`); el código sigue ambiguo |
| DEF-02K-OPS-02 — `OK` no distingue «tick fresco» de «tick que falló la verificación» | media | abierto, por diseño del guard (informa, no repara) |
| DEF-02K-OPS-03 — dos filas idénticas en `WATCHDOG_EVENTS.jsonl` por transición bloqueante | baja | abierto, cosmético |

No se han cambiado umbrales, contratos ni criterios. Ninguna de las reparaciones hechas —ni la del guard, ni la de los tres registros— habría acercado la lane a observar una sola barra.

## DECISION

**`BLOCKED_WITH_EVIDENCE`.**

Criterios de aceptación: `watchdog operativo` **PASS** · `capacidad con margen` **PASS** · `ejecución nueva verificable` **FAIL** · `verificadores PASS sin SKIP injustificado` **FAIL** · `evidencia independiente` **PASS** · `FALSE_SUCCESS = 0` **PASS**.

Lo que separa este paquete de `READY_TO_RESUME` es un fichero de 4.5 MB por activo cuyo contenido exacto está publicado pero cuyo productor se perdió. No es un problema de código, de espacio ni de vigilancia: es un problema de datos que ya no existen en este host.

## NEXT_ACTION

1. Obtener los originales `BTCUSDT_15m.json`, `ETHUSDT_15m.json`, `SOLUSDT_15m.json` de una copia fuera del host (o del equipo que los generó) y colocarlos en `<árbol>/data/raw/alpha003/price/`.
2. Comprobar, sin tocar el código, que el pin los acepta:
   `python -c "import sys;sys.path.insert(0,'src');from trading_bot.research.edge03 import forward_plan as FP;print(FP.assert_frozen_corpus())"`
   Debe imprimir `15m:BTC cd1d2ea256a97f7c`, `15m:ETH b8fd5744cc66f635`, `15m:SOL 72a268137cbe944b`.
3. Solo entonces, el primer tick real de la campaña nueva:
   `python scripts/edge04_observer.py --state-root data/forward/edge04r01 --store-root data/forward/edge03r01`
   Esperado: `OBSERVED` o `NO_NEW_DATA`, salida 0. Con la cadencia: `schtasks /change /tn TradingAgentic-EDGE04-Forward /enable`.
4. Si no aparece ninguna copia: **no** re-congelar el corpus dentro de este paquete. Eso es una decisión de experimento nuevo (quant-researcher + backtest-engineer + ADR), no una reparación, y cambiaría el ancla contra la que se midió todo lo anterior.

El guard queda arreglado, repuntado y con recibo; el espacio queda holgado; el corpus 1h queda restaurado y probado. Lo que falta es un fichero que solo puede venir de fuera.
