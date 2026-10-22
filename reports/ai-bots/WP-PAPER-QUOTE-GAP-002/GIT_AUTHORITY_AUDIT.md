# ACTUALIZACIÓN — RFC-PAPER-QUOTE-GAP-003 (cierre de Fase A)

> Esta sección se añade **encima** de la auditoría A5, que se conserva íntegra debajo como
> registro histórico. Los defectos O1–O9 que la auditoría abrió se cierran o se degradan con
> evidencia nueva en `rfc003/`.

| defecto | estado | evidencia |
|---|---|---|
| O1 identidad de import | **cerrado** | clone limpio en `aab65cf`; `trading_bot.__file__` dentro del checkout; señuelo en `PYTHONPATH` → gate exit 3 `REFUSED` |
| O2 log primario fuera del WP | **cerrado** | `rfc003/evidence/` versionado, 11 ficheros con sha256 en `EVIDENCE_MANIFEST.json` |
| O3 kills sólo pre-`COMMIT` | **cerrado** | los 14 kills siguen siendo pre-`COMMIT` (`closed 0→0`), y la rama posterior tiene test propio en `fed5476` |
| O4 `false_success` mal nombrado | **cerrado** | se publica `unsupported_pass_count=0/10`, no `FALSE_SUCCESS=0` |
| O5 `ledger.py` fuera del inventario | **cerrado** | `runtime_inventory` de 8 ficheros incluye `vision/ledger.py`; `NEG-10` lo exige |
| O6 `git diff --check` rc=2 | **cerrado para código** | `pyproject.toml` renormalizado a LF en el índice; check acotado `rc=0`. El global sigue en `rc=2` por 128 CR de ficheros `-text` |
| O7 cabeza de cadena confundida con hash de fichero | **cerrado** | `hash_kinds` + `chain_heads` separados en el manifiesto |
| O9 `live_*` literales | **cerrado** | 3 espías armados sobre `ccxt`, 0 cruces; `external_orders` sigue `NOT_VERIFIABLE` |

**Correcciones a esta misma auditoría** (medidas, no supuestas):

1. «Sin `PYTHONPATH`, `import trading_bot` resuelve a `Downloads/bot freebuff/src`» era falso en
   el baseline de hoy: el paquete **no era importable en absoluto**. El defecto O1 se mantenía,
   el mecanismo no.
2. «Ausencia estática de ruta de orden en `vision/` y `paper/`» era cierto de esas dos carpetas y
   falso del proceso: el lane carga `ccxt` y `trading_bot.execution`, y `app.py` tiene un
   `_cmd_place_order` real y gateado. El cero de órdenes se sostiene por frontera armada, no por
   ausencia de código.
3. El total de 694 se reproduce **exacto** desde el checkout limpio, en cinco tramos disjuntos.

Decisión vigente: **`PASS (LAB ONLY)`** — ver `rfc003/FINAL_REPORT.md`.

---

# GIT_AUTHORITY_AUDIT — WP-PAPER-QUOTE-GAP-002 (Fase A)

**Fecha:** 2026-10-21 · **Rama:** `wp/paper-resume-001` · **HEAD:** `fefb0771036c33c648ecb2ed11cb28e8c2b49264`
**Modo:** auditoría read-only. Sin LIVE, sin órdenes, sin commits, sin cambios de configuración.
**Decisión:** **`PARTIAL`** — la identidad entre el código probado y el disco actual está demostrada
por hash **y** por re-ejecución; lo que falta es que esa identidad esté anclada a un commit y que
las evidencias primarias de dos afirmaciones vivan dentro del propio WP.

---

## 1. Estado real del repositorio (A1)

| dato | valor |
| --- | --- |
| `git rev-parse HEAD` | `fefb0771036c33c648ecb2ed11cb28e8c2b49264` |
| rama | `wp/paper-resume-001` |
| upstream | **ninguno** (`fatal: no upstream configured`) |
| ficheros modificados | **8** (`M`) |
| entradas sin seguimiento | **121** (102 bajo `.tmp/`, 19 fuera) |
| `git diff --stat` | 8 ficheros, `+1009 / −30` |
| `git diff --check` | **rc=2** — 4 líneas de `pyproject.toml` marcadas como *trailing whitespace* |
| `git log -5` | `fefb077` · `9800925` · `10919df` · `f014813` · `b0e1549` |

