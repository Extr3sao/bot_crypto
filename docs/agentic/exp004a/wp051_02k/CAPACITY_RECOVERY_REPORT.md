# WP-051-02K — recuperación de capacidad y continuidad operativa

**Paquete:** WP-051-02K · **Experimental:** EXP-004A fase 3 (EDGE04) · **Fecha:** 2026-10-23 ·
**Dictamen:** `BLOCKED` (capacidad `INSUFFICIENT`; continuidad `PASS`; evidencia `INTACT`)

> El paquete anterior dejó la pregunta abierta: el disco no llega al presupuesto que el propio
> observador mide. Este paquete vuelve a medir con dos instrumentos, inventaría el disco entero
> —no sesenta rutas— y convierte el déficit en una petición exacta, reversible y sin
> administrador. No borra un byte ajeno: **libera 61,5 MB propios y devuelve una lista de 5 rutas,
> 14,16 GiB, con riesgo y procedimiento de vuelta.**

---

## 1. Identidad del árbol

| Campo | Valor |
| --- | --- |
| Worktree | `C:\Users\GVLLFR0035\Downloads\bot-freebuff-exp004a-02h` |
| Rama | `wp/exp004a-051-02h` |
| HEAD | `7f9758d9bbff55dd2cbc01a1146f8a2ed5d49b77` |
| Store de la campaña | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04` (**14 MB**) |
| Contrato | `config/preregistrations/EXP-004A.datasets.phase3.json` — `git diff` vacío |

## 2. Capacidad: antes y después, con dos instrumentos

| Momento | Libre | Uso | Estado | Déficit p90 |
| --- | --- | --- | --- | --- |
| `--before` (13:39Z) | **1,4558 GiB** | 99,39 % | `CRITICAL` | **13,108 GiB** |
| `--after` (13:46Z) | **1,4985 GiB** | 99,37 % | `CRITICAL` | **13,066 GiB** |
| Verificador (13:52Z) | 1,49 GiB | — | `CRITICAL` | 13,066 GiB |

`shutil.disk_usage` y `GetDiskFreeSpaceExW` coinciden **byte a byte** en las tres lecturas
(`instruments_agree: true`, delta 0). La diferencia antes/después (**+42,7 MiB**) es mayor que lo
eliminado (58,7 MiB) solo porque el volumen se movió por otras manos mientras corría el paquete: lo
que este paquete **puede** atribuirse son los 61.520.363 B que borró, no el saldo.

**Lo importante no es la cifra sino la dirección:** a las 13:39Z había 1,4558 GiB y a las 11:32Z
había 3,2519 GiB. En dos horas el host consumió **1,8 GiB**. El margen de 8 días que publicó 02J
se está gastando ahora.

## 3. El presupuesto, recalculado con las lecturas que existen hoy

| Medida | 02J (11:32Z) | 02K (13:39Z) |
| --- | --- | --- |
| Días completos de histórico | 11 | **11** |
| Caída intradía p50 | 6,96 GiB | 6,96 GiB |
| **Caída intradía p90** | 12,467 GiB | **12,467 GiB** |
| Caída máxima observada | 14,583 GiB | 14,583 GiB |
| Crecimiento propio (90 d) | 0,0968 GiB | **0,0967 GiB** |
| Suelo de protección | 2 GiB | **2 GiB** (intacto) |
| **Requerido (p90 + suelo + propio)** | 14,565 GiB | **14,564 GiB** |

El presupuesto no se movió (**−1 MiB**, por el crecimiento propio recalculado). El histórico de
lecturas no cambió lo suficiente: 11 días completos, hoy aún incompleto. **No se ha tocado el
criterio**: sigue siendo p90 + suelo + huella propia, y el máximo se publica al lado pero no se usa.

### DEF-02K-01 — el veredicto de 02J no podía decir `SUFFICIENT` nunca

`capacity()` de 02J añade `and not refused_total` al veredicto. `refused_total` cuenta **167**
rechazos históricos inmutables, así que el veredicto estaba estructuralmente condenado: ni con 50
GiB libres habría devuelto `SUFFICIENT`. Es un defecto de composición (un hecho pasado dentro de una
decisión en presente), no del umbral. **02K no lo arregla cambiando el criterio**: separa las dos
cosas — el presupuesto decide la capacidad, los rechazos se reportan como historia — y lo registra
como defecto abierto. Aun así el resultado es `INSUFFICIENT` por aritmética pura: 1,5 < 14,56.

## 4. Dónde están los 236 GiB

`VOLUME_INVENTORY.json`: **9.155 filas** medidas en 139 s, sin truncamientos, saltando *junctions*
(`AppData` apunta a sí mismo; seguirlas no termina nunca). La partición de primer nivel explica
**230,38 GiB de 236,09 (97,58 %)**; los **5,70 GiB restantes** no son un error de redondeo: están en
árboles que este proceso no puede leer (`System Volume Information`, `Recovery`, ficheros
bloqueados), es decir, instantáneas y áreas protegidas.

| Ruta | Tamaño | Quién |
| --- | --- | --- |
| `C:\Users` | 131,80 GiB | usuario |
| `C:\Windows` | 33,93 GiB | sistema |
| `C:\pagefile.sys` | **26,59 GiB** | Windows (memoria virtual) |
| `C:\Program Files` | 20,39 GiB | sistema |
| `C:\Program Files (x86)` | 9,20 GiB | sistema |
| `C:\ESD` | 4,58 GiB | staging de Windows Setup |
| `C:\ProgramData` | 1,99 GiB | sistema |
| `C:\tmp` | 1,48 GiB | sesiones de este repo (**activo**) |

Dentro del perfil, los cinco mayores consumidores —ninguno de ellos mencionado por 02J— son:

| Ruta | Tamaño | Naturaleza |
| --- | --- | --- |
| `AppData\Local\Microsoft` | 13,19 GiB | Edge 4,41 · OneDrive 5,55 · Office/Teams |
| `AppData\Local\Programs` | 7,03 GiB | aplicaciones instaladas (VS Code 3,09) |
| `AppData\Local\Temp` | **6,59 GiB** | scratch de procesos |
| `AppData\Roaming\Msty` | **6,35 GiB** | app de escritorio con modelos locales |
| `AppData\Local\wsl` | 6,16 GiB | imagen de la distro |

Y el hallazgo que ordena todo lo demás:

| Medida | Valor |
| --- | --- |
| Store completo de la campaña | **14 MB** |
| Crecimiento propio medido | **1,15 MB/día** |
| Huella propia en los 90 días | **0,0967 GiB** |

**La campaña no es el consumidor: es el 0,04 % del problema.** El host mueve entre 4 y 15 GiB al día
sin que la campaña escriba nada — 02J ya lo midió con contadores por proceso (`python.exe` 1,35 GiB,
`bun.exe` 452 MiB, `SearchIndexer.exe` 290 MiB, `chrome.exe` 246 MiB) y **ninguno de los árboles
vigilados crecía**. Este paquete confirma la otra mitad: el espacio que se podría recuperar no está
en la campaña sino en cachés de herramientas y en árboles del usuario.

## 5. Lo que sí se liberó: 61,5 MB, y todo era mío

`CLEANUP_EVIDENCE.json`: **209 directorios**, **61.520.363 B (58,7 MiB)**, todos cachés
byte-compiladas sin seguimiento de Git, en este worktree y en el repo de la campaña. Los cinco
mayores: `.mypy_cache` 18,3 MiB · `tests/unit/research/__pycache__` 8,4 MiB ·
`scripts/__pycache__` 5,9 MiB · `research/__pycache__` 1,4 MiB · `tests/unit/vision/__pycache__`
1,3 MiB.

No es una limpieza simbólica ni una limpieza grande: es **exactamente lo que este paquete puede
tocar sin permiso**, y se declara como tal. El `--clean` consulta `git ls-files` antes de borrar y
registra en `kept` lo que se negó a tocar.

## 6. Lo que no se liberó: 14,16 GiB en cinco rutas, sin administrador

`AUTHORISATION_REQUEST.json`. Ordenado por coste de recuperación: primero lo que se regenera solo,
después lo que se rehace a mano, y nunca un cambio de sistema mientras haya alternativa.

| # | Ruta | Tamaño | Riesgo | Recuperación | Admin |
| --- | --- | --- | --- | --- | --- |
| 1 | `%LOCALAPPDATA%\ms-playwright` | 3,27 GiB | otros proyectos re-descargan en su próximo run | `python -m playwright install chromium` | no |
| 2 | `%LOCALAPPDATA%\hermes` | 2,00 GiB | el runtime del agente se reconstruye al usarlo | reinstalar/re-ejecutar la herramienta | no |
| 3 | `C:\Users\GVLLFR0035\.cache` | 1,30 GiB | se rellena sola con el uso | re-ejecutar la herramienta | no |
| 4 | `%LOCALAPPDATA%\Temp` | 6,59 GiB | una ejecución interrumpida pierde su salida; los ficheros abiertos se niegan a borrarse | ninguna: el scratch no tiene origen por diseño | no |
| 5 | `Downloads\bot_crypto_004g` | 0,99 GiB | se pierden artefactos de un experimento previo | `git bundle create X.bundle --all` + `git archive` | no |

**Total: 14,16 GiB contra un objetivo de 14,066** (déficit 13,066 + 1 GiB de holgura, para no
volver a pedir mañana). Margen: **+0,094 GiB**. Ningún elemento requiere elevación, ninguno es un
documento, ninguno es un sistema.

### Lo que se midió y deliberadamente **no** se pidió

| Ruta | Tamaño | Por qué no |
| --- | --- | --- |
| `C:\pagefile.sys` | 26,59 GiB | cambio de sistema + reinicio; solo si nada más cubre el hueco |
| `AppData\Local\wsl` | 6,16 GiB | exportar exige 6 GiB que ahora no existen: **la recuperación no cabe en el disco que hay que liberar** |
| `C:\ESD` | 4,58 GiB | rompe un upgrade pendiente; requiere administrador |
| `AppData\Roaming\Msty` | 6,35 GiB | estado de app: modelos locales, no caché demostrada |
| `AppData\Local\Microsoft` | 13,19 GiB | perfiles de Edge/OneDrive: sesiones y borradores sin sincronizar |
| `Downloads` (raíz) · `OneDrive` · `Documents` · `Desktop` | 28,69 + 19,50 GiB | **documentos del usuario: no son una decisión de capacidad** |

`NEVER_OFFER` los excluye por ruta, no por tamaño: un árbol de 66 GiB no se convierte en candidato
por ser grande. Y `is_experiment_worktree()` exige que el árbol sea un worktree Git de esta familia
antes de proponerlo: `Deures Dylan` (0,79 GiB, deberes) quedó fuera en cuanto el filtro se aplicó.

## 7. Escrituras no esenciales: el umbral operativo ya se cruzó

| Hecho | Evidencia |
| --- | --- |
| Suelo de protección del guard | **2 GiB** — intacto (`health.json`, módulo del guard) |
| Aviso | 5 GiB — intacto |
| Libre ahora | **1,50 GiB < 2 GiB** → por debajo del suelo |
| Ticks rechazados | **167** históricos, **29 hoy**, el último `13:40:55Z` con 1.547.677.696 B |
| Escrituras de este paquete | JSON de KB; 58,7 MiB **borrados**, 0 MB añadidos al store |

El guard ya está haciendo lo que debe: **rechaza ticks antes que escribir sin espacio**. No hay que
inventar un umbral nuevo — existe y está actuando. Lo que este paquete añade es la prueba de que la
campaña está en ese estado *ahora*, con la hora del último rechazo, en vez de una proyección.

## 8. La campaña no se movió

`STORE_INTEGRITY.json` → **19/19 PASS, 0 FAIL**, comparado antes/después del paquete:

| Control | Resultado |
| --- | --- |
| `runs.jsonl`, `slots.jsonl`, `alerts.jsonl`, `ALERT_LEDGER.jsonl`, `WATCHDOG_EVENTS.jsonl` | prefijo intacto (append permitido, reescritura detectada) |
| 11 shards `daily/*.json` | sha256 **y** `mtime_ns` idénticos |
| `health.json`, `coverage.json`, `resource_budget.json` | contrato idéntico (suelo, aviso, presupuesto declarado) |
| Filas re-fetcheadas | **0** |
| Filas re-timbradas | **0** |
| Contrato (`git diff`) | vacío; ventana 90 d, 6.480 filas, suelo 0,9 |

El comparador distingue *añadir* de *reescribir*: un hash completo fallaría en cada tick y se
acabaría desactivando la comprobación. Se compara el **prefijo** que existía antes, y se exige que el
fichero no encoja.

## 9. Pruebas y verificación independiente

`TEST_EVIDENCE.json` — `pytest tests/unit/research/test_exp004a_wp051_02k.py -q`:
**32 passed, exit 0**, 0,58 s, suite sha256 `a0e78131e12b…`. Cubren, entre otras cosas: que un PASS
exige el presupuesto completo; que el p90 es el presupuesto y el máximo solo se publica; que un
rechazo es historia y no una decisión en presente; que un append conserva el prefijo y una
reescritura, un encogimiento o un shard movido se detectan; que un árbol ajeno nunca es
`SAFE_OWNED`; que un documento del usuario nunca es candidato; que un junction no se recorre; y que
la petición no cuenta dos veces un padre y su hijo.

`INDEPENDENT_VERIFICATION_02K.json` — programa aparte, sin importar el constructor: vuelve a medir el
volumen con sus dos instrumentos, **re-deriva el presupuesto del log del observador**, re-hashea los
shards write-once, comprueba los prefijos, re-ejecuta la suite y lee el commit de 02J en Git.

## 10. Defectos que siguen abiertos

| Defecto | Estado | Por qué no se cierra aquí |
| --- | --- | --- |
| `DEF-02I-07` | **OPEN** | `LogonType=Interactive` sigue sin probarse: hace falta administrador |
| `DEF-02I-08` | **OPEN** | el directorio `tests/unit/research` sigue roto por un import preexistente |
| `ALERT_REMOTE` | **OPEN** | sin webhook, sin SMTP: una avería nocturna se registra, no se entrega |
| `DEF-02K-01` | **OPEN** | el veredicto de 02J mezclaba rechazos históricos con capacidad presente |

## 11. Dictamen

**`BLOCKED`.** `capacity=INSUFFICIENT` (1,4985 GiB contra 14,564; déficit **13,066 GiB**),
`continuity=PASS` (19/19 controles, 0 re-fetch, 0 re-timestamp), `contract=UNCHANGED`,
`tests=PASS` (32/32), `verification=PASS`.

`CAPACITY=PASS` exige que el volumen cumpla el presupuesto con medición independiente. No lo cumple
y no puede cumplirlo con lo que este paquete tiene permiso de tocar: los 61,5 MB propios son el
0,5 % del déficit. **El arreglo existe, está medido, es reversible y no necesita administrador —
necesita que su dueño diga que sí.**

## 12. Reproducción

```bash
cd "/c/Users/GVLLFR0035/Downloads/bot-freebuff-exp004a-02h"
PY="/c/Users/GVLLFR0035/Downloads/bot freebuff/.venv/Scripts/python.exe"

"$PY" scripts/exp004a_wp051_02k_capacity.py --before
"$PY" scripts/exp004a_wp051_02k_capacity.py --inventory      # ~140 s, 9.155 filas
"$PY" scripts/exp004a_wp051_02k_capacity.py --clean          # solo cachés propios sin seguimiento
"$PY" scripts/exp004a_wp051_02k_capacity.py --after          # 19/19 de integridad del store
"$PY" scripts/exp004a_wp051_02k_capacity.py --report
"$PY" scripts/exp004a_wp051_02k_capacity.py --final
"$PY" -m pytest tests/unit/research/test_exp004a_wp051_02k.py -q     # 32 passed
"$PY" scripts/exp004a_wp051_02k_verify.py                    # 0 FAIL
```

Artefactos: `SNAPSHOT_BEFORE.json`, `SNAPSHOT_AFTER.json`, `VOLUME_INVENTORY.json`,
`CLEANUP_EVIDENCE.json`, `STORE_INTEGRITY.json`, `CAPACITY_RECOVERY.json`,
`AUTHORISATION_REQUEST.json`, `TEST_EVIDENCE.json`, `INDEPENDENT_VERIFICATION_02K.json`,
`FINAL_REPORT.json`.
