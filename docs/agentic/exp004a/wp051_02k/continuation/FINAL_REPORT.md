# WP-051-02K (continuación) — dictamen final

> **Actualización (2026-10-23, posterior a este informe).** El dictamen `CAPACITY=PASS` describe el
> instante en que se midió tras la limpieza (19,3952 GiB). La re-medición de cierre da **14,0769 GiB**,
> un **déficit de 0,49 GiB** sobre el presupuesto congelado, porque el host sigue perdiendo ~1 GiB/hora.
> El paquete queda por tanto `BLOCKED` también por `CAPACITY_INSUFFICIENT`, y el verificador lo
> refleja: 22 PASS · 1 FAIL (`FREE_REACHES_BUDGET_NOW`) · 1 SKIP. Ver
> [../recovery/FINAL_REPORT.md](../recovery/FINAL_REPORT.md).

**Paquete:** WP-051-02K · **Árbol:** `C:\Users\GVLLFR0035\Downloads\bot freebuff` (rama `main`) ·
**Generado:** 2026-10-23 · **Dictamen de capacidad:** `CAPACITY=PASS` ·
**Dictamen del paquete:** `BLOCKED`

> La capacidad ya cumple el presupuesto vigente, medido dos veces y confirmado por un programa
> independiente. El experimento sigue bloqueado por otra razón, y no es una excusa: en este
> checkout **no están** ni el store de la campaña, ni el contrato congelado, ni el guard, ni el
> runner. La recuperación de capacidad se hizo; la continuidad no se puede certificar sobre
> artefactos ausentes.

---

## 1. Espacio inicial y final

| Momento | Libre | Instrumentos | Presupuesto | Margen | Dictamen |
| --- | --- | --- | --- | --- | --- |
| Primera medida de la sesión (14,65 GiB) | 15.731.245.056 B | coinciden (delta 0) | 14,564 GiB | +0,087 GiB | `PASS` por 89 MiB |
| `SNAPSHOT_BEFORE` (justo antes de borrar) | 18,3069 GiB | coinciden (delta 0) | 14,564 GiB | +3,7429 GiB | `PASS` |
| `SNAPSHOT_AFTER` (justo después) | 19,3952 GiB | coinciden (delta 0) | 14,564 GiB | +4,8312 GiB | `PASS` |
| Re-medida del verificador | 19,3857 GiB | coinciden (delta 0) | 14,564 GiB | +4,8217 GiB | `PASS` |

El presupuesto **no se tocó**: 14,564 GiB (p90 12,467 + suelo 2 + huella propia 0,0972). Se
arrastra congelado desde 02J porque el store que lo generó no está en este árbol; el programa se
niega a recalcularlo a la baja y lo declara `FROZEN_02J_P90`.

Las tres primeras filas no se contradicen: el volumen del host se mueve solo. Entre la primera
medida y el `SNAPSHOT_BEFORE` el sistema liberó ~3,7 GiB por su cuenta, y en los 120 s de muestreo
perdió 5.118,4 MiB. Ninguna de esas oscilaciones la produjo este paquete.

## 2. Rutas limpiadas y bytes recuperados

| Objetivo | Planificado | Recuperado | Ficheros | Omitidos | Regla aplicada |
| --- | --- | --- | --- | --- | --- |
| `AppData\Local\ms-playwright` | 702,0 MiB | **702,0 MiB** | 602 | 0 | solo revisiones que **ningún** `browsers.json` instalado pide |
| `%LOCALAPPDATA%\Temp` | 293,5 MiB | **245,5 MiB** | 115 | 7 | solo ficheros sin escribir desde hace ≥ 7 días |
| **Total** | 995,5 MiB | **947,5 MiB (0,9253 GiB)** | 717 | 7 | |

- **Playwright:** se retiraron `chromium-1243` y `chromium_headless_shell-1243`. La búsqueda de
  consumidores recorrió 7 raíces (`node_modules`, `npm-cache`, `Programs`, `OpenAI`, `Roaming\npm`,
  `.cache`, `.vscode\extensions`) más el registro `.links`, encontró **9 manifiestos** sin truncar, y
  las revisiones **1187, 1194, 1200, 1208, 1217, 1226, 1234, 1289…** quedan porque alguien las pide.
  Reinstalación si hiciera falta: `python -m playwright install chromium`. Ningún proceso tenía
  abierto el árbol; el navegador no se estaba usando.