**Modificados:** `.gitattributes`, `docs/agentic/EXECUTION_CHECKPOINT.md`,
`docs/runtime/runtime_authority_map.md`, `pyproject.toml`, `src/trading_bot/vision/{lane,ledger,prospective,quotes}.py`.

**Nuevos fuera de `.tmp/` (19):** `src/trading_bot/vision/{durable,gap_recovery}.py`,
`scripts/{quote_gap_lab,verify_quote_gap,make_quote_gap_evidence,quote_feed_source,paper_resume_drill,verify_paper_resume,make_resume_report}.py`,
`tests/unit/vision/{test_gap_recovery,test_gap_recovery_venue,test_durable_book,test_session_durable,test_session_recovery}.py`,
`docs/rfc/RFC-050_*.md`, `docs/rfc/RFC-051_*.md`, `data/quote-feed-1m/*`.

**Nada de este WP está commiteado.** El código que pasó las pruebas existe **sólo** en el árbol de
trabajo; `HEAD` no lo contiene. La auditoría no descartó, movió ni reescribió ningún fichero.

Snapshot de A1: 8 `M` + 121 sin seguimiento. Después la auditoría añadió **15 entradas nuevas**
(todos bajo `.tmp/audit/`: el probe, su estado y los logs de re-ejecución), así que `git status`
muestra 144. Siguen siendo 8 los ficheros versionados modificados: ningún fichero de código,
tests o scripts cambió.

**Política del repo que afecta a la evidencia:** `reports/ai-bots/*` está en `.gitignore`
(`.gitignore:463`), así que los artefactos del WP **no pueden** tener identidad Git. Su única atadura
al código son los hashes que registran ellos mismos.

**`git diff --check` no está limpio, y la causa importa:** `pyproject.toml` está guardado en CRLF; las
líneas añadidas terminan en `\r\n` y git las reporta como espacio final porque `core.whitespace` no
incluye `cr-at-eol` en esta configuración. Es higiene de fin de línea, no contenido corrupto: el
`+`/`−` del diff está intacto y `pytest` lee el fichero sin error.

## 2. Correspondencia evidencia ↔ código (A2)

### 2.1 Hashes registrados contra disco — 20/20

`RUN_REPORT.json` (generado `2026-10-21T09:02:37Z`) registra 17 hashes de fichero y 3 de artefacto.
Recomputados ahora, **todos coinciden**:

| grupo | ficheros | resultado |
| --- | --- | --- |
| `runtime_sha256` | 7 (`gap_recovery`, `durable`, `lane`, `quotes`, `prospective`, `paper/broker`, `risk/manager`) | 7/7 `OK` |
| `script_sha256` | 4 (`quote_gap_lab`, `verify_quote_gap`, `quote_feed_source`, `make_quote_gap_evidence`) | 4/4 `OK` |
| `test_sha256` | 6 (los del WP) | 6/6 `OK` |
| `artifacts` | `GAP_LAB.json`, `VERIFICATION.json`, `DRILL.json` | 3/3 `OK` |
| `lab/SHA256SUMS` vs `GAP_LAB.json` | — | `OK` (`9970d07d…`) |
| `VERIFICATION.lab_sha256` vs `GAP_LAB.json` | — | `OK` |

Cronología coherente y sin solapes imposibles: drill `07:44:46Z` → lab `07:49:29Z` → log de la suite
`08:56:46Z` → `RUN_REPORT`/`VERIFICATION` `09:02:37Z` → `FINAL_REPORT` `09:03:37Z`.

### 2.2 El runtime alcanzado es el de este worktree — con una dependencia frágil

El venv usado (`…/Downloads/bot freebuff/.venv`) **no** tiene `trading_bot` instalado como paquete,
pero un `.pth`/editable apunta al checkout hermano:

```
python -c "import trading_bot"        →  …\Downloads\bot freebuff\src\trading_bot\__init__.py
python -m pytest … -o pythonpath=     →  ERROR de colección ("No module named
                                          'trading_bot.vision.gap_recovery'")
```

