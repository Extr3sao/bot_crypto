# RUN_REPORT — WP-ECONOMIC-RECOVERY-002

Registro operativo de la ejecución. La lectura razonada está en
[`FINAL_REPORT.md`](FINAL_REPORT.md); los números, en [`RUN_REPORT.json`](RUN_REPORT.json),
que **se deriva de los artefactos** con `scripts/wp_eco002_report.py` (no se teclean a mano).

## Entorno

| campo | valor |
| --- | --- |
| rama | `repro/economic-recovery-002` |
| base | `e67194e7` |
| commits propios | `eb53e631`, `64fa5112`, + commit de entregables |
| Python | 3.11.15 · pytest 9.1.1 |
| SO | Windows 10 (Git Bash), `core.autocrlf` **system=true** — el clon se hace con `-c core.autocrlf=false` para medir el repo y no la configuración de la máquina |

## Pasos ejecutados

| # | comando | resultado |
| --- | --- | --- |
| 1 | `git archive`/`git clone` de `e67194e7` + lectura de los entregables del WP-001 | 21 nodos "clean-only", método del WP-001 identificado como defectuoso |
| 2 | `build_strategy_admission.py --check` | exit **1**: digest registrado `5f794c36…` no coincide con el fichero ni con la única revisión commiteada de la matriz (`4e15882c…`) |
| 3 | `build_strategy_admission.py` (rebuild tras corregir `newline="\n"` y comparación por bytes) | **1 línea de diff**; payload idéntico salvo `_sources`; `--check` exit **0** |
| 4 | `tests/unit/research/test_strategy_admission_ledger.py` (nuevo) | 4 passed |
| 5 | `test_rfc047_windows_evidence.py` con `build_runtime(persist=False)` | artefacto versionado **sin cambios** de SHA-256 antes/después |
| 6 | `wp_eco002_reproducibility.py --phase working` | 104 nodos, **0** ficheros versionados reescritos de 2018 hasheados |
| 7 | `--phase clone` (clone real en `64fa5112`) | 104 nodos, **mismo conjunto** que el árbol; `rewritten=0` |
| 8 | `--phase healthy` | 447 passed, exit 0 |
| 9 | `--phase focused` (los 21 nodos, por id) | 21/21 en árbol y 21/21 en clon |
| 10 | `--phase assemble` | `REPRODUCIBILITY_COMPARISON.json`: `only_working=0`, `only_clone=0` |
| 11 | `wp_eco002_anchor.py` | ancla reconstruida; 0/6 entradas del builder de la matriz presentes |
| 12 | `wp_eco002_dependencies.py` | 19 rutas ausentes, ninguna versionada, 3 clases |
| 13 | `wp_eco002_verify.py` | **19 PASS · 0 FAIL · 0 NOT_ASSESSED**, exit 0 |

## Ficheros propios (los hashea [`MANIFEST.json`](MANIFEST.json))

Evidencia: `REPRODUCIBILITY_COMPARISON.{json,md}`, `ANCHOR_REPAIR.json`,
`DECLARED_DEPENDENCIES.json`, `INDEPENDENT_VERIFICATION.json`, `MANIFEST.json`,
`parts/{working,clone,healthy,focused}.json`, `parts/clone_dependency_tracebacks.txt`.

Scripts: `wp_eco002_reproducibility.py`, `wp_eco002_anchor.py`, `wp_eco002_dependencies.py`,
`wp_eco002_verify.py`, `wp_eco002_report.py`.

## Desviaciones respecto a lo previsto

1. **Un nodo preexistente pasa a rojo**: el pin del cost-barrier sobre
   `config/strategy_admission.json` (`6c4dd0be…`) es el del ledger con el ancla caducada.
   Declarado en `ANCHOR_REPAIR.json` y en `RUN_REPORT.json:declared_regression`; no se
   repara porque la reparación es re-certificar evidencia económica publicada.
2. **El método del WP-001 era parte del defecto**: `git archive` no lleva `.git`. Corregido
   a `git clone`; 17 de los 21 se explican así.
3. **`ruff format --check .` ya fallaba** antes de este WP (tres ficheros). No se
   reformatearon enteros; se verificó que el diff de formato no crece.
4. **`data/st6/ST6_RUNS.jsonl` no se borra**: procedencia determinada (24 eventos, 0
   `COLLECTED`, todos residuo de los ticks que lanzan los propios tests).
5. **`scripts/wp_eco001_add_defect.py` no se versiona**: era un mutador puntual del
   `RUN_REPORT.json` del WP anterior, idempotente; su efecto ya está en ese fichero, así que
   commitearlo sería residuo. Los otros seis scripts del WP-001 sí se versionan: son los que
   producen su evidencia.

## Qué NO se ha hecho

- No se tocó `src/` ni ninguna comisión, slippage, umbral o señal (comprobado sobre el diff).
- No se habilitó trading real ni se ejecutó PAPER con credenciales.
- No se regeneró evidencia económica publicada (cost-barrier, matriz de admisión).
- No se commitearon los JSON de `parts/` generados durante la medición sin pasar por
  `MANIFEST.json` — el manifest es la lista autoritativa de lo entregado.
