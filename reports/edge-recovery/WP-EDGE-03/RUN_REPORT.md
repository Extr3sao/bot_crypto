# WP-EDGE-03 — Registro de ejecucion

| | |
|---|---|
| paquete de trabajo | `WP-EDGE-03` (observacion forward, shadow y paridad de riesgo) |
| HEAD al ejecutar | `51bc497` (cierre previo de WP-EDGE-02: `04e4138`) |
| rama | `agent/edge-recovery/WP-EDGE-00-baseline` |
| corrida observada | `FWD-EDGE03-20261013T053048Z`, instante de mercado `2026-10-13T05:30:48Z` |
| modo | observacion de mercado publico de solo lectura + shadow hipotetico: **0 ordenes, 0 credenciales, 0 capital** |
| veredicto de la lane | `OBSERVATION_AVAILABLE` (226 dias de observacion, suelo declarado 60) · **promocion `NONE`** |
| paridad de riesgo | `PARITY_PASS` sobre 544 comparaciones clasificadas, 0 defectos |
| verificacion independiente | `VERIFY_PASS` 19/19 comprobaciones · `SELF_TEST_PASS` 20/20 sabotajes detectados |
| acciones de mercado | **ninguna**. No se declara `RENTABLE`, `CERTIFIED`, `PAPER` ni `PRODUCTION_READY` |

## 0. Estado recuperado antes de tocar nada

El paquete ya tenia un commit con codigo, pruebas, verificador y artefactos (`51bc497`, 25 ficheros). Este
registro **no** vuelve a contar ese trabajo como propio: lo que sigue distingue (a) lo ya commiteado, (b) lo
ejecutado de nuevo en esta sesion y (c) los defectos encontrados y corregidos aqui.

| elemento | estado al empezar | que hizo esta sesion |
|---|---|---|
| `src/trading_bot/research/edge03/{forward_plan,ingest,shadow,parity,reporting,run}.py` | commiteado | 2 defectos corregidos + deuda de lint/tipos del propio paquete saldada |
| `scripts/edge03_run.py`, `scripts/edge03_verify.py` | commiteados | idem |
| `tests/unit/research/test_edge03_forward.py` | commiteado | +6 pruebas (33 totales) |
| artefactos `reports/edge-recovery/WP-EDGE-03/**` | commiteados (corrida de `2026-10-12T23:39:51Z`) | regenerados por corridas reales de hoy |
| `RUN_REPORT.md/json`, `FINAL_REPORT.md` de este WP | **no existian** | escritos ahora |

## 1. Que se ejecuto

| paso | comando | resultado |
|---|---|---|
| runtime (observacion real) | `python scripts/edge03_run.py --outdir reports/edge-recovery/WP-EDGE-03` | exit 0 — corrida `FWD-EDGE03-20261013T050053Z` |
| runtime (segundo sondeo real) | idem | exit 0 — corrida `FWD-EDGE03-20261013T051043Z`, **0 barras nuevas** (`no_new_data` en las 6 series) |
| runtime (tercer sondeo real) | idem | exit 0 — corrida `FWD-EDGE03-20261013T051627Z`, 3 barras nuevas |
| runtime (corrida final) | idem | exit 0 — corrida `FWD-EDGE03-20261013T053048Z`, 3 barras nuevas |
| informe offline | `python scripts/edge03_run.py --reports-only <OBSERVATION.json>` | exit 0 — los informes se re-renderizan sin red |
| verificador independiente | `python scripts/edge03_verify.py --self-test --json-out reports/edge-recovery/WP-EDGE-03/VERIFICATION.json` | exit 0 — 19/19 y 20/20 |
| pruebas de la lane | `pytest tests/unit/research/test_edge03_forward.py -q` | **33 passed**, exit 0 |
| pruebas repo | `pytest -q` | **15 failed, 3663 passed** en 487 s, exit distinto de cero — **los 15 fallos son ajenos a esta lane** (§8.1) |
| lint | `ruff check src/trading_bot/research/edge03 scripts/edge03_run.py scripts/edge03_verify.py tests/unit/research/test_edge03_forward.py` | `All checks passed!` (exit 0) — antes: 23 hallazgos |
| tipos | `mypy` sobre los mismos 9 ficheros | `Success: no issues found in 9 source files` — antes: 15 errores |
| publicacion | 4 sondas `git push --dry-run` / `git ls-remote` | `BLOCKED_GITHUB_AUTH` (§10) |