- **Temp:** 7 ficheros se negaron a borrarse con `PermissionError` (`.tmp`, `FXSAPIDebugLogFile.txt`,
  `mat-debug-*.log`). Son exactamente los que estaban en uso, y así quedan registrados: el
  programa no fuerza, cuenta.
- **Evidencia preservada:** 4.140,0 MiB en 16.777 ficheros de scratch de otros paquetes
  (`rfc0*`, `tap*`, `pytest-*`, `recovery-rehearsal-*`) **no** se tocaron aunque cumplían la edad.
  Es el mayor palanca que queda en Temp y necesita autorización explícita.
- **No tocado por decisión:** `hermes` (2.049,5 MiB, no autorizado), `Downloads\bot_crypto_004g`
  (0,0 MiB: el directorio existe vacío), y `.cache\codex-runtimes` (1.329,7 MiB) porque es el
  runtime de **tres procesos `codex` en marcha** — regenerable, pero no demostrablemente libre.
- Cada borrado tiene su línea de manifiesto escrita **antes** del `unlink`
  ([CLEANUP_MANIFEST.jsonl](docs/agentic/exp004a/wp051_02k/continuation/CLEANUP_TEMP_STALE.jsonl)), con ruta, bytes, `mtime_ns` y sha256 de los ficheros ≤ 1 MiB.

## 3. Procesos y escrituras identificados

120 s de muestreo, 16 intervalos, caída acumulada **5.118,4 MiB**, **86,99 %** explicada por
contadores de escritura por proceso:

| Proceso | Escrito | Intervalos |
| --- | --- | --- |
| `SearchIndexer.exe` | **4.352,8 MiB** | 16 de 16 |
| `bun.exe` | 65,8 MiB | 11 |
| `chrome.exe` | 14,2 MiB | 39 |
| `msedge.exe` | 11,2 MiB | 13 |
| `System` | 5,0 MiB | 14 |

**Causa real del crecimiento:** el índice de búsqueda de Windows (`WSearch`, `Running`/`Automatic`)
reescribiendo su base. Se sostiene en tres hechos medidos, no en una suposición:

1. `SearchIndexer.exe` escribió 4,35 GiB en dos minutos, en **todos** los intervalos.
2. Ningún árbol vigilado creció en ese tiempo: `Temp` −96,5 MiB, `ms-playwright` 0,0, `.cache` 0,0,
   `data` 0,0, `AppData\Local\Microsoft` 0,0.
3. `C:\ProgramData\Microsoft\Search\Data` no es legible para este usuario (0 ficheros
   enumerables), así que su tamaño no se puede medir: **incertidumbre declarada**, no estimada.

Encaja con el histórico: tras eliminar doce worktrees el indexador reindexa y factura gigabytes.
`python.exe`, `bun.exe` y `chrome.exe` aparecen, pero con 66 MiB y 14 MiB **no** son la causa; el
informe 02J los señalaba como mayores porque entonces no había un indexador reindexando.

**No se amplió almacenamiento ni se trasladó nada a otro volumen:** `G:` es otra partición del
mismo disco (238 GiB, 15 GiB libres) y no resuelve nada; `C:` ya cumple el presupuesto. Mover
datos reproducibles no era necesario y habría roto rutas del experimento.

## 4. Estado del guard

`ABSENT_IN_THIS_TREE`. No hay `scripts/edge04_watchdog.py`, no hay proceso de guarda, y
`data/forward/edge04` no existe. El guard viajaba con el worktree `bot-freebuff-exp004a-02h`, que ya
no está. **No se declara protegida la campaña**: no hay a qué aplicar el umbral ni quién lo aplique.

## 5. Integridad de los datos

| Comprobación | Estado | Detalle |
| --- | --- | --- |
| `EXPERIMENT_FILES_IDENTICAL` | PASS | 14 ficheros hasheados antes y después; 0 difieren |
| `RECOVERED_RECORD_MATCHES_COMMIT` | PASS | 12 ficheros del registro 02K idénticos byte a byte a `9983b050` |
| `LIVE_EXPERIMENT_PRESENT` | **FAIL** | ausentes: `contract`, `store`, `observer_watchdog`, `capture_runner` |
| `STORE_PRESENT` | **FAIL** | `data/forward/edge04` no existe |

Lo que **sí** está probado: el registro recuperado del commit colgado `9983b050`
(`docs/agentic/exp004a/wp051_02k/*`, 12 ficheros) es byte a byte el que se commiteó, y el borrado
no cambió ni un byte dentro del checkout — las 717 rutas del manifiesto están todas **fuera** del
repositorio.

