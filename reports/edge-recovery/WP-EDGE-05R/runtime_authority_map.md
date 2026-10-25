# RUNTIME AUTHORITY MAP — WP-EDGE-05R

**Qué es.** El mapa de autoridad del runtime **de este work package**: qué entrypoints existen, cuáles
se ejecutan solos y cuáles a mano, qué se ha tocado, qué no, y con qué prueba. Se ha establecido
leyendo el repositorio, ejecutando los entrypoints y consultando el sistema operativo, no
infiriéndolo del informe de un predecesor.

**Relación con los mapas anteriores.** `reports/edge-recovery/runtime_authority_map.md` (WP-EDGE-00)
clasifica el runtime **PAPER** del proyecto y no menciona `edge03`/`edge04`/`edge05`.
`reports/edge-recovery/WP-EDGE-05/runtime_authority_map.md` cubre la cadena forward y el vigilante
**antes** de este encargo. Este documento registra lo que WP-EDGE-05R cambia sobre esa base y **no
sustituye** a ninguno de los dos.

**Ámbito.** Observación SHADOW. Sin órdenes, sin credenciales, sin capital, sin promoción.

---

## 1. Leyenda

| Clase | Significado |
| --- | --- |
| `RUNTIME_AUTHORITATIVE` | Lo ejecuta una tarea programada del sistema operativo y su salida es la evidencia viva. |
| `RUNTIME_REACHABLE` | Se ejecuta a mano; escribe evidencia, nunca estado de trading. |
| `TEST_ONLY` | Solo lo ejecutan tests o verificadores. |
| `CONFIG` | Configuración del repositorio; cambia lo que git ignora, no lo que el runtime hace. |
| `NOT_TOUCHED` | Existe, es alcanzable y este work package no lo ha modificado. |

## 2. Baseline técnico y operativo

| | |
| --- | --- |
| Rama / base | `agent/edge-recovery/WP-EDGE-00-baseline`, commit base `5237c76` (`WP-EDGE-05`) |
| Host / intérprete | `DESKTOP-4CHO695` · `.venv\Scripts\python.exe` 3.11.15 |
| Tarea de la lane | `TradingAgentic-EDGE04-Forward` — `Ready`, `InteractiveToken`, `PT15M` (solo lectura en este WP) |
| Tarea del vigilante | `TradingAgentic-EDGE05-Watchdog` — `Enabled`, `PT15M` (solo lectura en este WP) |
| Volumen al empezar | 1,95 GiB libres — **por debajo del suelo crítico de 2 GiB**; la lane rechazaba sus ticks |
| Volumen al terminar la recuperación | 2,07 GiB libres — por encima del crítico, **por debajo del suelo sano de 5 GiB** |
| Esquema de la lectura del vigilante | `EDGE05_WATCHDOG_V2` (era `V1`): añade la **causa** del fallo |

## 3. Entrypoints y ficheros de este work package

