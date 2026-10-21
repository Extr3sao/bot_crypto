# RUN REPORT — WP-003-04 · Desbloquear la integración en `main`

**WP:** WP-003-04 (continuación de WP-003-03)
**Repositorio:** `Extr3sao/bot_crypto` (`origin` = `https://github.com/Extr3sao/bot_crypto.git`, público)
**Rama de trabajo:** `wp/isolation-005`
**PR:** [#17](https://github.com/Extr3sao/bot_crypto/pull/17) → `main`
**Fecha de medición:** 2026-10-21 (UTC)
**Resultado:** `DELIVERY_STATUS = BLOCKED` · `FALSE_SUCCESS = 0`

---

## 0. Resumen

La integración en `main` **no es segura hoy**, y la causa no es WP-003-03.

De los **7 checks que fallan** en el PR #17:

- **3 ya fallaban en la base** (`origin/main` `5e6f9632`) antes de este PR: `pip-audit`, `tests-and-coverage` y el job de smoke.
- De los **2 que la base sí pasa** (`ruff format --check`, `mypy .`), el rojo del PR lo aportan **617 ficheros sin formatear y 611 errores de mypy que pertenecen a otros work packages**. WP-003-03 aportaba **11** de esos errores de mypy — en sus propios dos ficheros — y ya están corregidos (`e450a238`).
- Los 2 errores de colección que rompen la suite **no se pueden arreglar formateando**: los tests están commiteados en esta rama, pero los módulos que importan sólo existen en **ramas hermanas**.

La PR tampoco mide lo que su título dice: son **493 commits y 3 447 ficheros** porque `main` local lleva **259 commits sin publicar** desde el 2026-09-22.

---

## 1. Estado real de Git (capturado, no heredado)

| Dato | Valor | Cómo se obtuvo |
| --- | --- | --- |
| `HEAD` local | `ffda06d5` | `git rev-parse HEAD` |
| Rama remota `wp/isolation-005` | `ffda06d5` | `git ls-remote --heads origin` |
| `origin/main` | `5e6f9632` (2026-09-22) | `git rev-parse origin/main` |
| `main` local | `1d2192b0` (2026-10-12) | `git rev-parse main` |
| `main` local vs `origin/main` | **+259 / −0** | `git rev-list --count` |
| `main` local vs rama | **−234 / +0** | `git rev-list --count` |
| `merge-base(main, rama)` | `1d2192b0` | `git merge-base` |
| Divergencia de historial | **ninguna** (cadena lineal) | `git log --oneline HEAD..origin/main` = 0 |
| PR #17 | 493 commits · 3 447 ficheros · +2 721 865 / −1 437 | GitHub REST `pulls/17` |
| `mergeable` | `true` · `mergeable_state = unstable` | idem |
| Protección de `main` | `UNKNOWN` (401 anónimo) | `GET /branches/main/protection` |
| `mergeable_state` en el HEAD publicado | **`clean` con 7 checks rojos** | GitHub REST, `835ae788` |

**Consecuencia estructural:** `origin/main` ⊆ `main` local ⊆ `wp/isolation-005`. Nada está divergido; lo que falta es **publicar** los 259 commits de `main` local o **decidir** que no se publican. Mientras eso no se decida, cualquier PR desde este clon arrastra el tronco entero: la PR de un work package de 234 commits se presenta como una de 493.

**El indicador de merge de GitHub no acredita nada aquí.** Con `ffda06d5` devolvió `unstable` y con `835ae788` devolvió **`clean`**, en ambos casos con **siete checks rojos**. Mientras no se pueda leer la protección de rama (401 anónimo), la conclusión honesta es que las gates de este repositorio se respetan **por proceso**, no por la plataforma: no fusionar depende de quien tiene el botón.

---

## 2. Baseline de CI en `main` — medido, no supuesto

Run `35724120977` sobre `5e6f9632` (el commit de `main` que dice “zero-out ruff/mypy/format gates”):

| Job | Resultado en `main` | Paso que falla |
| --- | --- | --- |
| Format + Lint (Ruff) | **success** | — |
| Type check (Mypy strict) | **success** | — |
| pip-audit | **failure** | `pip-audit` |
| Tests + Coverage (pytest, fast) | **failure** | `pytest --cov --cov-fail-under=90` |
| Smoke PR-pipeline | **failure** | **`Set up job`** (antes del checkout) |

Reproducción local del job de tests en un worktree limpio de `origin/main`:

```
582 passed, 78 warnings in 193.98s          # sin cobertura: verde
TOTAL  11194  3619  2342  286  62%
FAIL Required test coverage of 90% not reached. Total coverage: 62.34%
BASE_COV_EXIT=1
```

**Los tests de `main` pasan; lo que no se cumple es el umbral de cobertura del 90 %** (62.34 %). Ese gate está rojo en la base desde antes de este PR.

`pip-audit` en la base: **80 vulnerabilidades conocidas en 9 paquetes** (`aiohttp 3.14.1`, `multidict`, `anyio`, `nltk`, `pip`, `setuptools`, `urllib3`…). En la rama bajan a **11** porque `aab65cf9` regeneró el lock, pero sigue rojo: es deriva del advisory DB, no de este trabajo.

El job de smoke falla en **`Set up job`**, antes de hacer checkout: es **infraestructura** (la acción `microsoft/powershell@v1.1.0` no arranca en el runner), no código.

---

## 3. Reproducción local del PR en árbol limpio

Worktree detached de `ffda06d5`, sin ficheros sin versionar, con la toolchain **pineada igual que en CI** (`uv.lock`: `ruff 0.15.20`, `mypy 2.1.0`; `.python-version` 3.11; instalado y usado: idénticos).

| Gate | Comando | Resultado |
| --- | --- | --- |
| Formato | `ruff format --check .` | **exit 1** · **617** ficheros a reformatear (543 ya formateados) |
| Lint | `ruff check .` | **exit 1** · **195** errores en **44** ficheros |
| Tipos | `mypy .` | **exit 1** · **622** errores en **107** ficheros (1 155 comprobados) |
| Tests | `pytest -m "not slow and not market"` | **exit 2** · **2 errores de colección**, colección interrumpida |
| Tests (diagnóstico, ignorando los 2) | idem `--ignore=…` | ver §6 |
| Auditoría | `pip-audit --ignore-vuln PYSEC-2026-597 -r reqs.txt` | **exit 1** · 11 avisos |
| Transitorios | `git ls-files \| grep -E 'commit_msg.*\.txt\|tmp_\|transient'` | **0** (pasa) |

Los 2 errores de colección:

```
tests/unit/observability/test_vision_panel.py
  ModuleNotFoundError: No module named 'trading_bot.observability.vision_panel'

tests/unit/research/test_edge16_pit.py
  AttributeError: module 'trading_bot.research.economic_recovery.alpha15'
                  has no attribute 'PRE_PIT_RUNNERS'
```

---

## 4. Clasificación de cada fallo

| Check | Base (`5e6f9632`) | Ramo (`ffda06d5`) | Causa | Clase |
| --- | --- | --- | --- | --- |
| `format-and-lint` (formato) | PASS | 617 ficheros | deuda de los 493 commits | `REGRESION_DE_LA_ACUMULACION` — **0 % de WP-003-03** |
| `format-and-lint` (lint) | PASS | 195 errores / 44 ficheros | idem | idem — **0 % de WP-003-03** |
| `type-check` | PASS (233 ficheros) | 622 errores / 107 ficheros → **611** tras `e450a238` | idem | idem — **11 eran de WP-003-03, ya pagados** |
| `tests-and-coverage` | **FAIL** (cobertura 62.34 %) | FAIL (2 errores de colección + fallos) | umbral 90 % incumplido en la base + tests que importan módulos de ramas hermanas | `BASELINE_PREEXISTENTE` + `REGRESION_AJENA` |
| `pip-audit` | **FAIL** (80 avisos) | FAIL (11 avisos) | deriva del advisory DB | `BASELINE_PREEXISTENTE` |
| Smoke PR-pipeline | **FAIL** en `Set up job` | FAIL en `Set up job` | acción de CI | `INFRAESTRUCTURA` |
| `recovery-determinism` | no ejecutado (por paths) | FAIL en *lane contract tests* | lane de otro WP | `REGRESION_AJENA` (no es required check) |
| `cost-barrier` | no ejecutado (por paths) | FAIL en *reproduce the artefacts* | artefactos de otro WP | `REGRESION_AJENA` (no es required check) |

### Atribución por cohorte (¿de quién es el rojo?)

Cohortes: `LOCAL_MAIN` = los 259 commits de `main` local sin publicar · `RAMA_PREVIA` = los 234 commits de la rama anteriores a WP-003-03 · `WP00303` = `b82b487a..HEAD` · `BASE` = ficheros introducidos antes de `origin/main`.

| Gate | WP-003-03 | Rama previa | `main` local | Base |
| --- | --- | --- | --- | --- |
| Formato (617 ficheros) | **0** | 183 | 430 | 4 |
| Lint (44 ficheros) | **0** | 28 | 16 | 0 |
| Mypy (622 errores) | **11 → 0** | 358 | 253 | 0 |

Método: para cada fichero infractor, `git log --diff-filter=A -1` da el commit que lo introdujo y se compara con las tres cohortes (`rev-list main..wp/isolation-005`, `rev-list origin/main..main`, `rev-list b82b487a..HEAD`). Los 617 ficheros sin formatear fueron tocados por última vez por **178 commits distintos**: no hay un único commit culpable al que apuntar la reparación.

---

## 5. Las dos dependencias rotas (por qué formatear no arregla la suite)

Ambos tests están **commiteados en `wp/isolation-005`**, pero su módulo vive en otras ramas:

| Test (commit que lo añadió) | Depende de | Existe en |
| --- | --- | --- |
| `tests/unit/observability/test_vision_panel.py` (`5fd791d8`) | `trading_bot.observability.vision_panel` | `e90a8ad3` / `26fd3955`, sólo en `wp003i/reproducibility` y `wp003j/runtime` |
| `tests/unit/research/test_edge16_pit.py` (`6f04e59b`) | `alpha15.PRE_PIT_RUNNERS` | `8eb4a2c1` / `9f3892f6` / `611db47e`, en `exp/ai-bots/EXP-003I-THROUGHPUT-001`, `wp003i/reproducibility`, `wp003j/runtime`, `agent/ai-critic/RFC-TAP-AI-BOTS-004G` |

Ninguno de esos commits es ancestro de `wp/isolation-005` (`git merge-base --is-ancestor … HEAD` → falso).

Además, `src/trading_bot/observability/vision_panel.py` existe **sin versionar** (`??`) en 6 worktrees del disco (`sha256 bcd04d18…`): el commit que publicó el test no publicó el módulo. Es exactamente el caso “archivo importante ignorado o sin versionar” del encargo, y su reparación es un `git add`, no un formateo. No se ha añadido: es trabajo de otro WP y no cambia el veredicto.

---

## 6. Suite en la rama (diagnóstico)

`pytest -m "not slow and not market"` en el árbol limpio de `ffda06d5`, **ignorando los 2 módulos que no coleccionan** para poder medir el resto (34 min, 4 513 tests):

```
101 failed, 4362 passed, 31 skipped, 5 deselected, 78 warnings, 14 errors in 2228.52s (0:37:08)
```

Atribución de esos **115 nodos en rojo** (101 fallos + 14 errores) por cohorte del fichero de test:

| Cohorte | Nodos | Ficheros | Ejemplos |
| --- | --- | --- | --- |
| **WP-003-03** | **0** | 0 | — |
| `main` local | 96 | 21 | `test_profitability_gate035.py` (22), `test_rfc035s3_strategy_closure.py` (16), `test_cost_barrier_gate.py` (12) |
| Rama previa | 19 | 5 | `test_edge03_forward.py` (10), `test_edge04_autonomous.py` (4) |

Los 20 tests de `tests/integration/test_paper_e2e_00{1,2,3}.py` pasan. Es decir: **ni un fallo de la suite es de este WP**, ni siquiera en el escenario de peor caso donde los dos errores de colección se aparcan.

Comparación medida:

| Árbol | Resultado |
| --- | --- |
| `origin/main` `5e6f9632` | **582 passed**, cobertura 62.34 % → gate rojo por umbral |
| `ffda06d5` | **2 errores de colección** (CI) · **101 failed + 14 errors** si se ignoran |

---

## 7. Por qué no se ejecutó la “ruta mínima” mecánica

1. **Reformatear es la única vía mecánica, y es exactamente lo prohibido.** `ruff format .` sobre `ffda06d5` produce **617 ficheros, +37 469 / −18 032 líneas**. Eso no es una reparación revisable: reescribe el trabajo de 178 commits de terceros en un solo diff. Requiere autorización explícita del titular, no una decisión técnica reversible.
2. **Los 611 errores de mypy restantes no son mecánicos.** 105 ficheros de otros WPs, con códigos `arg-type` (112), `type-arg` (90), `operator` (54), `attr-defined` (50)… Cada uno exige criterio sobre código ajeno. `ruff check --fix` sólo resuelve 122 de los 195 errores de lint; el resto es manual.
3. **La cobertura del 90 % no se alcanza sin cambiar el gate o el alcance de medida**: la base está en 62.34 %. Ninguna rama puede ponerlo verde aportando tests de su WP.
4. **Los 2 errores de colección dependen de ramas no fusionadas.** Se arreglan integrando `wp003i/reproducibility` / `wp003j/runtime`, o borrando tests ajenos. Borrar trabajo ajeno está prohibido; fusionar ramas hermanas es decisión del titular.
5. **La PR es irrevisable por tamaño mientras `main` no se publique** (493 commits / 3 447 ficheros en vez de 234 / 1 859).

Ninguna de las cinco es una decisión técnica reversible dentro de este work package. Por eso el resultado es `BLOCKED` con causa medida, no un `PASS` de conveniencia.

---

## 8. Ruta ordenada propuesta (con coste medido)

| # | Acción | Coste medido | Dueño |
| --- | --- | --- | --- |
| P1 | Arreglar el **baseline de CI en `main`**: umbral de cobertura (62.34 % real), `pip-audit` (80 avisos), acción del job de smoke (`Set up job`) | 3 gates, todos ajenos al PR | pipeline |
| P2 | **Decidir `main` local**: publicar los 259 commits (fast-forward, sin force) o declararlos abandonados | 0 conflictos: `origin/main` es ancestro | titular |
| P3 | **Deuda de formato**: 1 commit mecánico de 617 ficheros | +37 469 / −18 032 líneas | titular (autorización) |
| P4 | **Deuda de lint**: 122 auto-fixables + 73 manuales en 44 ficheros | manual | dueños de cada WP |
| P5 | **Deuda de tipos**: 611 errores en 105 ficheros | manual, el mayor | dueños de cada WP |
| P6 | **Auto-contención**: integrar `wp003i/reproducibility` y `wp003j/runtime`, o traer los 2 módulos que faltan | 2 dependencias | titular |
| P7 | Re-ejecutar CI + verificación independiente sobre la PR ya pequeña | — | este agente |

---

## 9. Lo que sí se ejecutó en este WP

1. **`e450a238`** — los 11 errores de mypy de WP-003-03, corregidos en sus dos ficheros (`scripts/paper_e2e_lab.py`, `scripts/make_paper_e2e_reports.py`): ignores muertos, un guard leído dos veces, un `payload` sin anotar y un `dict` de informe cuya unión por clave se filtraba a la lista de limitaciones. `mypy .` pasa de **622 → 611** errores y nuestros ficheros quedan en **0**. `ruff format --check` y `ruff check` siguen limpios en ambos.
2. **Re-ejecución independiente del laboratorio PAPER** con el código corregido (`paper_e2e_lab.py` completo, 3 escenarios + 8 de abuso): `LAB_EXIT=0`. El verificador, alimentado con esa segunda ejecución como `--repeat`, devuelve **`verdict: PASS` (exit 0)** con **18/18 checks** y **11/11 controles negativos rechazados**, incluido `reproducible_evidence: economic digests identical across two independent runs`. Es decir: la corrección de tipos **no cambió la economía** de la validación.
3. **Mediciones reproducibles** de Git, GitHub Actions y las cuatro gates, sobre árbol limpio y toolchain pineada, con los comandos exactos en §12 (§1–§4).

---

## 10. GITHUB_SYNC

| Campo | Valor |
| --- | --- |
| `repository` | `https://github.com/Extr3sao/bot_crypto.git` |
| `local_branch` | `wp/isolation-005` |
| `remote_branch` | `origin/wp/isolation-005` |
| `local_head_sha` | `e450a238` (al escribir este informe) → ver `GITHUB_SYNC.json` para el SHA observado tras publicar |
| `remote_head_sha` | ver `GITHUB_SYNC.json` |
| `default_branch_sha` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` |
| `commits_pending` | ver `GITHUB_SYNC.json` (`ls-remote` post-push) |
| `push_result` | ver `GITHUB_SYNC.json` |
| `pull_request_url` | https://github.com/Extr3sao/bot_crypto/pull/17 |
| `merge_result` | **NOT_MERGED** — 7/7 checks en rojo |
| `sync_status` | `REMOTE_BRANCH_SYNCED` para la rama · `MAIN_SYNCED = NO` |
| `verification_timestamp` | 2026-10-21 (UTC) |

El SHA de la rama se registra **después** de publicar, en el fichero `GITHUB_SYNC.json` que se añade en un commit posterior: un commit no puede contener su propio hash, así que el registro nombra el tip que `ls-remote` devolvió y declara el desfase de 1 commit por construcción.

---

## 11. Estados separados

| Dimensión | Estado | Base de la afirmación |
| --- | --- | --- |
| `IMPLEMENTATION_STATUS` | **PASS** | código de WP-003-03 commiteado; 11 errores de tipos propios corregidos en `e450a238` |
| `TEST_STATUS` | **FAIL** | 2 errores de colección en la rama; `main` pasa 582 tests pero no el umbral de cobertura |
| `RUNTIME_VALIDATION` | **PASS (PAPER, datos registrados)** | re-ejecución completa del laboratorio, `LAB_EXIT=0` |
| `NETWORK_ISOLATION` | **PASS (por proceso)** | `no_external_network`, 13 refusals en 8 escenarios, 0 llamadas a venue |
| `EXTERNAL_ORDER_PREVENTION` | **PASS (por proceso)** | 0 órdenes reales; barrera por proceso, no sandbox de SO |
| `OS_SANDBOX` | **NOT_AVAILABLE** | sin contención de SO acreditada |
| `PAPER_VALIDATION` | **PASS (offline, ledger de escenario declarado)** | ver `wp00303/VERIFICATION.json` + `--repeat` |
| `MAIN_SYNCED` | **NO** | `origin/main` = `5e6f9632`; 259 commits locales sin publicar |
| `CI_STATUS` | **RED (pre-existente en 3/7)** | run `39664991894` + run `35724120977` |
| `INDEPENDENT_VERIFICATION` | **PASS (del artefacto PAPER)** | 18/18 + 11/11, exit 0 |
| `DELIVERY_STATUS` | **BLOCKED** | 3 gates rojos en la base + deuda ajena no autorizada |
| `PRODUCTION_READY` | **NOT CLAIMED** | prohibido por el encargo |
| `FALSE_SUCCESS` | **0** | ningún fallo se reporta como superado |

---

## 12. Reproducir estas cifras

```bash
# identidad
git rev-parse HEAD origin/main main
git rev-list --count origin/main..main main..wp/isolation-005
git ls-remote --heads origin wp/isolation-005 main

# árbol limpio del commit juzgado
git worktree add --detach ../ff-wt-head ffda06d5

# las cuatro gates requeridas, con la toolchain del lock
cd ../ff-wt-head
ruff format --check .          # 617 ficheros
ruff check .                   # 195 errores / 44 ficheros
mypy .                         # 622 errores / 107 ficheros
pytest -m "not slow and not market"   # exit 2: 2 errores de colección

# baseline
git worktree add --detach ../ff-wt-main-baseline origin/main
cd ../ff-wt-main-baseline
ruff format --check . && ruff check . && mypy .   # los tres pasan
pytest -m "not slow and not market" --cov --cov-fail-under=90   # 582 passed, 62.34 %

# auditoría
uv export --all-extras --no-hashes --output-file /tmp/reqs.txt
pip-audit --ignore-vuln PYSEC-2026-597 -r /tmp/reqs.txt
```