Es decir: sin la línea `pythonpath = ["src"]` de `pyproject.toml`, **la suite de este WP no puede ni
siquiera importar el módulo que dice probar**, y un fichero que sí existiera en el árbol hermano se
probaría desde el árbol equivocado sin que nada fallara. Esa línea es la única garantía, **y está
sin commitear** (defecto **O1**).

Los scripts que producen las evidencias no dependen de esa línea: `quote_gap_lab.py` y
`paper_resume_drill.py` hacen `sys.path.insert(0, REPO/"src")`; `make_quote_gap_evidence.py` pasa
`PYTHONPATH=REPO/src` a cada hijo. Los procesos hijos del experimento vuelven a ejecutar el mismo
script, que reinserta `src`.

### 2.3 Independencia del verificador — real, con un límite que hay que nombrar

`scripts/verify_quote_gap.py` importa **sólo** `argparse`, `copy`, `hashlib`, `json`, `sys`,
`pathlib`, `typing`: **no importa `trading_bot`**. Recalcula con aritmética propia:

- niveles de stop/take desde `entry_price` y `%` (`_level`), reescritos frente a
  `PaperPosition` del bróker (líneas 90-97 de `paper/broker.py`);
- toques desde la tabla de minutos (`_touches`), no desde los `*_touch` que publica el laboratorio;
- identidades económicas por cierre (`pnl = gross − comisiones`, `coste = reference_gross − gross`),
  equity que se financia, disjunción abierto/cerrado, y `_walk` sobre los cuerpos de ambos brazos
  con una lista blanca de exenciones que **valida** (`exemptions_are_known`).

Límite: el verificador audita **el JSON del laboratorio**, no vuelve a ejecutar el runtime. Prueba
consistencia interna y aritmética del artefacto; que ese artefacto lo escribiera
`quote_gap_lab.py` con ese runtime lo da la construcción + el hash, no el verificador.

## 3. Validación de afirmaciones (A3)

Re-ejecutado en esta auditoría (host con `loadavg 65`, de ahí los tiempos): la suite amplia se
corrió en cinco tramos porque una sola invocación excede el límite de 600 s de la herramienta.
**Ninguno falló.**

Las **14** afirmaciones auditadas se clasifican: **12 `CONFIRMED`**, **2 `NOT_VERIFIABLE`**,
**0 `CONTRADICTED`**. Diez están en la tabla; las cuatro restantes (post-`COMMIT`, datos de
mercado, exchange y PAPER/LIVE) se clasifican en §5.

| # | afirmación | clasificación | evidencia | límite |
| --- | --- | --- | --- | --- |
| 1 | **694 tests PASS** | `CONFIRMED` | colección `334+73+147+140 = 694`; re-ejecución `310 + 240 + 92 + 33 + 19 = 694`, los cinco tramos con exit 0 | la evidencia archivada de la corrida original es un **log ignorado por git** (`.tmp/wide-suite.log`), fuera del WP, y `RUN_REPORT` lo cita como `source: captured log` sin hash (`O2`) |
| 2 | **90 tests del WP** | `CONFIRMED` | colección 90, corridos dentro del tramo de 310, exit 0 | — |
| 3 | **22 de minutos/subbar** | `CONFIRMED` | colección exacta 22, corridos en el tramo de 92, exit 0 | — |
| 4 | **ruff y mypy sin errores** | `CONFIRMED` | `ruff` exit 0 sobre 17 ficheros; `mypy` exit 0 sobre 7 | el inventario hasheado omite `vision/ledger.py`, que está modificado (`O5`) |
| 5 | **83/83 verificaciones** | `CONFIRMED` | re-ejecución sin `--json` (para no reescribir el artefacto): `83/83`, `failed=[]`, con los mismos 10 controles y el mismo `first_failure` que el archivo | verifica el JSON, no re-ejecuta el runtime (§2.3) |
| 6 | **10/10 controles, FALSE_SUCCESS=0** | controles `CONFIRMED`; `FALSE_SUCCESS=0` **`NOT_VERIFIABLE`** como medida | 10 mutaciones, todas detectadas, con el mismo `first_failure` que el archivo | el campo se calcula `0 if ok else 1`: mide si el verificador pasó, **no** si el runtime publicó un falso éxito alguna vez (`O4`) |
| 7 | **laboratorio GAP_LAB `ok=true`** | `CONFIRMED` | 6 escenarios (`split`, `quiet`, `stop`, `take` con misma economía; `both`→`GAP_EXIT_AMBIGUOUS`, `partial`→`GAP_NOT_COVERED`), corrupción `REFUSED_AT_LOAD`, concurrencia `REFUSED`; hash `9970d07d…` | salida del propio laboratorio; su vínculo con el runtime es de construcción |
| 8 | **drill 4/4** | `CONFIRMED` | criterios calculados, no literales (`RT-07` exige `comparison.ok` y `>1` sesión; `REC-04` exige `killed=True`; `verdict` exige ambos); `killed=true`, exit 1 del hijo; `differences=[]`; **los digests de datos se reproducen desde el archivo** (§5.4) | `live_orders`, `live_enabled`, `real_model_called` son **literales** (`paper_resume_drill.py:374-375`), no medidas (`O9`) |
| 9 | **14 experimentos kill-resume** | `CONFIRMED` en recuento; `NOT_VERIFIABLE` como cobertura completa de la carrera | 14 intentos, 14 `killed=true`; 12/12 libros legibles en `kill-save` | **los 14 kills cayeron antes del `COMMIT`** (`closed 0→0`, `open 1`): la rama posterior no la ejerció el experimento (`O3`), la cubre esta auditoría (§5.2) |