| Fichero | Clase | Qué es y qué se le ha hecho |
| --- | --- | --- |
| `src/trading_bot/research/edge05/watchdog.py` | `RUNTIME_AUTHORITATIVE` | El vigilante que ejecuta la tarea programada. Se le añade el vocabulario cerrado de **causas** (`RESOURCE_PRESSURE`, `PROVIDER_FAILURE`, `DATA_QUALITY_FAILURE`, `RUNTIME_FAILURE`, `SCHEDULER_FAILURE`, `EXPECTED_NO_NEW_DATA`), se enruta la categoría por la causa y no por el sitio donde se notó, y el rechazo por disco pasa a alertar `TICK_REFUSED_RESOURCE` con el planificador declarado limpio. Esquema `V2`. |
| `src/trading_bot/research/edge05/reading.py` | `RUNTIME_REACHABLE` | **Nuevo.** Una lectura congelada del estado vivo: cada cifra con `run_id`, `as_of_utc`, `source_artifact`, `source_digest` y `measurement_scope`. No lo ejecuta ninguna tarea programada. |
| `scripts/edge05r_snapshot.py` | `RUNTIME_REACHABLE` | **Nuevo.** Toma la lectura y la congela con su digest. |
| `scripts/edge05r_report.py` | `RUNTIME_REACHABLE` | **Nuevo.** Renderiza `RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md` y la matriz ACC desde la instantánea, y **se niega** si el digest no cuadra. |
| `scripts/edge05r_storage_inventory.py` | `RUNTIME_REACHABLE` | **Nuevo.** Solo lectura: tamaña el volumen, clasifica y atribuye cada subárbol y demuestra qué bytes son recuperables. |
| `scripts/edge05r_storage_reclaim.py` | `RUNTIME_REACHABLE` | **Nuevo.** Dry run por defecto; `--apply` borra únicamente cachés que pasan las tres comprobaciones **re-derivadas para esa ruta**, nunca leídas de un plan. |
| `scripts/edge05_verify.py` | `TEST_ONLY` | El verificador independiente. Se le añade la regla de causa (un rechazo por recursos no puede archivarse como fallo del planificador), acepta `V1` y `V2` exigiendo que la lectura **más nueva** sea `V2`, y gana un sabotaje número 16. |
| `tests/unit/research/test_edge05_watchdog.py` | `TEST_ONLY` | Pruebas nuevas de las seis causas, del rechazo por disco y del caso "no hay nada nuevo". La fixture fija un volumen sano por defecto. |
| `tests/unit/research/test_edge04_autonomous.py` | `TEST_ONLY` | **Fichero de otro work package.** Solo se toca la fixture: fija un volumen sano por defecto para que el espacio libre del host no decida un veredicto. **Ninguna aserción cambia**; se declara aquí precisamente por ser ajeno. |
| `.gitignore` | `CONFIG` | Se añade `.hypothesis/`: era la única caché de herramienta no versionada que `.gitignore` no nombraba, y por eso el plan de recuperación se negó a incluirla hasta corregirlo. |
| `reports/edge-recovery/WP-EDGE-05R/**` | `RUNTIME_REACHABLE` | Los artefactos de este WP: diagnóstico, recuperación, instantánea, informes, matriz y estado de GitHub. |

## 4. Lo que este work package NO toca

| Componente | Por qué |
| --- | --- |
| `src/trading_bot/research/edge03/autonomous.py` (la lane) | El encargo recupera disco y arregla clasificación e informes; la lane ya cierra en falso correctamente. |
| `scripts/edge04_observer.py`, `scripts/edge04_verify.py`, `scripts/edge05_reconcile.py` | No hay defecto demostrado en ellos. |
| Risk Engine, `config/risk.yaml`, sizing, límites, gates de promoción | Prohibido: nada de este encargo los cambia. |
| Estrategias, señales, órdenes, credenciales de exchange | Fuera de ámbito. |
| Evidencia de otros workstreams | El diagnóstico los tamaña y dice a quién pertenecen; borrarlos es una decisión del propietario, no una limpieza. |

**Prueba de los límites.** `git diff --name-only 5237c76..HEAD` no lista ningún fichero de las dos
primeras filas de la tabla anterior, ni `config/risk.yaml`, ni nada bajo `src/trading_bot/risk/` o
`src/trading_bot/strategies/`; sí lista, y solo, los ficheros de la sección 3 más los informes.

## 5. La causa, y por qué importa

Un tick que la lane rechaza por disco sale con código 5. El vigilante lo veía como "el planificador
devolvió un resultado distinto de cero" y lo archivaba como `SCHEDULER_FAILURE`: un lector habría ido
a reparar el Programador de tareas mientras el problema era el volumen. Ahora el propio dato lleva la
causa (`failure_class`), la categoría se elige por la causa, y las dos comprobaciones son
verificables:

- el vigilante escribe `cause` y `failure_classes` en cada lectura, además de la categoría;
- el verificador **recalcula** la regla desde el dato y rechaza una lectura que diga
  `SCHEDULER_FAILURE` teniendo causa `RESOURCE_PRESSURE`;
- un sabotaje nuevo archiva un rechazo por recursos como fallo del planificador y **debe** ser
  detectado, de modo que la regla no puede volver a perderse en silencio.

`EXPECTED_NO_NEW_DATA` existe para lo contrario: nombrar lo que **no** es un fallo (un segundo disparo
del slot, o un tick sin nada nuevo) en lugar de dejarlo implícito.
