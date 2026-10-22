# WP-003-06 — Run report

**Objetivo:** convertir la integración mínima de WP-003-03 en una entrega revisable,
reproducible y verificable, sin tocar su comportamiento económico.

**Modo:** OFFLINE / PAPER sobre klines grabadas. `LIVE_ORDERS=0`, `EXTERNAL_SESSION=NOT_PERFORMED`,
sin credenciales, sin merge, sin force-push, sin `ruff format .`.

**Estado:** `EVIDENCE_VERSIONED=PASS`, `INDEPENDENT_VERIFICATION=PASS 18/18`,
`CI_REAL_RUN=NOT_PERFORMED`, `MAIN_SYNCED=NO`, `DELIVERY_STATUS=BLOCKED`, `FALSE_SUCCESS=0`.

---

## 0. Un bloqueo material antes de empezar

El disco estaba al **100 % (0 bytes libres)** y el primer `git worktree add` murió con
`No space left on device`. Se liberaron **cuatro worktrees de scratch** de WPs anteriores
(`ff-wt-local-main`, `ff-wt-main-baseline`, `ff-wt-branch`, un temp de rfc018): todos
detachados, limpios y recreables desde git, ninguno con trabajo propio. No se borró ningún
fichero del proyecto. Quedaron **1.1 GB** libres.

---

## 1. Autoridad Git, medida en esta sesión