No se contaron suites solapadas como pruebas independientes: `test_minute_quote_feed` y
`test_subbar_execution` (22) están **dentro** de los 694, y los 90 del WP también. El desglose de la
re-ejecución es 310 (90 WP + 220 paper/risk) + 240 (100 vision + 140 market_data) + 92 (minutos,
lane_vertical, señales, subbar) + 33 (charts, provider, defectos visuales) + 19 (open-phase) =
**694**, sin repetir ningún fichero. La colección por directorios da la misma cuenta:
`vision 334` + `paper 73` + `risk 147` + `market_data 140`.

## 4. Defectos (A4)

### Corregidos y demostrados en este WP

| id | defecto | prueba de que está corregido |
| --- | --- | --- |
| C1 | morir entre rotar `BOOK.json → .prev` y el `replace` dejaba **sólo** `.prev`, y `load()` lo leía como «no hay libro» → sesión plana con exposición | `durable.py:520-525` copia la generación anterior (`_copy_previous`) antes de `os.replace`; `BOOK.json` ausente con `.prev` → `CorruptBook`; tests `test_a_crash_before_the_rename_leaves_the_previous_book_readable`, `test_a_book_that_lost_its_current_generation_is_not_read_as_a_fresh_one` |
| C2 | dos procesos podían relevar el mismo cerrojo muerto a la vez y creerse ambos dueños | guardián `BOOK.lock.takeover` con `O_EXCL`, relectura bajo el guardián y verificación del fichero propio (`durable.py:310-341`); `test_a_second_taker_is_refused_while_one_takeover_is_in_flight` |
| C3 | el generador de evidencias reventaba con `--out` relativo (`relative_to` sobre rutas mixtas) | `collect()` ancla `out` a `REPO`; corrida posterior exit 0 con `--out` relativo |
| C4 | el generador formateaba `None` como duración del check leído de un log (`TypeError`) | imprime `(log)` en vez de un cero falso; corrida posterior exit 0 |
| C5 | `quote_feed_source.py` con 3 avisos reales de ruff (RUF007, RUF100, SIM108) | `ruff` exit 0 |

### Abiertos

