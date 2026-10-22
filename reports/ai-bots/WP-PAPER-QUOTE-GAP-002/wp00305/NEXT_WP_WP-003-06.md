# WP-003-06 — Cerrar las dependencias huérfanas de test y dejar el tronco publicable

**Estado:** `READY_TO_EXECUTE` (con dos decisiones del titular, marcadas D1/D2)
**Nace de:** WP-003-05 · `INTEGRATION_BASELINE.json` · `INTEGRATION_MAP.md`
**Modo:** PAPER únicamente. Sin LIVE, sin órdenes, sin credenciales.

---

## Objetivo

Dejar el repositorio en un estado en el que publicar el tronco y la PR de WP-003-03 sea una operación **revisable y verde**, sin reformatear 433 ficheros a ciegas y sin borrar ni silenciar un solo test.

## Lo que ya está medido y no hay que repetir

| Hecho | Evidencia |
| --- | --- |
| `origin/main` pasa formato, lint y tipos; falla cobertura (62.34 %), `pip-audit` (80) y el job de smoke (`Set up job`) | run `35724120977` sobre `5e6f9632` |
| El tronco (`1d2192b0`, 259 commits) trae 433 ficheros sin formatear, 100 errores de lint, 253 de tipos y **4 errores de colección** | `wp00305/evidence/CI_GATES.json` |
| WP-003-03 es aislable en **6 commits / 23 ficheros** sobre el tronco, con **3/3 digests económicos idénticos** | `integration/wp00303-min` = `5b5ea7d2` |
| El port no añade deuda de gates (0 formato, 0 lint, 0 tipos, 0 errores de colección) | `CI_GATES.json` → `delta_vs_trunk` |
| El job de smoke muere porque `microsoft/powershell@v1.1.0` no existe (404 en tag y `action.yml`) | job `119491886187`, paso 1 `Set up job` fallido, sin paso 2 |

## Tareas ejecutables sin decisión previa

### T1 · Versionar `trading_bot.observability.vision_panel` (cierra D2)

`tests/unit/observability/test_vision_panel.py` está commiteado en la rama (`5fd791d8`) y su módulo **no existe en ningún commit**: vive sin versionar, con sha256 `bcd04d18…`, en seis worktrees del disco.

1. Localizar la copia, comparar los seis ficheros por sha256 y quedarse con la que el test espera.
2. Añadirlo en una rama propia, ejecutar `tests/unit/observability/test_vision_panel.py` y demostrar que pasa **con el módulo versionado**, no con el del disco.
3. Comprobar que el fichero no contiene credenciales ni rutas absolutas.

**Criterio:** el test colecciona y pasa desde un checkout limpio de esa rama; 0 errores de colección atribuibles a este módulo.

### T2 · Resolver `alpha15.PRE_PIT_RUNNERS` (cierra D3)

El test `tests/unit/research/test_edge16_pit.py` (`6f04e59b`) importa un símbolo que sólo existe en cuatro ramas hermanas (`8eb4a2c1`, `9f3892f6`, `611db47e`).

1. Diff del símbolo y de sus dependencias entre `wp/isolation-005` y la rama que lo tiene.
2. Port **del símbolo y su grafo mínimo**, no de la rama entera; ejecutar el test y la suite de `research/economic_recovery`.
3. Si el grafo excede lo revisable, registrar `BLOCKED` con el diff medido y la decisión que necesita el titular.

**Criterio:** el test colecciona y pasa, o queda `BLOCKED` con causa medida. Nunca `skip`.

### T3 · Medir el coste real de la decisión de formato (D1)

En una rama de trabajo **no publicada**:

1. `ruff format` sobre el tronco y `git diff --stat` resultante: ficheros, líneas, commits afectados.
2. Repetir la ejecución PAPER mínima después del formateo y comprobar que los 3 digests siguen idénticos (ya se demostró para los 5 ficheros del port; falta el resto).
3. Escribir el memo de decisión: reformatear 433 ficheros de 259 commits ajenos **o** estrechar el gate de formato a los ficheros cambiados. Con el coste y el riesgo de cada opción.

**Criterio:** el memo existe con las dos opciones medidas; ninguna se aplica sin la decisión del titular.

### T4 · Dejar PR-1 y PR-3 listas para abrir

- PR-1 `fix/ci-smoke-pwsh` = `9682ee1b`, publicada. Abrir la PR **sólo** con autorización; sin ella, queda como rama.
- PR-3 `integration/wp00303-min` = `5b5ea7d2`, local. Rebasarla sobre el tronco publicado cuando D1 esté decidida y volver a ejecutar: `paper_e2e_lab` + verificador + `pytest` de los ficheros del WP.

**Criterio:** cada PR tiene su informe con alcance, gates y digests; ninguna se fusiona.

## Decisiones que sólo puede tomar el titular

| id | decisión | opciones | consecuencia medida |
| --- | --- | --- | --- |
| **D1** | Deuda de formato del tronco | (a) reformatear 433 ficheros · (b) gate incremental por ficheros cambiados · (c) no publicar el tronco | (a) diff masivo sobre 259 commits ajenos · (b) cambio de política de CI · (c) WP-003-03 no puede integrarse (su runtime no está en `main`) |
| **D2** | Abrir PR-1 y PR-3 | (a) sí · (b) sólo PR-1 · (c) ninguna | sin PR no hay ejecución real del workflow; el smoke queda verificado sólo por proxy local |

## Restricciones (heredadas, no negociables)

- Prohibido `ruff format .` sobre todo el repositorio, fusionar cientos de commits, force-push o reescribir ramas compartidas.
- Prohibido borrar, omitir o silenciar tests; prohibido bajar la cobertura o desactivar `pip-audit`.
- Prohibido publicar en `main` o fusionar la PR #17.
- `FALSE_SUCCESS = 0`: un check no ejecutado se registra como `BLOCKED`, nunca como `PASS`.

## Entregables

`RUN_REPORT.md/json` · `FINAL_REPORT.md/json` · memo de decisión de formato (T3) · evidencia de T1/T2 (tests + hashes) · `GITHUB_SYNC.json` con el estado real de cada rama.