| ref | sha | publicado |
| --- | --- | --------------- |
| `origin/main` | `5e6f9632` | sí |
| `main` local | `1d2192b0` | **no** (259 commits) |
| `recovery/trunk-sync` | `1d2192b0` | sí |
| `recovery/wp00303` | `08c5d9d2` | sí |
| `wp/isolation-005` (PR #17) | `624455c8` | sí |
| `fix/ci-smoke-pwsh` | `9682ee1b` | sí |

`merge-base main wp/isolation-005` = `1d2192b0`. Historial lineal, **0 merges**. Fast-forward
en todas las direcciones: no hay divergencia que resolver.

## 2. Ramas creadas y publicadas (Fase B)

- **`recovery/trunk-sync`** = `1d2192b0`. No es un commit nuevo: es un nombre inmutable para el
  tronco local, para que el diff del port se pueda tomar contra algo publicado.
- **`recovery/wp00303`** = `08c5d9d2`, cortada del tronco. Ocho commits:
  `31b8d223` `021d614d` `4c60683c` `04aeb308` `7e4971d1` `baf5b560` (el port, 6 commits) ·
  `abdf2146` (bundle de evidencia) · `08c5d9d2` (veredicto y reportes que lo citan).

Ambas publicadas con `git push -u origin`, sin `--force`. `origin/recovery/wp00303` leído de
vuelta con `git ls-remote`: `08c5d9d2`.

**Advertencia que el mapa repite y aquí se sostiene:** la revisión apilada **no es una
integración independiente del tronco**. `origin/main` no tiene `src/trading_bot/autonomous/`;
sin los 259 commits, el runtime que este WP ejercita no existe.

## 3. Fase C — los cuatro controles que fallaban

En WP-003-05 el verificador daba **14/18**. Los cuatro no verdes eran de empaquetado, no de
flujo. Ahora:

| control | antes | ahora |
| ------- | ----- | ----- |
| `evidence_in_commit` | "27 ficheros del bundle de scratch no están en el commit juzgado" | **35 ficheros dentro de `08c5d9d2`** |
| `manifest_covers` | "no hay `EVIDENCE_MANIFEST.json`" | **33 ficheros hasheados, ninguno sin listar** |
| `reports_consistent` | "no hay `RUN_REPORT.json` / `FINAL_REPORT.json`" | **counts = lab, 9 dimensiones con `basis`** |
| `github_sync_consistent` | BLOCKED (rama sin publicar) | **`REMOTE_BRANCH_SYNCED`, ancestría leída de `origin`** |

**Cómo se rompió la circularidad.** Ningún fichero nombra al commit que lo añade. El bundle
nombra `local_head_sha = baf5b560` — el commit al que corrió el laboratorio y cuyos 13 hashes de
runtime viajan en el bundle — y ese sha es **ancestro** de la rama publicada; el manifiesto
identifica los artefactos por contenido, no por auto-referencia. El veredicto se escribe en un
commit posterior (`08c5d9d2`), que es también el que hace que los reportes citen el resultado en
vez de predecirlo.

```
18/18 checks · 11/11 controles negativos rechazados
```

Dos ejecuciones: sobre el commit de evidencia `abdf2146`, y sobre el tip entregado `08c5d9d2` en
un **checkout limpio** (`git worktree add --detach`, `git status --porcelain` vacío). Ambas PASS.

## 4. Fase D — validación funcional

**37/37 tests del WP** en el tip entregado: `tests/integration/test_paper_e2e_00{1,2,3}.py` +
`tests/unit/execution/test_isolation.py`, exit 0.

**Digests económicos: 3/3 idénticos a la referencia publicada**, en cuatro ejecuciones del
laboratorio:

| run | árbol | limpio | digests |
| --- | ----- | ------ | ------- |
| 1 | `baf5b560` | sí | idénticos (el bundle entregado) |
| 2 | `baf5b560` | `status_short=['?? .tmp/']` (su propio directorio de salida) | idénticos — descartado para no dejar un run sucio como prueba |
| 3 | `baf5b560` | sí | idénticos (el repeat entregado) |
| 4 | `08c5d9d2` (**el tip**) | sí | idénticos |

`20f10f30…` · `59dc3611…` · `45ada80c…`. Contabilidad idéntica: 23 órdenes, 21 cierres,
comisión 10.5, PnL realizado `87.65152561534461`, 0 fills huérfanos, 0 clon duplicado tras el
reinicio. 8/8 escenarios de abuso OK, 13 rechazos, **0 eventos de red**.

**Identidad del runtime ejecutado:** 13 ficheros re-hasheados contra el árbol, byte-idénticos.

**Comparación bidireccional de fallos** (suite completa, misma toolchain):

```
tip       08c5d9d2 : 81 failed, 3230 passed, 31 skipped, 3 deselected, 14 errors  (668.61 s)
baseline  tronco+ops: 81 failed, 3213 passed, 31 skipped, 3 deselected, 14 errors  (562.08 s)

nodos rojos: 95 vs 95
solo en el tip: 0
solo en el baseline: 0
→ conjuntos idénticos
```

Los 17 tests extra que pasan son los del port. **Cero regresiones nuevas, en las dos
direcciones.**

**Reformateo: bytes declarados, semántica comprobada.** 19 ficheros Python comparados por AST
entre `baf5b560` y el tip de la rama: 18 idénticos; 1 (`ops/windowless.py`) difiere **solo en la
posición de un `from collections.abc import Sequence`** — mismo conjunto de imports, cuerpo
no-import idéntico. Cambios semánticos: **0**.

**Gates:** tronco 433 formato / 100 lint / 253 mypy / 4 errores de colección; port 428 / 100 /
253 / **0**. Deuda nueva: 0 en las cuatro.

`ruff format --check` en el tronco: **433**, en el port **428**. La diferencia son exactamente
los 5 ficheros del tronco que el port toca y formatea; el conjunto añadido está **vacío**. Los 8
ficheros que formateó `7e4971d1` son esos 5 más 3 ficheros nuevos que el tronco nunca contó. Los
dos números eran correctos; medían árboles distintos y ahora está escrito cuál es cuál.

## 5. Fase E — CI

**`CI_REAL_RUN = NOT_PERFORMED`.** No es una omisión silenciosa: no hay `gh` instalado, no hay
token en el entorno, y el workflow sólo se dispara en `push`/`pull_request` a `main`. Abrir una
PR es una acción del titular, no algo que esta sesión pueda fabricar.

Lo que sí se midió en local, sobre `fix/ci-smoke-pwsh`:

- El YAML parsea; el job `smoke-pr-pipeline` conserva **un solo `uses:`** (`actions/checkout@v4`).
- `microsoft/powershell` **no existe como repositorio** (`git ls-remote` → `repository not found`),
  así que el job no podía resolver la acción y moría en `Set up job`, antes del checkout.
- `scripts/open-pr-tsk-0204.ps1` parsea con **551 tokens y 0 errores** bajo Windows PowerShell
  **5.1**.26100. Limitación declarada: `pwsh` 7 no está instalado en esta máquina.

## 6. Fase D — `observability.vision_panel`, resuelto

WP-003-05 afirmó "no existe en ningún commit; un fichero untracked en seis worktrees con sha256
`bcd04d18…`". **Las dos afirmaciones eran falsas** y la corrección cambia el propietario:

- El módulo **está commiteado** en `e90a8ad3` (172 líneas), en `wp003i/reproducibility` y
  `wp003j/runtime`, reformateado en `26fd3955`.
- El test que lo importa es `5fd791d8`, que está en la rama pero **ni en el tronco ni en el
  port** — por eso el port tiene 0 errores de colección y la rama tiene 2.
- Las dos copias en disco **no son iguales** (`cabf5066…` ≠ `fc8e4cd3…`), así que "promover una
  copia" nunca fue una operación segura.
- La versión tolerante del test ya existe en `a91cabea` (rama `exp/ai-bots/EXP-003I-THROUGHPUT-001`).

Nada fuera del test importa el módulo. Propietario: el lane de observabilidad. **No se
incorpora**: no es código huérfano a promover, es trabajo commiteado de otro lane más su arreglo
de test, y meterlo habría arrastrado un tercer contrato a un WP de PAPER.

## 7. Entregables

`reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00306/`: `INTEGRATION_MAP.md`,
`INTEGRATION_BASELINE.json`, `GITHUB_SYNC.json`, `RUN_REPORT.md/json`, `FINAL_REPORT.md/json`,
`TRUNK_SANITATION_PLAN.md`.
El bundle verificado vive en `reports/ai-bots/WP-PAPER-QUOTE-GAP-002/wp00303/` dentro de
`recovery/wp00303`.