| id | severidad | defecto | consecuencia |
| --- | --- | --- | --- |
| **O1** | **alta** | la línea `pythonpath = ["src"]` que ata los tests a este árbol **no está commiteada**; el venv resuelve `trading_bot` al checkout hermano | en un checkout limpio de `HEAD`, con este venv, la suite prueba **otro** árbol; sólo la colección fallaría por casualidad (le falta `gap_recovery`) |
| **O2** | media | la evidencia primaria de «694» es `.tmp/wide-suite.log`, ignorado por git (`*.log`), fuera del WP y sin hash en `RUN_REPORT` | el número no es reproducible como artefacto sin volver a correr la suite; un `git clean -xfd` la borra |
| **O3** | media | `kill-resume` mató siempre **antes** del `COMMIT` | la rama «muere después del `COMMIT`» no estaba medida por la evidencia del WP (sí por esta auditoría, §5.2) |
| **O4** | baja | `VERIFICATION.false_success = 0 if ok else 1` | el nombre promete «ningún falso éxito publicado»; la implementación sólo dice «el verificador pasó» |
| **O5** | baja | `RUNTIME_FILES` omite `vision/ledger.py` (modificado) y todo el resto de imports (`clock`, `guards`, `settings`, `config`, fixture) | el inventario de hashes cubre 7 ficheros, no el grafo de ejecución |
| **O6** | baja | `git diff --check` rc=2 por CRLF en las líneas añadidas de `pyproject.toml` | higiene; cualquier CI que use `--check` fallará |
| **O7** | informativa | `MANIFEST.events_sha256` **no** es el hash del fichero `EVENTS.jsonl`, sino la cabeza de la cadena de eventos | un auditor que compare fichero contra campo verá un «mismatch» que no existe: la cadena se verificó entera (§5.4) |
| **O8** | informativa | sin reconciliación con el exchange, huecos a mitad de corrida, feed de 1 minuto en vivo, retención | capacidades no prometidas en el informe; siguen abiertas |
| **O9** | media | `live_orders`, `live_enabled`, `real_model_called` son constantes escritas por el generador | la afirmación «PAPER, 0 órdenes» se sostiene por **ausencia estática de ruta de orden**, no por una medida del runtime |

## 5. Verificaciones específicas de A4

### 5.1 Recuperación **antes** del `COMMIT`

14/14 intentos de `kill-resume` mataron al hijo con la posición abierta (`closed_before=0`,
`closed_after=0`, `open=1`) y el libro quedó byte-idéntico; la pasada final sin matar produce **un**
cierre y equity `9996.380966197243`. Es la rama «muere antes → se recalcula desde los mismos
minutos». `CONFIRMED`.

### 5.2 Recuperación **después** del `COMMIT` — medida en esta auditoría

La evidencia del WP no la ejercía. Se ejecutó un probe acotado (`.tmp/audit/probe_after_commit.py`,
que usa los fixtures de `test_session_recovery` y **no** toca código del repo):

| paso | resultado |
| --- | --- |
| run-1 (muere con 1 posición abierta) | `open=1`, `closed=0`, barrera `1792530000000` |
| run-2 (hueco + feed prueba el stop) | **1 cierre** `GAP_RECONSTRUCTION`, libro `closed=1`, `open=0`, equity `9996.380966197243` |
| run-3 (mismo libro, mismo hueco y feed) | **0 cierres**, `closed=1`, `open=0`, misma equity, `state_digest` **idéntico** al de run-2, sin bloqueo |

`CONFIRMED`: no hay doble cierre después del `COMMIT`; el libro se reanuda sin volver a cerrar.

### 5.3 Persistencia y ausencia de doble cierre

`CONFIRMED` por tres vías independientes: el probe anterior (§5.2), `no_duplicate_close` y
`open_and_closed_are_disjoint` del verificador sobre cada brazo, y `REC-03` del drill (ids únicos en
el libro final). El `state_digest` de `kill-resume` **no** es igual al de la referencia y el
laboratorio lo declara con las rutas exentas nombradas; la prueba es la comparación campo a campo
(`differences=[]`), no el digest.

### 5.4 Datos de mercado realmente utilizados

`CONFIRMED`, recomputado desde los bytes:

- `bars_sha256` de `DRILL.json` se reproduce agregando `archive/{ETHUSDT,SOLUSDT}.jsonl` con
  `load_bars` + `series_digest`: 144 velas por símbolo, `e230e99d…` y `053c43f3…`, **iguales**;
- `minutes_sha256` coincide con `MANIFEST.symbols[*].sha256` y con el fichero;
- la cadena de eventos del collector se recompuso evento a evento: **3034 eventos, 0 rota**, cabeza
  `b92e5226…` = `MANIFEST.events_sha256`; 10 `GAP` y 10 `GAP_FILLED` (3003 `DUPLICATE_IDENTICAL`,
  438 `FORMING_BAR_IGNORED`, 59 `SETTLE_DEFERRED`).