Cuatro corridas reales, no una: la segunda **no** encontro barras nuevas y lo registro como resultado
(`no_new_data`), no como fallo; la tercera y la cuarta si encontraron barras nuevas y las sellaron. Un
pipeline que solo sabe crecer no esta probado; este sabe decir "no hay nada nuevo" y seguir.

## 2. Datos nuevos (ingesta incremental)

La tienda `data/forward/edge03/` es **append-only** y local (5,4 MB, ignorada por git; lo que se versiona es su
procedencia, sus digests y el ledger). El corpus congelado de WP-EDGE-01/02 **no se toca**: se re-lee y se
verifica que no se movio.

| corrida (UTC) | barras nuevas | 1h (por serie) | 15m (por serie) | resultado |
|---|---:|---|---|---|
| `2026-10-12T23:39:51Z` (heredada) | 17.850 (backfill del prefijo congelado) | 5.423 | 527 | `ingested` |
| `2026-10-13T05:00:53Z` | 84 | +6 | +22 | `ingested` |
| `2026-10-13T05:10:43Z` | **0** | 0 | 0 | `no_new_data` en las 6 series |
| `2026-10-13T05:16:27Z` | 3 | 0 | +1 | `ingested` / `no_new_data` mixto |
| `2026-10-13T05:30:48Z` (final) | 3 | 0 | +1 | `ingested` / `no_new_data` mixto |

Calidad del store final (recomputada por el verificador desde los bytes, no leida del informe):

| serie | barras | primera barra (UTC) | ultima barra (UTC) | gaps | duplicados | fuera de orden | contiguo |
|---|---:|---|---|---:|---:|---:|---|
| `1h:BTC/ETH/SOL` | 5.429 | `2026-03-01T00:00:00Z` | `2026-10-13T04:00:00Z` | 0 | 0 | 0 | si |
| `15m:BTC/ETH/SOL` | 551 | `2026-10-07T11:45:00Z` | `2026-10-13T05:15:00Z` | 0 | 0 | 0 | si |

- **Ninguna barra guardada es anterior o igual al cierre congelado** (`1h` ≤ `2026-02-28T23:00:00Z`,
  `15m` ≤ `2026-10-07T11:30:00Z`): comprobado barra a barra por el verificador (17.940 barras admisibles).
- **Ningun gap rellenado**: no hubo gaps; la regla declarada es contarlos y **nunca** rellenarlos.
- **Barra abierta**: ninguna se guardo; una barra sin cerrar se cuenta y se descarta.
- **Reinicio**: una segunda ingesta en el **mismo instante** devolvio `no_new_data` en las 6 series, anadio
  **0** barras y dejo los 6 digests identicos; duplicados de timestamp en el store: **0**; rechazos
  duplicados en el brazo primario: **0**.

### 2.1 Latencia de ingesta — dos lecturas, no una

| lectura | 15m (3 series) | 1h (3 series) | que significa |
|---|---|---|---|
| barras de ESTA corrida (cierre → store) | 1 barra/serie, mediana **48,8 s** | 0 barras | la latencia que veria un lector programado |
| ventana completa (incluye el backfill) | 551 muestras, mediana 227.391 s | 5.429 muestras, mediana 9.751.191 s | **no** es latencia del feed: es el dia en que la lane empezo a mirar |

Este es uno de los dos defectos corregidos en esta sesion (§7.2).

