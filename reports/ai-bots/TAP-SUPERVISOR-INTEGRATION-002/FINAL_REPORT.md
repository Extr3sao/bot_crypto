# FINAL REPORT — TAP-SUPERVISOR-INTEGRATION-002

**Recomendación: `NOT_READY` para `main`.** Todo está integrado, ejecutado y verificado
salvo **una firma**: el veto semanal de pérdidas ahora se libera los lunes a las 00:00 UTC en
vez de no liberarse nunca. Eso es una decisión de política de riesgo, no mía.

---

## 1. Lo que se hizo

Rama aislada `integ/supervisor-002` derivada de `main` (`e67194e7`, que no se ha movido), en
el worktree `ff-wt-integ002`. **No se fusionó la lane**: se copiaron *blobs* de Git, ruta a
ruta, con su hash y su commit de origen registrados. `git rev-list --merges main..HEAD` = 0.

| Commit | Qué |
| --- | --- |
| `f238b632` | `matplotlib` declarado **y fijado** en el lock + test que impide que vuelva a mentir |
| `537e4990` | la rebanada de 47 rutas + 37 tests + la compatibilidad G2 del verificador |
| `b489d488` | contrato de riesgo: paridad con `main` + las tres deltas (46 tests) |
| `HEAD` | G2 completo, B1 forzado, verificador independiente e informes |

## 2. Rutas migradas

**84 rutas, todas con hash** en [ROUTE_MANIFEST.json](ROUTE_MANIFEST.json): 47 de la rebanada
(35 módulos nuevos, 7 modificados, 2 configs, lock/dependencia/ignore) y 37 tests que las
fijan. `tools/route_manifest.py --check` → `PASS` (84). Cuatro son ediciones declaradas, no
copias: `uv.lock` (regenerado), `.gitignore` (acotado), el verificador (G2) y dos tests de
`def_run_016` (cargan un script fuera de la rebanada y se saltan con el motivo).

Los 7 ficheros divergentes no revierten nada de `main`: los 4 commits que `main` tiene de más
tocan 66 rutas y **ninguna** coincide con las 87 del manifiesto
(`evidence/MAIN_ONLY_OVERLAP.txt`).

## 3. Tests

| Conjunto | Resultado |
| --- | --- |
| `tests/unit/paper tests/unit/risk` en **`main`** | **6 failed / 170 passed** |
| `tests/unit/paper tests/unit/risk` en la rama | **2 failed / 220 passed** |
| `tests/unit/ops` | **76 passed** |
| `tests/unit/vision` | **17 failed / 311 passed / 1 skipped** (23 min 44 s) |
| 6 ficheros `tests/unit/research` migrados | **14 failed / 159 passed** |
| contrato de riesgo (nuevo) | **46 passed** |
| B1 (nuevo) | **6 passed** |
| lock/pyproject (nuevo) | **3 passed** (y **3 failed** contra el lock de `main`) |

**Ningún test que pase en `main` falla aquí**; los 2 rojos son subconjunto de los 6 de `main`.
Los 33 restantes están declarados por causa: 15 por un corpus que solo existe en la lane
(`data/quote-feed-1m`), 14 de investigación (corpus/scripts de la lane y un `SystemError` de
Windows en `campaign_lock`, módulo ajeno a la rebanada), 1 que carga un script fuera de la
rebanada (ahora skip), 1 *flaky* que pasa en aislamiento (4,8 s) y falla solo en el orden de la
suite completa, y los 2 preexistentes de `data/rfc048`.

## 4. G1 — contrato de riesgo

**La atribución de la auditoría era incorrecta y corregirla es el hallazgo.** `main` limpio
ya está en **6 failed / 170 passed**, incluidos los dos de
`test_futures_independent_verifier.py`: la causa son hashes obsoletos en
`data/rfc048/PROVENANCE.json` (6 de 7 fuentes no coinciden con los ficheros crudos
commiteados), no `risk/manager.py`. Queda **OPEN_PREEXISTING**; reescribir los hashes
bendeciría una cadena de procedencia que nunca existió.

Lo que la rebanada sí cambia está en [RISK_CONTRACT_DELTA.md](RISK_CONTRACT_DELTA.md): tres
endurecimientos (el broker no inventa un stop; un stop inusable se rechaza en vez de recortarse;
un stop dentro de su coste puede rechazarse, `OFF` por defecto) y **un aflojamiento**: el veto
semanal se reinicia en el lunes UTC. Umbral intacto, probado en el límite, a mitad de semana,
con reloj hacia atrás y tras restaurar estado. **G1 = `OPEN_SIGNOFF`.**

## 5. G2 — verificadores sobre campañas reales

Sobre la campaña real, `paper_supervisor_verify.py` ya no busca `scenarios/SCENARIOS.json`:
un check sin evidencia es `NOT_APPLICABLE` (no falla), una mutación que no puede ejecutarse no
es ni inválida ni detectada, y una mutación que borra la evidencia de su check cuenta como
**detectada**.

