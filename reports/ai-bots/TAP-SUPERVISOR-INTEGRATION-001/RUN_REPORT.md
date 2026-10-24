# RUN REPORT — TAP-SUPERVISOR-INTEGRATION-001

Rama de auditoría: `audit/supervisor-integration-001`, creada desde `main` (`e67194e7`).
Worktrees desechables: `ff-lane-probe` (`fda95664`), `ff-wt-42files` (`main` + rebanada),
sesiones y campañas en `%DOWNLOADS%\ff-paper-probe`, `ff-paper-campaign`, `ff-42-session`.
**`main` y el checkout compartido no se tocaron.**

## 1. Referencias

| Comando | Resultado |
| --- | --- |
| `git rev-parse main` | `e67194e7` |
| `git rev-parse codepaper/supervisor-001` | `3b758e22` |
| `git rev-parse fda95664` | `fda95664` |
| `git rev-list --count main..codepaper/supervisor-001` | 301 |
| `git rev-list --count main..fda95664` | **307** (301 lane + 6 RFC) |
| `git rev-list --count fda95664..main` | 3 |
| `git merge-base main codepaper/supervisor-001` | `1d2192b0` |

## 2. Inventario y alcance

| Comando | Resultado |
| --- | --- |
| `git diff --name-status main...codepaper/supervisor-001 \| cut -c1 \| sort \| uniq -c` | 1761 A, 43 M |
| recuento por área dominante de los 301 commits | reports 152, scripts 54, docs 33, tests 31, src 21, config/data 8, otros 2 (suma 301; inventario completo en `evidence/COMMIT_INVENTORY.tsv`) |
| `git diff --name-only main...lane \| grep -cE '^(reports\|docs)/'` | 1248 |
| `git ls-tree` (`.py`) lane / main | 1257 / 818 |

## 3. Alcanzabilidad (estática, desde objetos de Git)

| Comando | Resultado |
| --- | --- |
| `lane_graph.py` (8 entry points) | **110** alcanzables · 68 idénticos · 35 ausentes · 7 distintos |
| `lane_graph.py --broad` (todos los `scripts/*.py`) | 843 alcanzables · 338 ausentes · 15 distintos |
| clasificación de los 448 `.py` solo-lane | 35 supervisor · 303 otros scripts · 3 solo tests · 107 huérfanos |

Tres correcciones de método, cada una descubierta ejecutando: falta de
`def_run_019_prospective_run.py` como semilla (19→37), imports relativos mal resueltos
(37→42, apareció `economic_recovery/costs.py`), y configuraciones invisibles al grafo
(42→45, aparecieron `vision.yaml` y `strategy_candidates_edge15.json`).

## 4. Simulación de integración (no destructiva)

| Comando | Resultado |
| --- | --- |
| `git merge-tree --write-tree --name-only main codepaper/supervisor-001` | **exit 0**, árbol `1053827…`, **0 conflictos**, 1804 ficheros |
| `git merge-tree --write-tree --name-only main fda95664` | **exit 0**, árbol `1a2f60b…`, **0 conflictos**, 2012 ficheros, +1 705 545/−172 |
| `git cherry-pick -n c44f912c` sobre `main` (clon desechable) | **exit 1**, 7 conflictos (`deleted in HEAD and modified`) |

Evidencias: `evidence/MERGE_TREE_lane.txt`, `evidence/MERGE_TREE_rfc_tip.txt`.

## 5. Viabilidad operativa (ejecutada, no deducida)

Worktree `ff-lane-probe` en `fda95664`, `uv sync --frozen` → 0.