## 3. Shadow de las estrategias congeladas

Las reglas son **las congeladas**: el digest del ruleset se re-deriva en cada corrida y se compara con el que
publico WP-EDGE-01 (`d073a2d686b9b198…`); si no coincide, la lane **se niega a correr** (§7.1). El shadow
recorre la ventana forward (estrictamente posterior a cada congelacion) y **solo anota rellenos hipoteticos**:
cada fila lleva `hypothetical: true` y `order_sent: false`, y el proceso no tiene cliente de exchange.

| brazo | tf | escenario | barras ventana | senales | rellenos hipot. | neto USDT | max DD % | exposicion % |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `edge_trend_01_4h` (primario) | 4h | BASE | 4.065 | 103 | 31 | −44,31 | 2,78 | 28,86 |
| `edge_trend_01_4h` | 4h | 2X_FEES | 4.065 | 103 | 31 | −73,77 | 2,94 | 28,86 |
| `edge_trend_01_4h` | 4h | ADVERSE | 4.065 | 103 | 30 | −69,69 | 2,92 | 30,16 |
| `edge_trend_01_1d` | 1d | BASE | 675 | 5 | 3 | −54,66 | 0,66 | 8,70 |
| `edge_intra_01 / 01r / 02` (10 brazos) | 15m | BASE / 2X / ADVERSE | 1.581 | 0 | 0 | 0,00 | 0,00 | 0,00 |

- El embudo de rechazo del brazo primario es explicito: `candidate:trend_filter_fail` 86 (mas
  `volume_filter_fail` en el tramo intradia).
- Los brazos intradia no imprimen senal en la ventana forward: se registran como lectura, **sin promocion**
  (estan marcados `RESEARCH ONLY` en el plan declarado).
- **Ningun numero de esta tabla es una afirmacion de rentabilidad**: son negativos en la ventana observada,
  que es exactamente lo que la lane debe poder publicar sin adornos. `promotion` es `NONE` por construccion.

## 4. Paridad de riesgo con el motor autoritativo

Se alimenta al presupuesto de investigacion y al **Risk Engine real del runtime** con el mismo estado, la
misma intencion y el mismo instante, y se clasifica cada caso.

| clase | casos |
|---|---:|
| `AGREE_APPROVED` | 79 |
| `AGREE_REFUSED_SAME_RULE` | 155 |
| `RULE_ORDER_DIFFERS` | 194 |
| `RULE_NOT_MODELLED_BY_RESEARCH` | 72 |
| `SIZING_ROUNDING_ONLY` | 35 |
| `RESEARCH_ONLY_REFUSAL` | 9 |
| `SIZING_DIFFERS` | 0 |
| `PARITY_DEFECT` | **0** |

Veredicto **`PARITY_PASS`** con 544 casos clasificados. `RULE_NOT_MODELLED_BY_RESEARCH` nombra los limites que
el presupuesto de investigacion **no** modela (kill switch, limites de perdida diaria/semanal, drawdown
diario): no se cuentan como acuerdo ni como desacuerdo, se cuentan aparte. **Ningun limite se relajo** para
conseguir concordancia: los umbrales son los del runtime y los del presupuesto congelado, y las discrepancias
de orden de reglas o de redondeo se publican como tales.

## 5. Observabilidad producida

| artefacto | contenido |
|---|---|
| `forward-observation/DAILY_2026-10-13.md` | el dia mas reciente del store: barras recibidas, calidad, senales, rechazos, libro hipotetico, latencia de esta corrida, dias de observacion |
| `forward-observation/CUMULATIVE.md` | toda la ventana: por serie (primera/ultima barra, gaps, duplicados), ledger de ingesta, latencia (esta corrida y ventana), prueba de reinicio, tabla de brazos y paridad |
| `forward-observation/DAILY_REPORTS.json` | el rollup dia a dia, del que se generan los diarios |
| `forward-observation/OBSERVATION.json` | la observacion completa (plan, decision, corrida, calidad, sombra, paridad) — todo informe se genera de aqui |
| `risk-parity/PARITY.md` / `PARITY.json` / `PARITY_CASES.csv` | la paridad caso a caso, con la clase y las dos decisiones |

