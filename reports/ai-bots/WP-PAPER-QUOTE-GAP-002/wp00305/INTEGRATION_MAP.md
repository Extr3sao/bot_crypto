# MAPA DE INTEGRACIÓN — WP-003-05

**Repositorio:** `Extr3sao/bot_crypto` · **PR:** [#17](https://github.com/Extr3sao/bot_crypto/pull/17)
**Fecha de medición:** 2026-10-22 · **Autoridad:** Git local + `git ls-remote`, no notas previas.
**Resultado de la fase:** `INTEGRATION_DESIGN = READY` · `DELIVERY_STATUS = BLOCKED` · `FALSE_SUCCESS = 0`

---

## 1. Autoridad Git, capturada hoy

| Referencia | SHA | Fecha | Cómo se obtuvo |
| --- | --- | --- | --- |
| `origin/main` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` | 2026-09-22 | `git rev-parse origin/main` tras `git fetch --prune` |
| `main` local | `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` | 2026-10-12 | `git rev-parse main` |
| `wp/isolation-005` (PR head) | `afc0127086a67632ed94488d95d2e430417535b2` | 2026-10-21 | `git rev-parse HEAD` = `origin/wp/isolation-005` |
| Ancestro común | `1d2192b0` = `main` | — | `git merge-base main wp/isolation-005` |
| Divergencia | **ninguna** | — | `git rev-list --left-right --count` = `0 259` y `0 239` |

`origin/main` ⊆ `main` ⊆ `wp/isolation-005`. La historia es **lineal**, sin merges: 498 commits, un solo autor.

### Lo que la PR mide hoy

| Dato | Valor | Comando |
| --- | --- | --- |
| Commits en la PR | **498** | `git rev-list --count origin/main..HEAD` |
| Ficheros | **3 452** | `git diff --numstat origin/main...HEAD` |
| Líneas | **+2 722 984 / −1 437** | idem |
| Checks del head publicado | **7 / 7 en rojo** | `GET /commits/afc01270/check-runs` |
| `mergeable_state` | `clean` con 7 checks rojos | REST `pulls/17` (medido en WP-003-04) |
| Protección de `main` | **UNKNOWN** (401 anónimo) | REST `branches/main/protection` |

## 2. Por qué la PR mide 498 commits y no 3

Dos cohortes disjuntas, ninguna fusionada con la otra:

| Cohorte | Rango | Commits | Fechas | Toca (file-touches) |
| --- | --- | --- | --- | --- |
| **TRONCO_NO_PUBLICADO** | `origin/main..main` | **259** | 2026-09-25 → 2026-10-12 | `data` 648 · `docs` 569 · `scripts` 406 · `src` 252 · `tests` 227 · `research` 106 |
| **RAMA** | `main..HEAD` | **239** | 2026-10-12 → 2026-10-21 | `reports` 2 042 · `scripts` 278 · `src` 187 · `tests` 111 · `docs` 61 · `data` 26 |

El tronco no está etiquetado por work package (259/259 sin tag); la rama sí (125/239 con tag `[WP-…]`/`[RFC-…]`, 21 tags distintos, `WP-EDGE-01` 20 commits y `WP-EDGE-07` 16 los mayores).

### Inventario del tamaño (por clase de artefacto)

| Clase | Ficheros | +líneas | % de las adiciones |
| --- | --- | --- | --- |
| **Evidencia generada** (`reports/`) | 1 176 | **1 790 665** | **65.8 %** |
| **Datasets** (`data/`) | 323 | 382 299 | 14.0 % |
| Scripts | 432 | 240 901 | 8.8 % |
| Código `src/` | 271 | 118 071 | 4.3 % |
| Documentación | 896 | 99 782 | 3.7 % |
| Tests | 236 | 71 047 | 2.6 % |
| CI / otros | 118 | 20 219 | 0.8 % |

Cinco ficheros explican **646 000 líneas** por sí solos: `reports/edge-recovery/WP-EDGE-01/EQUITY_CURVE.csv` (229 648), `.../rfc004/RECOVERY_LAB.json` (184 410), `.../WP-EDGE-02/.../ROBUSTNESS.json` (97 676), `.../WP-EDGE-09/panel/PANEL_SECONDS.csv` (95 914), `data/rfc048/raw/binance_usdm_exchange_info.json` (79 246).

**Conclusión de la fase A.5:** la PR no es grande por el código. Es grande porque publica la evidencia de 20 work packages de investigación y porque `main` no se ha publicado desde el 2026-09-22. El código de WP-003-03 son **2 629 líneas** de tres scripts.

## 3. WP-003-03 aislado: qué necesita de verdad

WP-003-03 son **dos commits** (`06ba3183` el laboratorio, `e450a238` el arreglo de tipos) y tres scripts: `paper_e2e_lab.py` (1 290 líneas), `verify_paper_e2e.py` (841, sólo stdlib), `make_paper_e2e_reports.py` (498). El laboratorio no modifica runtime: lo **ejerce**.

Se construyó una rama limpia desde el tronco y se fue midiendo qué falta, un error cada vez, sin suponer nada:

| Paso | Lo que se añadió | Origen exacto | Fallo medido que lo exigió |
| --- | --- | --- | --- |
| L1 | 13 ficheros: guardia de aislamiento en `execution/__init__.py`, `execution/isolation.py`, `app.py` y los 3 conectores de venue, más su test | `0bdda77d` (WP-003-02) | `ModuleNotFoundError: trading_bot.execution.isolation` |
| L2 | `data/edge07/holdout-1h/` (4 ficheros, 1.6 MB) | `8e66e81b` (WP-EDGE-07) | corpus declarado por el laboratorio; sin él no hay barras |
| L3 | `paper/broker.py`, `paper/reconciliation_v4.py`, `autonomous/{contracts,decision,runtime,supervisor}.py` | `b4ff5889`, `87b9c6af`, `5b86b656`, `96957a2b`, `86d4f126` | `AttributeError: 'PaperBroker' object has no attribute 'accounting_snapshot'` |
| L4 | `risk/manager.py` | `9dbbbaee`, `1869f535`, `5b86b656` | **no hubo error**: el digest de `E2E-RESTART` difería (32 trades aprobados donde la evidencia publicada vetó los 81). Sin este fichero el resultado era silenciosamente distinto |
| L5 | los 3 scripts del laboratorio | `06ba3183` + `e450a238` | — |
| L6 | `src/trading_bot/ops/` (2 ficheros, 499 líneas) | `fe9b5e26` | **4 errores de colección** de la suite: cuatro tests commiteados en el tronco importan un módulo que no existía hasta el 2026-10-18 |
| L7 | `ruff format` sobre los 8 ficheros portados que la rama dejó sin formatear | — | `ruff format --check` marcaba 8 de 17 ficheros portados |

El paso L4 es el hallazgo metodológico de este WP: **el laboratorio pasa con el tronco aunque el broker no sea el medido**. Los tres escenarios salieron `OK` con el digest de `E2E-COMMITTED` y `E2E-SCENARIO` idéntico, y sólo `E2E-RESTART` delataba la diferencia. Un port que se hubiera validado con un solo escenario habría publicado un falso éxito.

### Rama resultante: `integration/wp00303-min`

| Commit | Contenido |
| --- | --- |
| `31b8d223` | guardia de aislamiento + corpus holdout (11 ficheros) |
| `021d614d` | 3 scripts del laboratorio (2 629 líneas) |
| `4c60683c` | broker + runtime de decisión (6 ficheros, +526/−53) |
| `04aeb308` | `risk/manager.py` (+82/−3) |
| `7e4971d1` | formato de los 8 ficheros portados |
| `baf5b560` | `src/trading_bot/ops/` (2 ficheros, 499 líneas) |

**23 ficheros, +4 472 / −88 líneas** (19 de código/config y test, +4 393 líneas; 4 de dataset, 1.6 MB en 79 líneas porque son JSON de una sola línea), frente a 1 864 ficheros y +1 990 709 líneas de la rama.

### Equivalencia económica, medida

| Escenario | Digest publicado | Digest en la rama mínima | Igual |
| --- | --- | --- | --- |
| `E2E-COMMITTED` | `20f10f30bb6ce539…` | `20f10f30bb6ce539…` | **sí** |
| `E2E-SCENARIO` | `59dc36111fad5be5…` | `59dc36111fad5be5…` | **sí** |
| `E2E-RESTART` | `45ada80c456bf79b…` | `45ada80c456bf79b…` | **sí** |

Además, en el port **antes** de formatear, los **13 `runtime_sha256` son byte-idénticos** a los de la evidencia publicada y el bloque `dataset` es idéntico (mismo `manifest_sha256` `883a4fd3…`). Sólo difieren identificadores por corrida (`position_id`, `trade_id`, `*_order_id`) y relojes de pared (`opened_at`, `closed_at`); ningún campo económico.

El commit de formato (`7e4971d1`) cambia los bytes de 5 de esos 13 ficheros y **deja los 3 digests idénticos**: es la prueba de que el formateo es semánticamente inerte, y también el motivo por el que el propietario puede elegir entre conservar la identidad byte a byte (descartar ese commit) o el gate de formato en verde (conservarlo). No hay una opción que dé ambas cosas sin reformatear también los ficheros del tronco.

## 4. Dependencias no satisfechas en la base (defectos, no preferencias)

| # | Test commiteado | Módulo/símbolo que importa | Dónde existe | Estado |
| --- | --- | --- | --- | --- |
| D1 | `tests/unit/autonomous/test_{lab_ops_hardening,pid_identity,supervisor}.py`, `tests/unit/forward/test_forward_exit_contract.py` (tronco, 2026-09-29/10-01) | `trading_bot.ops` | sólo rama, `fe9b5e26` (2026-10-18) | **reparado** en `baf5b560`: 4 errores de colección → 0 |
| D2 | `tests/unit/observability/test_vision_panel.py` (`5fd791d8`) | `trading_bot.observability.vision_panel` | **en ningún commit**: existe sin versionar en 6 worktrees | **abierto**, ajeno a este WP |
| D3 | `tests/unit/research/test_edge16_pit.py` (`6f04e59b`) | `alpha15.PRE_PIT_RUNNERS` | `8eb4a2c1`/`9f3892f6`/`611db47e`, en 4 ramas hermanas | **abierto**, requiere decisión del titular |

D1 demuestra que el tronco **no era publicable tal cual**: en `1d2192b0` la suite ni siquiera colecciona. D2 y D3 son tests commiteados sin su módulo: el defecto es de quien publicó el test, no del pipeline.

## 5. Secuencia de integración propuesta

Tres PR pequeñas, cada una con su propia causa y su propia verificación. **Ninguna se ejecuta en `main` sin autorización del titular.**

### PR-1 · Reparar el job de smoke (`fix/ci-smoke-pwsh`, local `9682ee1b`)

`microsoft/powershell@v1.1.0` **no existe**: ni tag ni `action.yml` (404 en GitHub). Por eso el job muere en `Set up job`, antes del checkout. `ubuntu-latest` ya trae pwsh y los dos pasos ya piden `shell: pwsh`, así que el paso de instalación sólo rompía el job. Se elimina **una** línea de `uses:` y se corrigen los comentarios que la describían.

- Alcance: 1 fichero (`.github/workflows/ci.yml`), −7/+8 líneas de comentario y la eliminación del `uses:`.
- Verificación local: YAML parseado; el job queda con un único `uses:` (`actions/checkout@v4`); `scripts/open-pr-tsk-0204.ps1` parsea con **0 errores** y 551 tokens usando la misma API `Language.Parser` que el paso (proxy en PowerShell 5.1 local, no pwsh 7).
- Verificación real pendiente: **sólo se demuestra ejecutando el workflow**. Requiere publicar una rama.

### PR-2 · Publicar el tronco (fast-forward de 259 commits)

Sin force, sin merge: `origin/main` es ancestro. Reduce la PR de 498 a 239 commits y de 3 452 a 1 864 ficheros.

**Pero no es gratis, y esta es la medición que faltaba:**

| Gate | `origin/main` `5e6f9632` | tronco `1d2192b0` | rama `afc01270` | rama mínima |
| --- | --- | --- | --- | --- |
| `ruff format --check .` | **0** | **433 ficheros** | 617 | **428** (0 propios; 5 menos que el tronco) |
| `ruff check .` | **0** | **100 errores** | 195 / 44 ficheros | 100 (todos del tronco) |
| `mypy .` | **0** | **253 errores** | 622 / 107 ficheros | 253 (todos del tronco) |
| Colección de la suite | 582 tests OK | **4 errores** | 2 errores | **0 errores** |
| `pytest --cov-fail-under=90` | falla: 62.34 % | — | — | — |
| `pip-audit` | falla: 80 avisos | — | falla: 11 | — |

Publicar el tronco **pone rojo en `main` el formato, el lint y los tipos**. Arreglarlo exige `ruff format` sobre 433 ficheros de 259 commits ajenos: exactamente lo prohibido. La alternativa —estrechar el gate a los ficheros cambiados— es un cambio de política de CI, no una reparación, y decide el titular.

### PR-3 · WP-003-03 mínimo (`integration/wp00303-min`, 6 commits sobre el tronco)

Sólo existe **encima del tronco**: el runtime que ejerce (`autonomous/`, `paper/`) no está en `origin/main`. Es decir, WP-003-03 **no es separable** del tronco; lo que sí es separable es de las otras 236 commits de la rama.

- Alcance: 23 ficheros, +4 472 / −88, 0 deuda nueva de formato/lint/tipos.
- Verificación: 3/3 escenarios, 8/8 escenarios de abuso, digests económicos idénticos, 13/13 hashes de runtime idénticos, 37 tests del WP y de la guardia en verde, verificador independiente 14/18 con 11/11 controles negativos rechazados (los 4 no verdes son de empaquetado de evidencia y estado remoto, ver `RUN_REPORT.md` §6).

### Orden y dependencias

```
PR-1  pipeline (independiente)
  └─ desbloquea: el job de smoke deja de morir antes del checkout
PR-2  tronco (fast-forward)              ← bloqueada por decisión del titular (formato 433 ficheros)
  └─ desbloquea: PR-3 revisable (239 commits en vez de 498)
PR-3  WP-003-03 mínimo (sobre PR-2)
  └─ bloqueada por PR-2 (el runtime no existe en main)
```

## 6. Lo que este WP no hace

- No publica en `main`, no fusiona la PR #17, no hace force-push, no reescribe ramas compartidas.
- No reformatea el repositorio: `ruff format` se aplicó a 8 ficheros portados, no a 433.
- No degrada gates: cobertura 90 %, `pip-audit` y los marcadores `slow`/`market` intactos.
- No borra ni silencia tests: los 4 errores de colección se cerraron **portando el módulo**, no ignorando los tests.
- No declara `PRODUCTION_READY` ni habilita LIVE.

## 7. Reproducir este mapa

```bash
git fetch --prune origin
git rev-parse origin/main main wp/isolation-005
git rev-list --count origin/main..main main..wp/isolation-005
git diff --numstat origin/main...wp/isolation-005 | awk -F'\t' '{a+=$1;b+=$2;n++} END {print n, a, b}'

# gate del tronco, árbol limpio
git worktree add --detach ../ff-wt-trunk 1d2192b0
cd ../ff-wt-trunk && ruff format --check . && ruff check . && mypy .
PYTHONPATH=src pytest -m "not slow and not market" -q     # 4 errores de colección

# rama mínima
cd ../ff-wt-min && git log --oneline main..HEAD
PYTHONPATH=src python scripts/paper_e2e_lab.py --out .tmp/lab --json .tmp/PAPER_E2E_LAB.json
python scripts/verify_paper_e2e.py --lab .tmp/PAPER_E2E_LAB.json --bundle .tmp \
  --repo . --evidence-sha "$(git rev-parse HEAD)" --repeat .tmp/PAPER_E2E_LAB.json \
  --negative-controls --json .tmp/VERIFICATION.json
```
