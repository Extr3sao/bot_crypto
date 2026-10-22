# FINAL REPORT — WP-003-05 · Recuperación de integración y baseline de GitHub

**Decisión: `BLOCKED` con causa medida.** La integración está diseñada, construida y verificada; lo que falta no es código, es **una decisión de formato sobre 259 commits ajenos** y la autorización para abrir dos PR.

**DELIVERY_STATUS: `BLOCKED`.** PAPER únicamente, datos registrados offline, sin capital real, sin LIVE.

---

## Resultado medido

- **Dos cohortes explicadas:** 259 commits del tronco no publicado (2026-09-25 → 10-12) + 239 de la rama (2026-10-12 → 10-21), 0 merges, 1 autor. GitHub y Git coinciden en los 498 commits, 3 452 ficheros y +2 722 984 / −1 437.
- **WP-003-03 aislado en 6 commits y 23 ficheros** (`integration/wp00303-min` = `baf5b560`), frente a 1 864 ficheros de la rama.
- **3/3 digests económicos idénticos** (`20f10f30…`, `59dc3611…`, `45ada80c…`), totales y contabilidad idénticos, 23 órdenes, 21 cierres, PnL 87.65152561534461.
- **13/13 hashes de runtime byte-idénticos** en el port previo al formateo; 8/13 tras él, con los 3 digests intactos.
- **0 deuda nueva de gates:** 0 ficheros de formato, 0 errores de lint, 0 de tipos, **0 errores de colección** (el tronco tenía 4).
- **37 tests del WP en verde**; suite completa `81 failed, 3230 passed, 31 skipped, 14 errors`, todos los rojos en `tests/unit/research/*` del tronco.
- **Job de smoke reparado y publicado** (`9682ee1b`): la acción `microsoft/powershell@v1.1.0` no existe; el job moría en `Set up job`, antes del checkout.
- **Verificación independiente:** 14/18 checks y **11/11 controles negativos rechazados**; los 4 no verdes son empaquetado de evidencia y estado remoto, declarados como límite.

## Las tres piezas de la integración

| PR | Rama | Base | Alcance | Estado |
| --- | --- | --- | --- | --- |
| **PR-1** | `fix/ci-smoke-pwsh` `9682ee1b` | `origin/main` | 1 fichero, −7/+8 | **publicada**, CI real pendiente de abrir la PR |
| **PR-2** | tronco `1d2192b0` | `origin/main` | 259 commits, fast-forward | **bloqueada** por la decisión de formato (433 ficheros) |
| **PR-3** | `integration/wp00303-min` `baf5b560` | PR-2 | 6 commits, 23 ficheros | **construida y verificada**, no publicada; depende de PR-2 |

El orden no es estético: PR-3 **no puede existir sin PR-2**, porque el runtime que WP-003-03 ejerce no está en `origin/main`. Lo que sí se ha demostrado es que no necesita las otras 236 commits de la rama.

## Por qué no se declara `PASS`

1. **El tronco no es publicable tal cual:** 433 ficheros sin formatear, 100 errores de lint, 253 de tipos y 4 errores de colección. Publicarlo pone rojo `main`, y arreglarlo exige `ruff format` sobre 433 ficheros de 259 commits ajenos — prohibido por el encargo y no reversible.
2. **La cobertura del 90 % sigue inalcanzable** desde una base de 62.34 %; bajarla está prohibido.
3. **`pip-audit` sigue rojo** por deriva de dependencias (80 avisos en la base).
4. **Dos tests commiteados no tienen módulo** en ningún commit (D2) o lo tienen sólo en ramas hermanas (D3).
5. **El smoke fix no tiene run de CI propio** porque el workflow sólo se dispara en PR a `main`; abrirlo es decisión del titular.

`ruff format .`, fusionar 239 commits, borrar tests, bajar gates o publicar en `main` quedan fuera de lo autorizado. Ninguna de esas acciones se ha ejecutado.

## Lo que este WP sí entrega