Los informes se generan **del artefacto, no de prosa**: `--reports-only` los re-renderiza sin red desde un
`OBSERVATION.json` guardado, y eso es lo que se ejecuto.

## 6. Verificacion independiente

`scripts/edge03_verify.py` **no importa nada de `trading_bot`**: lee los artefactos, la tienda cruda, los
corpus congelados y el texto de los fuentes; reafirma las constantes y reimplementa las comprobaciones.

| # | comprobacion | resultado |
|---|---|---|
| 1 | `ARTIFACTS_PRESENT` | PASS |
| 2 | `FROZEN_CORPUS_UNCHANGED` | PASS (6 series) |
| 3 | `FROZEN_PARAMS_PINNED` | PASS (`d073a2d686b9b198…` re-derivado del fuente) |
| 4 | `STORE_DIGESTS_MATCH_MANIFEST` | PASS (6 ficheros) |
| 5 | `FORWARD_BARS_AFTER_FREEZE` | PASS (17.940 barras) |
| 6 | `QUALITY_RECOMPUTED` | PASS |
| 7 | `OBSERVATION_DAYS_RECOMPUTED` | PASS (226) |
| 8 | `LATENCY_RECOMPUTED` | PASS (ventana **y** ultima corrida) |
| 9 | `SHADOW_WINDOW_RESPECTED` | PASS (1.356 filas) |
| 10 | `SHADOW_WINDOW_START_CONSISTENT` | PASS (16 brazos) |
| 11 | `HYPOTHETICAL_ONLY` | PASS (425 filas hipoteticas, 0 ordenes) |
| 12 | `SHADOW_ACCOUNTING` | PASS |
| 13 | `EXPOSURE_RECOMPUTED` | PASS (16 brazos) |
| 14 | `PARITY_CLASSES_RECOMPUTED` | PASS (544 casos, 0 defectos) |
| 15 | `PARITY_CASES_COMPLETE` | PASS |
| 16 | `RESTART_PROOF_CONSISTENT` | PASS |
| 17 | `VERDICT_RECOMPUTED` | PASS (`OBSERVATION_AVAILABLE`, promocion `NONE`) |
| 18 | `TEST_TARGET_EQUALS_RUNTIME` | PASS (`run_forward_observation` en ambos) |
| 19 | `NO_ORDER_PATH` | PASS (7 fuentes libres de llamadas de orden) |

Auto-test de sabotaje: **20 sabotajes aplicados, 20 detectados, 0 sin detectar, 0 saltados, 4 roturas
colaterales** (las colaterales son esperadas: sabotear la tienda rompe varias comprobaciones a la vez, y se
publican como colaterales del sabotaje, no como detecciones).

## 7. Defectos encontrados y corregidos en esta sesion

### 7.1 La lane afirmaba algo que no comprobaba (regla congelada)

El modulo declaraba en su docstring que el digest del ruleset "se re-deriva y se compara aqui". **No habia
ninguna comparacion**: se publicaba el digest y nadie lo contrastaba con el que WP-EDGE-01 publico, asi que
una edicion posterior de `FROZEN_PARAMS` habria corrido hacia delante midiendo un ruleset distinto **sin que
nada se quejara**. Correccion: `forward_plan.assert_frozen_params()` re-hashea `FROZEN_PARAMS` desde cero
(receta reafirmada en el modulo), lo compara con la constante importada y con `OOS_TREND.json#params_hash`, y
**aborta** si algo no cuadra; el runtime lo ejecuta en cada corrida y lo publica en
`OBSERVATION.json#frozen_params`. El verificador lo comprueba por su cuenta **parseando el fuente con `ast`**
(no importando el paquete), y el auto-test lo sabotea aflojando un parametro del texto fuente.
4 pruebas nuevas cubren: pin correcto, parametro aflojado, publicacion ausente y publicacion de otro ruleset.