Cadena temporal (UTC, de `st_mtime`): `archive/` **07:41** → `drill/DRILL.json` **07:44** →
`lab/GAP_LAB.json` **07:49** → log de la suite **08:56** → `RUN_REPORT`/`VERIFICATION` **09:02** →
`FINAL_REPORT` **09:03**. El archivo es anterior al drill, como debe ser; y aun así se comprobó que
los `minutes_sha256` del drill son los de los ficheros actuales.

Límite: que esos minutos vengan del venue lo declara el propio collector (`source:
binance_spot_rest_1m`). No hay firma de terceros sobre `archive/`; la cadena prueba integridad
interna y orden, no origen externo.

### 5.5 Reconciliación con el exchange

`ABSENT` (declarado, no oculto). `reconcile_book` reconcilia el libro **consigo mismo y con el
prefijo del dataset**; no hay cliente de exchange ni ruta de órdenes en `vision/` (`grep` de
`place_order|create_order|submit_order` en `vision/` y `paper/`: sin resultados). `provider.py`
habla con una API de modelo (bearer token), no con un venue.

### 5.6 Estado PAPER y bloqueo de LIVE

- Estático: **no existe** ruta de envío de órdenes en `vision/` ni en `paper/`; el "live" no es una
  bandera que alguien pueda activar en esta cadena. `CONFIRMED`.
- Como **medida**: los campos `live_orders=0`, `live_enabled=false`, `real_model_called=false` son
  literales del generador → `NOT_VERIFIABLE` como observación (`O9`). El proveedor usado en el drill
  y en el laboratorio es de guion (`ReplayProvider`/`ScriptedProvider`), lo que sí es verificable en
  el código y en el `RUN.provider` del runtime.

## 6. Decisión y siguiente acción

**`PARTIAL`.** No es `BLOCKED`: la identidad del código ejecutado está demostrada (20/20 hashes
coinciden y la suite, el verificador, `ruff` y `mypy` se re-ejecutaron verdes sobre esos mismos
bytes). No es `PASS`: el WP no existe en ningún commit, la evidencia primaria de «694» está fuera
del paquete y sin hash, la cobertura de la carrera del `COMMIT` era unilateral, y tres campos que
suenan a medida son constantes.

Ninguna de esas cuatro cosas invalida la recuperación a través de un hueco: el mecanismo se sostiene
en el laboratorio, en el drill y en el probe de §5.2. Lo que no permite es presentar el WP como
«cerrado y anclado» cuando su código sólo está en el árbol de trabajo.

**Siguiente acción técnica (una sola, en este orden):**

1. **Commitear el WP** (código + tests + `pyproject.toml` con `pythonpath`, que es lo que ata los
   tests a este árbol) y anotar el SHA en el informe.
2. Después, regenerar la evidencia **contra ese commit**: copiar el log de la suite dentro de
   `reports/ai-bots/WP-PAPER-QUOTE-GAP-002/` (o hashearlo en `RUN_REPORT`), añadir `vision/ledger.py`
   al inventario, y sustituir los literales `live_*` por una comprobación estática de ausencia de
   ruta de orden, que es la afirmación que de verdad se puede sostener.
3. Sólo entonces la Fase A puede pasar a `PASS`. Nada de esto habilita PAPER integral ni LIVE.

---

### Artefactos de esta auditoría

`GIT_AUTHORITY_AUDIT.md` (este documento) · `GIT_AUTHORITY_AUDIT.json` (mismo contenido, legible por
máquina) · `EVIDENCE_MANIFEST.json` (inventario con sha256, tamaños y rol de cada pieza).

Fuentes primarias consultadas, no citadas de memoria: `git rev-parse/status/diff/log`, los 20 hashes
recomputados, `.tmp/wide-suite.log`, `RUN_REPORT.json`, `VERIFICATION.json`, `lab/GAP_LAB.json`,
`drill/DRILL.json`, `archive/MANIFEST.json` + cadena de `EVENTS.jsonl`, `pyproject.toml` (árbol y
`HEAD`), `.gitignore`, y las re-ejecuciones descritas en §3.
