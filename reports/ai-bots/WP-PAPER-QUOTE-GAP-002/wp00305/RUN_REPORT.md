# RUN REPORT — WP-003-05 · Recuperación de integración y baseline de GitHub

**WP:** WP-003-05 (continuación de WP-003-04)
**Repositorio:** `Extr3sao/bot_crypto` · **PR:** [#17](https://github.com/Extr3sao/bot_crypto/pull/17)
**Rama juzgada:** `wp/isolation-005` = `afc0127086a67632ed94488d95d2e430417535b2`
**Fecha:** 2026-10-22 · **Modo:** PAPER, sin red, sin órdenes, sin credenciales
**Resultado:** `DELIVERY_STATUS = BLOCKED` · `FALSE_SUCCESS = 0` · `PRODUCTION_READY` no declarado

---

## 0. Resumen

La integración **sí tiene una ruta verificable**, y este WP la ha construido y medido en vez de proponerla: una rama de **6 commits y 23 ficheros** sobre el tronco que reproduce **los tres digests económicos publicados** de WP-003-03, con **0 deuda nueva** de formato, lint, tipos o colección.

Lo que bloquea la entrega no es el código de WP-003-03. Son **dos decisiones del titular** y un hecho medido que ningún agente puede resolver solo:

1. **El tronco (259 commits) no es publicable tal cual.** En `1d2192b0` hay **433 ficheros sin formatear, 100 errores de lint y 253 de tipos**, y la suite **ni siquiera colecciona** (4 errores, cuatro tests importan un módulo que sólo existe en la rama). Publicarlo pone rojo `main` y arreglarlo exige reformatear 433 ficheros de 259 commits ajenos: exactamente lo prohibido.
2. **WP-003-03 no es separable del tronco.** El runtime que ejerce (`autonomous/`, `paper/`) no existe en `origin/main`. Sí es separable de las otras **236** commits de la rama, que es lo que se ha demostrado.

Además se ha reparado, medido y publicado **el único fallo de pipeline que era reproducible y aislado**: el job de smoke muere porque referencia `microsoft/powershell@v1.1.0`, una acción que **no existe** (tag y `action.yml` devuelven 404).

---

## 1. Autoridad Git, capturada hoy

| Dato | Valor | Comando |
| --- | --- | --- |
| `origin/main` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` | `git rev-parse origin/main` tras `fetch --prune` |
| `main` local | `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` | `git rev-parse main` |
| `wp/isolation-005` | `afc0127086a67632ed94488d95d2e430417535b2` | `git rev-parse HEAD` = `origin/wp/isolation-005` |
| Divergencia | ninguna: `0 259` y `0 239` | `git rev-list --left-right --count` |
| Historia | lineal, **0 merges**, 1 autor | `git log --merges` |
| PR #17 | **498 commits · 3 452 ficheros · +2 722 984 / −1 437** | REST `pulls/17` |
| Checks en `afc01270` | **7 / 7 en rojo** | REST `commits/afc01270/check-runs` |
| `mergeable_state` | `unstable` (con 7 rojos) | REST `pulls/17` |
| Protección de `main` | `UNKNOWN` (401 anónimo) | REST `branches/main/protection` |

Los números de la PR coinciden **exactamente** con los que devuelve GitHub y con `git diff --numstat`: 3 452 / +2 722 984 / −1 437.

## 2. Fase A — las dos cohortes

| Cohorte | Rango | Commits | Fechas | Verificación |
| --- | --- | --- | --- | --- |
| **TRONCO_NO_PUBLICADO** | `origin/main..main` | **259** | 2026-09-25 → 10-12 | nunca publicada, nunca ejecutada por CI; 4 errores de colección en su tip |
| **RAMA** | `main..HEAD` | **239** | 2026-10-12 → 10-21 | 7/7 rojo en el head publicado |

La rama se etiqueta por work package (125/239 con tag, 21 tags); el tronco no (0/259). Ninguna cohorte tiene merges.

### Qué explica el tamaño

| Clase | Ficheros | +líneas | % |
| --- | --- | --- | --- |
| Evidencia generada (`reports/`) | 1 176 | **1 790 665** | **65.8 %** |
| Datasets (`data/`) | 323 | 382 299 | 14.0 % |
| Scripts | 432 | 240 901 | 8.8 % |
| `src/` | 271 | 118 071 | 4.3 % |
| Docs | 896 | 99 782 | 3.7 % |
| Tests | 236 | 71 047 | 2.6 % |
| CI / otros | 118 | 20 219 | 0.8 % |

**No es una PR de código grande; es una PR de evidencia.** El código de WP-003-03 son 2 629 líneas en tres scripts. Los cinco ficheros mayores son artefactos (`EQUITY_CURVE.csv` 229 648 líneas, `RECOVERY_LAB.json` 184 410, `ROBUSTNESS.json` 97 676, `PANEL_SECONDS.csv` 95 914, `binance_usdm_exchange_info.json` 79 246).

## 3. Fase A.3/A.4 — dependencias reales de WP-003-03

Construida en árbol limpio desde el tronco, añadiendo **sólo** lo que cada error exigía:

| Paso | Origen | Fallo medido que lo exigió |
| --- | --- | --- |
| Guardia de aislamiento (7 ficheros) | `0bdda77d` | `ModuleNotFoundError: trading_bot.execution.isolation` |
| Corpus holdout (4 ficheros, 1.6 MB) | `8e66e81b` | sin barras el laboratorio no tiene datos |
| Broker + runtime de decisión (6 ficheros) | `b4ff5889`, `87b9c6af`, `5b86b656`, `96957a2b`, `86d4f126` | `AttributeError: 'PaperBroker' object has no attribute 'accounting_snapshot'` |
| `risk/manager.py` | `9dbbbaee`, `1869f535`, `5b86b656` | **ningún error**: el digest de `E2E-RESTART` difería (16 órdenes y 32 aprobaciones donde la evidencia vetó las 81) |
| 3 scripts del laboratorio | `06ba3183` + `e450a238` | — |
| `ops/` (2 ficheros) | `fe9b5e26` | 4 errores de colección de la suite |
| Formato de 8 ficheros | este WP | `ruff format --check` marcaba 8 de 17 |

El cuarto paso es el que justifica medir los tres escenarios: con el broker del tronco, `E2E-COMMITTED` y `E2E-SCENARIO` daban **el digest publicado** y sólo `E2E-RESTART` delataba que el runtime no era el medido. Una validación de un solo escenario habría publicado un falso éxito.

### Dependencias huérfanas

| id | Test | Necesita | Existe en | Estado |
| --- | --- | --- | --- | --- |
| D1 | 4 tests de `autonomous/` y `forward/` (tronco, 29-09/01-10) | `trading_bot.ops` | rama, `fe9b5e26` | **cerrado** en `baf5b560` (4 errores → 0) |
| D2 | `test_vision_panel.py` (`5fd791d8`) | `observability.vision_panel` | **ningún commit**; fichero sin versionar en 6 worktrees | abierto, ajeno |
| D3 | `test_edge16_pit.py` (`6f04e59b`) | `alpha15.PRE_PIT_RUNNERS` | 4 ramas hermanas | abierto, requiere titular |

## 4. Fase B — la rama mínima, medida

`integration/wp00303-min` = `baf5b560101188ecceb36a4880d3dca16b267e31` (local, sin publicar).

| Commit | Contenido |
| --- | --- |
| `31b8d223` | guardia de aislamiento + corpus |
| `021d614d` | 3 scripts del laboratorio |
| `4c60683c` | broker + runtime de decisión |
| `04aeb308` | `risk/manager.py` |
| `7e4971d1` | formato de los 8 ficheros portados |
| `baf5b560` | `src/trading_bot/ops/` |

**23 ficheros · +4 472 / −88** frente a **1 864 ficheros · +1 990 709** de la rama.

### Equivalencia económica

| Escenario | Digest publicado | Digest del port | Totales | Contabilidad |
| --- | --- | --- | --- | --- |
| `E2E-COMMITTED` | `20f10f30…` | **idéntico** | idénticos | idéntica |
| `E2E-SCENARIO` | `59dc3611…` | **idéntico** | idénticos | idéntica (23 órdenes, 21 cierres, PnL 87.65152561534461) |
| `E2E-RESTART` | `45ada80c…` | **idéntico** | idénticos | idéntica |

Sólo difieren `position_id`, `trade_id`, `entry/exit_order_id` y los relojes `opened_at`/`closed_at`: **ningún campo económico**.

**Runtime:** en el port previo al formateo, **13/13 `runtime_sha256` byte-idénticos** a la evidencia publicada. Tras `7e4971d1`, 8/13 (5 cambian sólo por espacios) y **los 3 digests siguen idénticos**: el formateo es semánticamente inerte.

**Dataset:** idéntico, `manifest_sha256 = 883a4fd3…`.

**Abuso:** 8/8 escenarios `OK`, 13 refusals, **0 eventos de red auditados**.

## 5. Gates (árbol limpio, misma toolchain del lock)

`ruff 0.15.20` · `mypy 2.1.0` · Python 3.11.15

| Gate | base `5e6f9632` | tronco `1d2192b0` | rama `afc01270` | port `baf5b560` |
| --- | --- | --- | --- | --- |
| `ruff format --check .` | **0** | 433 | 617 | **428** (0 propios) |
| `ruff check .` | **0** | 100 | 195 | **100** (0 propios) |
| `mypy .` | **0** (233) | 253 (29 f.) | 611 (105 f.) | **253** (0 propios) |
| Colección | 0 | **4 errores** | 2 errores | **0 errores** |
| `pytest --cov-fail-under=90` | falla 62.34 % | — | — | — |
| `pip-audit` | 80 avisos | — | 11 | — |

El port **reduce** la deuda de formato en 5 ficheros (los que el tronco también marcaba y `7e4971d1` formateó) y **no añade ninguna** en ninguna de las cuatro dimensiones.

## 6. Suite

- **Tests del WP y de la guardia:** `37 passed` en 4,80 s (`test_paper_e2e_001/002/003` + `test_isolation`).
- **Suite completa del port:** `81 failed, 3230 passed, 31 skipped, 3 deselected, 14 errors in 738.41 s` — **0 errores de colección**.
- Los 81 fallos y los 14 errores están **todos** en `tests/unit/research/*` (16 en `test_rfc035s3_strategy_closure`, 11 en `test_cost_barrier_gate`, 9 en `test_st6_scheduler`, 8 en `test_profitability_gate035`…), artefactos de investigación del tronco, ninguno en ficheros del port.
- Comparación de atribución: la misma suite sobre `1d2192b0 + ops` (sin el port) da el mismo conjunto. Ver `evidence/CI_GATES.json` y §12.

## 7. Reparación del pipeline (PR-1)

`fix/ci-smoke-pwsh` = `9682ee1b31dbd01f72b3ff94ba3e6397df971fb6`, **publicada** en `origin` (fast-forward, rama nueva, sin force).

- Causa: `microsoft/powershell@v1.1.0` **no existe** — `raw.githubusercontent.com/.../v1.1.0/action.yml` → 404, `api.github.com/.../releases/tags/v1.1.0` → 404.
- Prueba en el job real `119491886187`: **paso 1 `Set up job` fallido, sin paso 2**. El runner no llega ni al checkout.
- Arreglo: eliminar el paso de instalación. `ubuntu-latest` ya trae pwsh y los dos pasos ya piden `shell: pwsh`.
- Verificado localmente: YAML parseado; el job queda con un único `uses:` (`actions/checkout@v4`); `scripts/open-pr-tsk-0204.ps1` parsea con **0 errores y 551 tokens** usando la misma API `Language.Parser` (proxy en PowerShell 5.1: en el runner es pwsh 7).
- **No verificado en CI todavía:** el workflow sólo se dispara en `push` a `main` y en `pull_request` a `main`. Una rama publicada no ejecuta nada, y abrir la PR es decisión del titular.

## 8. Verificación independiente

`scripts/verify_paper_e2e.py` (sólo stdlib) sobre el bundle de la corrida final, juzgando `baf5b560`:

- **14/18 checks OK**, **11/11 controles negativos rechazados**, `unsupported_pass_count = 4`.
- Verdes: `lab_shape`, `runtime_identity`, `dataset_identity`, `committed_ledger_no_trade`, `scenario_reached_broker`, `no_orphan_fills`, `accounting_identities`, `risk_before_order`, `restart_reconciled`, `error_path_closed`, `no_external_network`, `abuse_battery`, `pit_holds`, `reproducible_evidence`.
- No verdes, **todos de empaquetado o estado remoto**: `evidence_in_commit` (los 27 ficheros del bundle están en `.tmp`, no en el commit), `manifest_covers` (sin `EVIDENCE_MANIFEST.json`), `reports_consistent` (sin `RUN_REPORT.json`/`FINAL_REPORT.json`), y `github_sync_consistent` **BLOCKED** (la rama mínima no está publicada: no se puede leer el remoto, y no se cuenta como pasado).

Ninguno de los cuatro cuestiona el flujo, la economía ni el aislamiento. Se declaran como límite, no se maquillan.

## 9. Por qué `BLOCKED` y no `PASS`

| # | Bloqueo | Medida | Quién decide |
| --- | --- | --- | --- |
| B1 | Publicar el tronco pone rojo `main` (433/100/253) | `CI_GATES.json` | titular: reformatear 433 ficheros, gate incremental o no publicar |
| B2 | WP-003-03 necesita el tronco (su runtime no está en `main`) | `origin/main` no tiene `src/trading_bot/autonomous/` | depende de B1 |
| B3 | Cobertura 90 % con base 62.34 % | WP-003-04 | no se baja el umbral |
| B4 | `pip-audit` 80 avisos en la base | WP-003-04 | deriva de dependencias, no de este WP |
| B5 | D2/D3: tests commiteados sin su módulo | §3 | titular / port desde ramas hermanas |

`ruff format .` sobre 433 ficheros de 259 commits ajenos, fusionar 239 commits o bajar gates quedan **fuera** de lo autorizado. Por eso el WP entrega la ruta y la evidencia, no un merge.

## 10. GITHUB_SYNC

| Campo | Valor |
| --- | --- |
| `repository` | `https://github.com/Extr3sao/bot_crypto.git` |
| `local_branch` | `wp/isolation-005` |
| `remote_branch` | `origin/wp/isolation-005` |
| `local_head_sha` | `afc0127086a67632ed94488d95d2e430417535b2` |
| `remote_head_sha` | `afc0127086a67632ed94488d95d2e430417535b2` |
| `default_branch_sha` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` |
| `commits_pending` | **0** en `wp/isolation-005`; **259** entre `main` local y `origin/main` |
| `push_result` | esta rama no recibió commits nuevos; se publicó `fix/ci-smoke-pwsh` (`9682ee1b`, rama nueva, sin force) |
| `pull_request_url` | https://github.com/Extr3sao/bot_crypto/pull/17 |
| `merge_result` | **NOT_MERGED** — 7/7 checks rojos |
| `sync_status` | `REMOTE_BRANCH_SYNCED` · `MAIN_SYNCED = NO` |
| `verification_timestamp` | `2026-10-22T16:20:00Z` |

## 11. Estados separados

| Dimensión | Estado | Base |
| --- | --- | --- |
| `HISTORY_EXPLAINED` | **PASS** | dos cohortes medidas, 0 merges, SHA de GitHub = SHA locales |
| `DEPENDENCIES_MAPPED` | **PASS** | D1 cerrado; D2/D3 con causa y dueño |
| `CI_BASELINE_REPRODUCED` | **PASS** | 4 árboles medidos + 2 runs de GitHub |
| `MINIMAL_INTEGRATION` | **PASS** | 23 ficheros, 3/3 digests, 0 deuda nueva, 37 tests del WP |
| `PIPELINE_REPAIR` | **PARTIAL** | smoke verificado localmente; CI real pendiente de PR |
| `INDEPENDENT_VERIFICATION` | **PASS (del flujo)** | 14/18 con 11/11; los 4 no verdes son empaquetado/remoto |
| `PAPER_VALIDATION` | **PASS (offline, datos registrados)** | 3 escenarios, 23 órdenes, 21 cierres, 8 escenarios de abuso |
| `MAIN_SYNCED` | **NO** | `origin/main` = `5e6f9632` |
| `CI_STATUS` | **RED (7/7 en el head; 3 ya rojos en la base)** | runs `35724120977` y `39677738326` |
| `DELIVERY_STATUS` | **BLOCKED** | B1–B5 |
| `PRODUCTION_READY` | **NOT CLAIMED** | prohibido |
| `FALSE_SUCCESS` | **0** | ningún check no ejecutado se cuenta como pasado |

## 12. Reproducir

```bash
# autoridad
git fetch --prune origin
git rev-parse origin/main main wp/isolation-005
git rev-list --count origin/main..main main..wp/isolation-005

# gates, árbol limpio, toolchain del lock
git worktree add --detach ../ff-wt-trunk 1d2192b0
cd ../ff-wt-trunk && ../bot-freebuff-recovery-004/.venv/Scripts/ruff format --check .   # 433
../bot-freebuff-recovery-004/.venv/Scripts/ruff check .                                  # 100
../bot-freebuff-recovery-004/.venv/Scripts/mypy .                                        # 253
PYTHONPATH=src pytest -m "not slow and not market" -q                                    # 4 errores de colección

# rama mínima
cd ../ff-wt-min && git log --oneline main..HEAD
PYTHONPATH=src pytest tests/integration/test_paper_e2e_00*.py tests/unit/execution/test_isolation.py -q
PYTHONPATH=src python scripts/paper_e2e_lab.py --out .tmp/lab --json .tmp/PAPER_E2E_LAB.json
python scripts/verify_paper_e2e.py --lab .tmp/PAPER_E2E_LAB.json --bundle .tmp \
  --repo . --evidence-sha "$(git rev-parse HEAD)" --repeat .tmp/PAPER_E2E_LAB.json \
  --negative-controls --json .tmp/VERIFICATION.json

# PR-1
cd ../ff-wt-ci && git log --oneline -1        # 9682ee1b
```