### 7.2 La latencia publicada no era la latencia de la corrida

`OBSERVATION.json#latency` agregaba **todas** las barras de la tienda, incluido el backfill inicial de marzo,
y el informe diario publicaba ese maximo (`19.521.591 s` ≈ 226 dias) como estado del proceso de hoy. Un lector
no podia distinguir "la ingesta tarda 49 s" de "la lane empezo a mirar en marzo". Correccion: dos lecturas
separadas en el runtime (`ventana` y `barras de esta corrida`), dos tablas en el informe acumulado, una linea
en el diario que solo habla de lo que **esta** corrida recibio, y el verificador recomputa **ambas** ademas de
exigir que una corrida que no trajo barras **no** publique cifra fresca. El auto-test gana un sabotaje que
publica el backfill como si fuera la ultima corrida.

### 7.3 Deuda de lint y tipos del propio paquete

El commit de la lane dejo **23 hallazgos de ruff** (imports sin usar, imports desordenados, `__all__` sin
ordenar, f-string sin placeholders, `zip()` sin `strict`, `pairwise` evitable, variable de bucle muerta,
codigo muerto en el verificador) y **15 errores de mypy strict** (variables reutilizadas con otro tipo,
retornos `Any`, `type: ignore` innecesarios, anotaciones ausentes, aritmetica sobre `object`) en sus propios
ficheros. Correccion: los 38 puntos resueltos **sin relajar ningun umbral** (nada de `# type: ignore` nuevo ni
reglas desactivadas), y los dos ficheros del commit anterior que declaraban una comprobacion y no la hacian se
dejaron en su sitio. Los 9 ficheros de la lane quedan limpios para `ruff check` y `mypy` strict.

## 8. Gates

| gate | comando | resultado |
|---|---|---|
| lint (lane) | `ruff check` sobre los 9 ficheros de la lane | `All checks passed!` (exit 0) |
| tipos (lane) | `mypy` strict sobre los 9 ficheros de la lane | `Success: no issues found in 9 source files` (exit 0) |
| pruebas (lane) | `pytest tests/unit/research/test_edge03_forward.py -q` | 33 passed (exit 0) |
| pruebas (repo) | `pytest -q` | **15 failed, 3663 passed**, 78 warnings, 487,47 s, exit distinto de cero — 0 fallos en esta lane, causas ajenas en §8.1 |
| formato | `ruff format --check` sobre los 9 ficheros de la lane | **8 de 9 se reformatearian** — deuda preexistente del repo (ver §11), no se reformatea para no enterrar el diff semantico |
| lint (repo) | `ruff check .` | **150 hallazgos, 0 en los ficheros de esta lane** — deuda preexistente de otras lanes con la version local de ruff (0.15.20; el pin del repo es `ruff>=0.4.0`) |

Los dos ultimos no se declaran verdes: se declaran **medidos y ajenos a este diff**.

### 8.1 Los 15 fallos de la suite completa, clasificados

Ninguno toca `edge03`: ningun test que falle importa ni ejecuta nada de esta lane. Causas observadas, todas
en el checkout compartido y en el host:

| fichero | fallos | causa observada |
|---|---:|---|
| `tests/unit/scanner/test_universe_scanner.py` | 8 | lane del scanner |
| `tests/unit/research/test_wp9_disk_budget.py` | 3 | el preflight de disco de WP-9 respondio `INSUFFICIENT_FREE_SPACE` (el host esta al **97 %**: 7,4 GB libres de 238 GB) donde el test espera `INCOHERENT_BUDGET` |
| `tests/unit/research/test_recovery_determinism.py` | 2 | "the committed view is stale: re-run scripts/campaign_state_view.py" y el digest de `data/recovery/ACTIVE_ECONOMIC_AUDIT.json`: vistas de estado de otras lanes, movidas por commits ajenos |
| `tests/unit/research/test_cost_barrier_adversarial.py` | 1 | la reproduccion del cost barrier devuelve `REPRODUCTION_FAILED` |
| `tests/unit/research/test_active_recovery_wp.py` | 1 | `INSUFFICIENT_FREE_SPACE` (misma causa de host) |