| Medida | Valor |
| --- | --- |
| Veredicto | **PASS** (exit 0) |
| Checks | todos PASS; 2 no aplicables |
| Mutaciones aplicables | **10/10 detectadas** |
| `false_success` | **0** |
| Controles negativos | ausente, `live_orders=1`, lock residual, cadena rota → **4/4 FAIL** |

El propio *run* adversarial encontró dos debilidades del verificador, ya corregidas y fijadas:
una secuencia de fences de longitud 1 hacía `reclaim_fences_advance` vacuamente cierta, y
recalcular la aplicabilidad por mutante dejaba que la mutación borrase su propio check.

El verificador de lock ya **no rechaza** su propio esquema: juzga los 33 checks sobre una
campaña real de 3 ciclos y 1 crash. Falla 3 checks que exigen la forma mínima de la campaña
(≥5 recuperaciones, ambos sitios de crash, carrera de reclaim), así que **G2 = CLOSED** para el
supervisor y **PARTIAL** para el lock hasta que termine la campaña completa.

## 6. G3 / B1 — la ventana del lock

Causa raíz, por construcción: el lock se crea con `os.link(tmp, path)`, así que el registro
está completo en el instante en que existe. Donde no hay hard links, el *fallback* crea el
fichero y **después** escribe: un crash entre las dos syscalls deja un fichero vacío.
`_normalise("")` → `EMPTY` → `LOCK_UNATTRIBUTED`, que se rechaza y **no se borra** — el síntoma
histórico exacto.

`tests/unit/ops/test_lock_attribution_b1.py` (6 passed) fuerza el caso: 200 adquisiciones sin
observar nunca un lock vacío o parcial; el *fallback* también escribe completo; y con
`os.link` y `os.write` forzados a fallar queda el lock vacío y el siguiente escritor lo rechaza
sin tocarlo. **G3 = `DIAGNOSED`**: cerrado donde hay hard links (medido aquí), rechazado con
seguridad donde no.

## 7. B2, B3, `finished_without_locks`, timeout

- **B3 — FIXED.** Reproducido primero: `uv lock --check` exit 1 y `uv sync --frozen` exit **0**
  con `ModuleNotFoundError: matplotlib`. Después del `uv lock`: `--check` 0, `--frozen` 0,
  `matplotlib 3.11.2` importable. Un test lee ambos ficheros sin red y **falla 3/3 contra el
  lock de `main`**.
- **B2 — `NOT_REAUDITED`.** `scripts/verify_claims.py` no existe ni en `main` ni en la lane.
- **`finished_without_locks` — `NOT_REPRODUCED`.** Aquí fue `true` y exit 0. El flag es el
  booleano de un `wait_for` (¿algún poll vio RECOVERED sin locks antes del timeout?), no un
  veredicto: un hijo que suelta el último lock después del timeout produce `false` con
  `final.locks` vacío, justo la combinación que vio la auditoría. Recomendación: reevaluarlo
  tras `supervisor_process.wait()` (no aplicada, para no cambiar un productor que aquí
  funcionó).
- **Suite completa — `NOT_TESTED`.** Los subconjuntos medidos suman 27 minutos; no se intentó
  la suite entera y no se declara.

## 8. Campaña PAPER real

`paper_supervisor_campaign.py run --crashes 1`, sin credenciales, datos públicos.

| Hecho | Valor |
| --- | --- |
| Supervisor | `STOP_COMPLETED`, exit 0 |
| Ciclos | `[1, 2, 3, 4, 5]` |
| Crash → recuperación | 1 episodio (`after_cycle`) |
| Estado final | `RECOVERED` |
| Cadena | `INTACT`, 13 líneas (recomputada) |
| Locks al final | **0** |
| `live_orders` | **0** en todas las filas |
| `finished_without_locks` | `true` |
| Verificador | PASS, 10/10, `false_success 0` |

## 9. Verificador independiente

`tools/independent_verify.py` no importa nada de `trading_bot` ni del verificador: reimplementa
la canonicalización, rehashea cada ruta y artefacto, parsea los logs y comprueba Git.
**7/7 claims PASS, 0 FAIL, 0 UNKNOWN, `false_success 0`** (exit 0). Su autocontrol exige que el
claim de campaña falle sobre la copia manipulada y **falla** (`S1`), así que no es ciego por
construcción.

## 10. Defectos abiertos

1. **G1/D** — el veto semanal se libera; falta la firma del risk-manager.
2. **G2/e** — campaña completa de lock (6 sitios de crash + carreras) en ejecución.
3. **B2** — sin reauditar (script inexistente).
4. **`finished_without_locks`** — sin reproducir; ruta de código identificada.
5. **`data/rfc048`** — procedencia obsoleta preexistente en `main` (2 tests rojos).
6. 16 fallos de visión atados a datos (y 1 flaky) + 14 de investigación: declarados, ninguno
   en la ruta de ejecución del supervisor.
7. Sin ninguna afirmación de rentabilidad; la admisión sigue `NO_GO` y el ledger no se tocó.

**`FALSE_SUCCESS = 0`** en todas las afirmaciones emitidas: cada PASS tiene su artefacto y su
exit code, y lo que no se ejecutó figura como `NOT_TESTED`, `PARTIAL`, `NOT_REPRODUCED` o
`NOT_REAUDITED`.