- `INTEGRATION_BASELINE.json` — SHA, cohortes, inventario de tamaño, capas de dependencia, gates, suite, plan de PR y estados.
- `INTEGRATION_MAP.md` — el mapa legible: qué bloquea qué y en qué orden.
- `evidence/CI_GATES.json` — los cuatro árboles medidos con la misma toolchain.
- `evidence/PAPER_E2E_MINIMAL_COMPARISON.json` — digests, hashes y campos que difieren.
- `evidence/VERIFICATION_MINIMAL.json` — veredicto independiente completo.
- `NEXT_WP_WP-003-06.md` — siguiente WP ejecutable, con las dos decisiones del titular medidas.
- Rama local `integration/wp00303-min` y rama publicada `fix/ci-smoke-pwsh`.

## Limitaciones (no son PASS)

- `OS_SANDBOX = NOT_AVAILABLE`: la barrera es un audit hook por proceso, no un sandbox de SO.
- `EXTERNAL_SESSION = NOT_PERFORMED`: la política paper niega la red por diseño.
- `PIPELINE_REPAIR = PARTIAL`: verificado localmente (YAML + parser), no en un runner.
- La comparación de suite es contra `1d2192b0 + ops`, porque el tronco solo no colecciona.
- El verificador juzga el artefacto del laboratorio; no re-ejecuta el runtime. Lo que une artefacto y código son los 13 hashes y la construcción.
- Plataforma Windows/CRLF: los números de ruff y mypy no dependen del fin de línea; los conteos de git sí.

## GITHUB_SYNC

| Campo | Valor |
| --- | --- |
| `repository` | `https://github.com/Extr3sao/bot_crypto.git` |
| `local_branch` | `wp/isolation-005` |
| `remote_branch` | `origin/wp/isolation-005` |
| `local_head_sha` | `afc0127086a67632ed94488d95d2e430417535b2` |
| `remote_head_sha` | `afc0127086a67632ed94488d95d2e430417535b2` |
| `default_branch_sha` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` |
| `commits_pending` | 0 en la rama · 259 en el tronco |
| `push_result` | `OK` para `fix/ci-smoke-pwsh` (`9682ee1b`, rama nueva, sin force); `wp/isolation-005` sin cambios |
| `pull_request_url` | https://github.com/Extr3sao/bot_crypto/pull/17 |
| `merge_result` | `NOT_MERGED` — 7/7 checks rojos |
| `sync_status` | `REMOTE_BRANCH_SYNCED` · `MAIN_SYNCED = NO` |
| `verification_timestamp` | `2026-10-22T16:20:00Z` |

## Dimensiones

| Dimensión | Resultado |
| --- | --- |
| `HISTORY_EXPLAINED` | **PASS** |
| `DEPENDENCIES_MAPPED` | **PASS** (D1 cerrado; D2/D3 con dueño) |
| `CI_BASELINE_REPRODUCED` | **PASS** (4 árboles + 2 runs) |
| `MINIMAL_INTEGRATION` | **PASS** (23 ficheros, 3/3 digests, 0 deuda) |
| `PIPELINE_REPAIR` | **PARTIAL** |
| `INDEPENDENT_VERIFICATION` | **PASS (del flujo)** 14/18, 11/11 |
| `PAPER_VALIDATION` | **PASS (offline, datos registrados)** |
| `MAIN_SYNCED` | **NO** |
| `CI_STATUS` | **RED** (3 rojos ya en la base) |
| `DELIVERY_STATUS` | **BLOCKED** |
| `PRODUCTION_READY` | **NOT CLAIMED** |
| `FALSE_SUCCESS` | **0** |

## Siguiente paso

`NEXT_WP_WP-003-06.md`: cerrar D2 (versionar `observability.vision_panel`), resolver D3 con el port mínimo de `PRE_PIT_RUNNERS`, medir el coste real del formateo del tronco en una rama no publicada y dejar PR-1/PR-3 listas para abrir. Dos decisiones del titular, ambas con la consecuencia ya medida.

Verificación independiente: **`14/18`, 11/11 controles negativos, `FALSE_SUCCESS = 0`.**
