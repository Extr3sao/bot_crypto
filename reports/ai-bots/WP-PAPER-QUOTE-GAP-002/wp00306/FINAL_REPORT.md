# WP-003-06 — Final report

**Veredicto:** la entrega es **revisable, reproducible y verificable de forma independiente**, y
sigue **BLOCKED** para promoción. Lo que la bloquea no es este trabajo: es el tronco heredado y
dos gates de política que no se pueden resolver desde aquí.

`FALSE_SUCCESS = 0` · `MAIN_SYNCED = NO` · `MERGES = NONE` · `PRODUCTION_READY = NOT CLAIMED`

---

## 1. Commits y ramas reales

| rama | sha | publicado | qué es |
| ---- | --- | --------- | ------ |
| `recovery/trunk-sync` | `1d2192b0` | sí | el tronco local, con nombre inmutable |
| `recovery/wp00303` | `08c5d9d2` | sí | el entregable: 6 commits de port + evidencia + veredicto |
| `fix/ci-smoke-pwsh` | `9682ee1b` | sí | reparación de pipeline, independiente de todo |
| `wp/isolation-005` (PR #17) | `624455c8` | sí | sin fusionar, sin tocar |
| `origin/main` | `5e6f9632` | — | la autoridad del proyecto |

Ocho commits en el entregable: `31b8d223` `021d614d` `4c60683c` `04aeb308` `7e4971d1`
`baf5b560` `abdf2146` `08c5d9d2`. Ningún merge, ningún rebase, ningún force-push.

## 2. Qué se ha integrado y qué no

**Integrado (en una rama, no en `main`):** los 23 ficheros de WP-003-03 — guardia de
aislamiento, corpus holdout, broker/decisión, `risk/manager.py`, los tres scripts, `ops/` y el
formato de 8 ficheros — más 35 ficheros de evidencia verificable.

**No integrado, y por qué:**

- **`main` no se ha tocado.** Publicarlo pondría `main` rojo en formato (433), lint (100), tipos
  (253) y colección (4), y arreglarlo exige `ruff format` sobre 433 ficheros de 259 commits
  ajenos: prohibido por este WP.
- **PR #17 no se ha fusionado.** Sus gates obligatorios siguen rojos.
- **`observability.vision_panel` no se ha incorporado.** Ver §7 y `INTEGRATION_MAP.md` §5.
- **Los 95 nodos rojos de `tests/unit/research/*` no se han tocado.** Son del tronco.

## 3. Tests y CI ejecutados

| qué | resultado |
| --- | --------- |
| 37 tests del WP en el tip | **37 passed**, exit 0 |
| suite completa en el tip `08c5d9d2` | 81 failed, **3230 passed**, 31 skipped, 14 errors, 668.61 s |
| suite completa en el baseline tronco+ops | 81 failed, 3213 passed, 31 skipped, 14 errors, 562.08 s |
| nodos rojos, comparación bidireccional | **95 = 95**, 0 sólo en el tip, 0 sólo en el baseline |
| laboratorio PAPER, 4 ejecuciones | 3/3 digests idénticos a la referencia en todas |
| verificador independiente | **18/18** y **11/11** controles negativos, dos veces |

**CI real: `NOT_PERFORMED`.** Sin `gh`, sin token y sin trigger de rama. Lo local: YAML válido,
un solo `uses:`, `microsoft/powershell` inexistente, script con 551 tokens y 0 errores en PS 5.1.

## 4. Estado de los 18 controles

**18/18 PASS**, en el commit de evidencia `abdf2146` y en un checkout limpio del tip `08c5d9d2`.
Los cuatro que en WP-003-05 valían 0 ahora se evalúan de verdad:

- `evidence_in_commit` — 35 ficheros del bundle están dentro del commit juzgado.
- `manifest_covers` — 33 ficheros hasheados por `EVIDENCE_MANIFEST.json`, ninguno fuera.
- `reports_consistent` — los conteos de los reportes igualan al laboratorio; 9 dimensiones con
  `basis`, ninguna con PASS vacío.
- `github_sync_consistent` — `REMOTE_BRANCH_SYNCED` comprobado contra `origin`, no contra una nota.

Los 11 controles negativos (orden inventada, equity movida un céntimo, fill huérfano, comisiones
a cero, conexión externa, dataset falsificado, sync reclamada sin ser cierta…) son rechazados por
el verificador. Un verificador que no puede rechazar no prueba nada.

## 5. Bloqueos restantes

| # | bloqueo | de quién |
| - | ------- | -------- |
| B1 | el tronco no es publicable: 433 formato / 100 lint / 253 mypy / 4 colección | decisión de formato del titular (un commit mecánico, `+32 621/−15 426`, AST-neutro) |
| B2 | cobertura 90 % contra 62.34 % en la base | política: subir cobertura, acotar el gate o bajar el umbral con ADR |
| B3 | `pip-audit`: 80 avisos en 9 paquetes en la base | triaje por paquete |
| B4 | el stack depende del tronco: `origin/main` no tiene `src/trading_bot/autonomous/` | estructural |
| B5 | CI real del arreglo de PowerShell | titular: abrir la PR a `main` |
| B6 | 95 nodos rojos en `tests/unit/research/*` | lane de research (paquete F1) |
| B7 | `alpha15.PRE_PIT_RUNNERS` (D3) | lane de research, sólo existe en ramas hermanas |

## 6. Estado de PAPER

Ejecutado de verdad, no simulado en un mock: el `AutonomousPaperRuntime` real sobre klines 1h
grabadas de Binance, con `COST_MODEL_V3` y spread declarado como **estimado** (no hay serie de
top-of-book en este corpus, y el bundle lo dice en vez de inventar un cero observado).

23 órdenes, 21 cierres, comisión 10.5, PnL realizado `87.65152561534461`, 480 decisiones,
9 decisiones de trade no ejecutadas con motivo, 280 vetos de riesgo, 0 fills huérfanos, 0 clon
duplicado tras el reinicio, 0 eventos de red. Los tres digests son idénticos a los publicados en
**cuatro** ejecuciones, una de ellas sobre el árbol entregado.

`EXTERNAL_SESSION = NOT_PERFORMED`: la política de PAPER deniega la red por diseño, así que una
sesión contra venue no puede existir bajo ella. Eso es un límite declarado, no un fallo oculto.

## 7. Corrección a WP-003-05: `vision_panel`

WP-003-05 escribió que el módulo no estaba "en ningún commit" y que había "un fichero untracked
en seis worktrees". Las dos cosas eran falsas: el módulo está en `e90a8ad3` (dos ramas del lane
de observabilidad), el test que lo importa no está ni en el tronco ni en el port (por eso el port
tiene 0 errores de colección), las copias en disco **difieren** entre sí, y la versión tolerante
del test ya existe en `a91cabea`. Decisión: no incorporarlo. Corregido en
`INTEGRATION_BASELINE.json` → `missing_dependencies.D2`.

## 8. Siguiente paso mínimo

**Autorizar el commit mecánico de formato sobre `1d2192b0`.** Es una sola decisión, reversible,
con la neutralidad semántica ya demostrada sobre los 9 ficheros donde el port y la rama difieren
(AST idéntico salvo la posición de un import). Convierte 433 en 0 y deja los otros gates medibles
contra una base verde. Todo lo demás del plan está en `TRUNK_SANITATION_PLAN.md`, ordenado por
causa y con tamaño medido.

## 9. Limitaciones declaradas

- El verificador juzga el artefacto, no re-ejecuta el runtime; el vínculo es 13 hashes + 3
  ejecuciones frescas.
- Host Windows 11 con CRLF; el hashing normaliza CRLF→LF, los conteos de git no.
- `pwsh` 7 ausente: la aserción de PowerShell corrió en 5.1.
- Se liberaron cuatro worktrees de scratch (limpios, detachados, recreables) porque el disco
  estaba al 100 %. No se borró ningún fichero del proyecto.