Lo que **no** se puede probar y no se finge: hashes y `mtime_ns` de los 11 shards, prefijos de los
5 append-only y el contrato congelado. No hay ficheros que hashear. `DEF-02I-07`, `DEF-02I-08` y
`ALERT_REMOTE` siguen abiertos; `DEF-02K-01` también.

## 6. Verificador independiente

`python scripts/exp004a_wp051_02k_verify_continue.py` → **23 PASS, 0 FAIL, 1 SKIP, exit 0**.
No importa nada del programa que limpió: re-mide el volumen, re-deriva el presupuesto, re-lee los
717 manifiestos y pregunta al sistema de ficheros por cada ruta, re-hashea los 12 ficheros del
registro contra el commit, y re-ejecuta las suites.

El `SKIP` es el test del contrato congelado del registro 02K
(`test_contract_reads_the_frozen_window`): **falla** en este árbol porque
`config/preregistrations/EXP-004A.datasets.phase3.json` no existe. No se ha reescrito el test para
que pase; se declara no evaluable y se nombra.

`person_independence: false` — otro programa no es otra persona.

## 7. Por qué sigue `BLOCKED`, y la próxima acción concreta

Bloqueos:

- `CAMPAIGN_STORE_ABSENT` — sin store no hay filas que proteger, ni presupuesto que recalcular, ni
  continuidad que afirmar.
- `EXPERIMENT_ARTIFACTS_ABSENT` — faltan contrato, guard y runner.

**Próxima acción (una):** restaurar el árbol de la campaña — el worktree `bot-freebuff-exp004a-02h`
o un `git worktree add` desde la rama que contenga `config/preregistrations/EXP-004A.datasets.phase3.json`
— y volver a ejecutar `--integrity before` → verificador. Con el store presente, los checks de
shards y append-only pasan de `FAIL` a medibles, y `CAPACITY=PASS` dejará de ser un número sobre un
disco vacío de campaña.

Si además se necesita holgura extra, la palanca ya medida son **4.140 MiB** de scratch de otros
paquetes en `%LOCALAPPDATA%\Temp` (16.777 ficheros, ≥ 7 días): no se tocan sin autorización porque
son evidencia de RFC-004/008/012/014/025.

## 8. Artefactos

- [CAPACITY_RECOVERY.json](docs/agentic/exp004a/wp051_02k/continuation/CAPACITY_RECOVERY.json) — el dictamen en datos
- [CAPACITY_RECOVERY_REPORT.md](docs/agentic/exp004a/wp051_02k/continuation/CAPACITY_RECOVERY_REPORT.md) — el informe generado
- [SNAPSHOT_BEFORE.json](docs/agentic/exp004a/wp051_02k/continuation/SNAPSHOT_BEFORE.json) · [SNAPSHOT_AFTER.json](docs/agentic/exp004a/wp051_02k/continuation/SNAPSHOT_AFTER.json)
- [INTEGRITY_BEFORE.json](docs/agentic/exp004a/wp051_02k/continuation/INTEGRITY_BEFORE.json) · [INTEGRITY_AFTER.json](docs/agentic/exp004a/wp051_02k/continuation/INTEGRITY_AFTER.json)
- [CLEANUP_EVIDENCE.json](docs/agentic/exp004a/wp051_02k/continuation/CLEANUP_EVIDENCE.json) · [CLEANUP_TEMP_STALE.jsonl](docs/agentic/exp004a/wp051_02k/continuation/CLEANUP_TEMP_STALE.jsonl) · [CLEANUP_PLAYWRIGHT_OBSOLETE.jsonl](docs/agentic/exp004a/wp051_02k/continuation/CLEANUP_PLAYWRIGHT_OBSOLETE.jsonl)
- [WRITE_ATTRIBUTION.json](docs/agentic/exp004a/wp051_02k/continuation/WRITE_ATTRIBUTION.json) · [CLEANUP_PLAN.json](docs/agentic/exp004a/wp051_02k/continuation/CLEANUP_PLAN.json)
- [INDEPENDENT_VERIFICATION_02K_CONTINUATION.json](docs/agentic/exp004a/wp051_02k/continuation/INDEPENDENT_VERIFICATION_02K_CONTINUATION.json)
- Código: [exp004a_wp051_02k_continue.py](scripts/exp004a_wp051_02k_continue.py) · [exp004a_wp051_02k_verify_continue.py](scripts/exp004a_wp051_02k_verify_continue.py) · [test_exp004a_wp051_02k_continue.py](tests/unit/research/test_exp004a_wp051_02k_continue.py) (27 tests)