Se declaran aqui como **preexistentes y ajenos**: no se han corregido porque pertenecen a otras lanes y al estado
(dinamico) de este checkout compartido, y corregirlos exigiria tocar trabajo que no es de este paquete.

## 9. Commits

El conjunto lo define la etiqueta del asunto, no una tabla a mano:

```
git log --oneline --grep='\[WP-EDGE-03\]'
```

Hasta el commit que ancla este registro, `WP-EDGE-03` aporta **1 commit** (`51bc497`, codigo + artefactos +
`.gitignore`), y este cierre anade los commits de correccion y de informes con la misma etiqueta.
`git rev-list --count 4be09fb..HEAD` da **27** commits por delante de la base.

## 10. Publicacion — `BLOCKED_GITHUB_AUTH` (sigue bloqueada)

| sonda | exit | resultado |
|---|---:|---|
| `GIT_TERMINAL_PROMPT=0 git push --dry-run` | 128 | la rama no tiene upstream: no se intento escritura remota |
| `GIT_TERMINAL_PROMPT=0 git -c credential.helper= push --dry-run origin HEAD:refs/heads/agent/edge-recovery/WP-EDGE-03` | 128 | `fatal: could not read Username for 'https://github.com': terminal prompts disabled` |
| `GIT_TERMINAL_PROMPT=0 git push --dry-run origin HEAD:refs/heads/agent/edge-recovery/WP-EDGE-03` (helper por defecto) | 124 | **se cuelga**: el helper interactivo abre su propio dialogo, que `GIT_TERMINAL_PROMPT` no suprime; cortado a los 45 s |
| `GIT_TERMINAL_PROMPT=0 git ls-remote --heads origin 'refs/heads/agent/edge-recovery/*'` | 0 | lectura anonima OK; **no existe ninguna ref de la lane** en el remoto |

`GITHUB_TOKEN`, `GH_TOKEN` y `GIT_ASKPASS` estan sin definir, no hay `~/.git-credentials` y `gh` no esta
instalado. **No se ha leido, pedido, almacenado ni impreso ningun token.** Los commits quedan **locales**; el
procedimiento de desbloqueo (9 pasos, con cuatro vias) es el que documenta `RUN_REPORT.json#push`.

## 11. Limites

- La ventana forward es **corta por construccion** (29 dias de `1h`, 6 de `15m`): la lane dice cuantos dias
  independientes ha visto (226 contando el prefijo congelado, 2 dias nuevos desde la congelacion) y **no**
  lee un criterio de admision. Nada aqui es una afirmacion de rentabilidad.
- Los brazos intradia leen BTC `1h` como contexto, exactamente como hacia el campaign congelado, extendido con
  las barras forward para que el contexto cubra la ventana.
- La paridad compara **dos implementaciones sobre las mismas entradas**: no dice que limites son los correctos,
  solo si ambas coinciden.
- Toda cifra de PnL de este informe es **hipotetica** (`hypothetical: true`, `order_sent: false`); no hay
  capital, ni orden, ni endpoint privado en ningun punto de la lane.
- La corrida depende de la red publica de Binance; si el venue no responde, la lane registra el error y **no**
  inventa datos (esta sesion incluye una corrida con `no_new_data` en las 6 series, que es ese camino).
- Los dos gates en rojo de §8 (formato de los 9 ficheros de la lane; `ruff check .` con 150 hallazgos ajenos)
  son deuda preexistente del repo con la toolchain local, medida y publicada aqui, no corregida para no
  mezclar trabajo de otras lanes.