| Prueba | Resultado |
| --- | --- |
| `--help` de 6 entry points | **6/6 exit 0** |
| Sesión PAPER real (1 símbolo, `window_bars 20`, `warmup 25`, `duration 60`) | **exit 0**, `STOP_COMPLETED (CLEAN_END)`, `state=READY`, `restarts=0`, `live_orders=0` |
| Sesión con `window_bars=5` (bajo el mínimo) | **exit 3**, `STOP_NO_PROGRESS`; el hijo muere con `window_bars must be >= 20` — el supervisor **paró** en vez de reintentar en silencio |
| `paper_supervisor_campaign.py run --crashes 1` | **exit 1**, pero campaña completa: `RECOVERED`, 1 episodio, **5 ciclos**, cadena `INTACT` (13 líneas), `locks []`, `live_orders 0`, 5 min, `supervisor_exit_code 0` |
| `paper_lock_campaign_verify.py` sobre esa campaña | **exit 1**, `UNSUPPORTED_CAMPAIGN_SCHEMA` (declara `TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`, espera `TAP_PAPER_LOCK_CAMPAIGN_V1`), 0 checks puntuados |
| `paper_supervisor_verify.py` sobre esa campaña | **exit 1**, `FileNotFoundError: …/campaign/scenarios/SCENARIOS.json` (solo existe en el fixture) |
| `paper_session_status.py` sobre la sesión real | exit 0, reporta fencing (`stream_fence 1`, 3 ficheros `.lock.fence`) |

Sobre `main` + rebanada de 42 (`ff-wt-42files`, commit desechable `e1c23254`):

| Prueba | Resultado |
| --- | --- |
| `uv sync --frozen` (main, sin matplotlib) | 0, pero `import matplotlib` → `ModuleNotFoundError` |
| `uv add "matplotlib>=3.8,<4.0"` | exit 0; imports de `vision.prospective`, `ops.paper_supervisor`, `ops.windowless` **OK** |
| árbol sucio + sesión | **exit 3**, `RUNTIME_PATHS_DIRTY` (la procedencia exige commit) |
| 42 ficheros, sin config | **exit 3**, `STOP_BLOCKED`, 0 ciclos |
| 42 ficheros + 2 configs | **exit 0**, `STOP_COMPLETED`, **1 ciclo**, `live_orders 0` |
| `pytest tests/unit/paper tests/unit/risk` | **6 failed, 170 passed** |
| `--help` de 5 entry points | **5/5 exit 0** |

## 6. Bloqueos B1–B4, medidos

| Prueba | Resultado |
| --- | --- |
| B1: `pytest tests/unit/ops/test_single_writer_lock.py` ×5 | 19 passed ×5, **0 fallos** |
| B1: `pytest tests/unit/ops` ×3 (carga) | 86 passed ×3, **0 fallos** |
| B3: lock con dependencia **añadida** y no resuelta | `uv lock --check` **1**, `uv sync --frozen` **1** |
| B3: lock que **omite** una dependencia declarada (baseline del RFC) | `uv lock --check` **1**, `uv sync --frozen` **0** y desinstala `matplotlib` |
| B4 | campaña real existe y es reproducible; **no hay verificador que la juzgue** |

## 7. Lo que falló, y se reporta como fallo

- `pytest tests/unit` completo: **no terminó en 600 s**. `NOT_TESTED`. No lo presento como verde.
- La campaña real termina **exit 1** aunque `locks` esté vacío: `finished_without_locks=false`
  con `state=RECOVERED`. El criterio del harness no distingue "acabó limpio" de "acabó tras un
  crash recuperado". Se registra, no se "arregla" aquí.
- Los dos verificadores de campaña no aceptan la evidencia de su propio productor.
- `merge-tree` sin conflictos **no** es un aval: se reporta como riesgo, no como éxito.

## 8. FALSE_SUCCESS

Todas las afirmaciones de este informe tienen comando, exit code y evidencia enlazada.
**`false_success = 0` sobre las afirmaciones comprobadas.** Lo no comprobado está marcado
`NOT_TESTED` (suite completa, ruta `ccxt` autenticada, B2) o `BLOCKED` (verificación de campaña
real), nunca `PASS`.

## 9. Nota de repositorio

`main` ignora `reports/*` (solo `!reports/.gitkeep`). Este worktree de auditoría añade su
directorio con `git add -f`; la rebanada de integración incluye `.gitignore` porque, sin la
regla, cualquier commit de evidencia sobre `main` sale sin los informes y nadie lo nota.
