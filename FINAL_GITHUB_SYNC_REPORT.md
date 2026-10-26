# FINAL_GITHUB_SYNC_REPORT — Trading Agentic Portable → `Extr3sao/bot_crypto`

**Fecha:** 2026-10-26 · **Agente:** Codebuff (Buffy) · **Estado final:** `PARTIAL_SYNC`

> **`SYNC_COMPLETE ≠ MAIN_INTEGRATED ≠ RUNTIME_CERTIFIED ≠ PROFITABLE`**
> Publicar código no integra `main`, no certifica el runtime y no demuestra rentabilidad.

---

## RESUMEN EJECUTIVO

**Qué estaba solo en local → qué se publicó → qué se integró → qué sigue bloqueado → qué falta para arrancar PAPER y medir beneficios.**

| | Estado |
|---|---|
| **Solo en local (antes)** | 226 commits sin publicar en 17 ramas, 15 worktrees sucios (1338 entradas sucias en el checkout principal + 246 ficheros sin commit en otros 14), 0 stashes, 0 huérfanos recuperables |
| **Se publicó** | **35/35 ramas** con `SHA local == SHA remoto`; **0 commits** inalcanzables desde `origin/*`; 15 ramas de preservación nuevas; **31 PR draft** (`#19`–`#35`, `#36`–`#49`); roadmap **v1.7**; los 4 reportes + manifiesto de exclusiones |
| **Se integró en `main`** | **Nada.** `origin/main` sigue en `5e6f9632`, **263 commits por detrás**; no se hizo push a `main`, no se hizo merge, no se forzó ninguna rama |
| **Sigue bloqueado** | Gates de `main` en rojo (ruff 130 / format 444 / mypy 297 / pytest 79F-3274P-14E); PR `#19` `BLOCKED` por error de colección; 31 PR en draft `NOT_VERIFIED`; `recovery/mt0003-kill-switch-*` crítico de riesgo |
| **Falta para PAPER** | 1) integrar el linaje (`PR #18`) y poner los gates en verde, 2) arreglar la colección de `test_failfast.py`, 3) autorizar el arranque de PAPER (host + `WP-005H`), 4) `REAL_MODEL_CALLED=false` → ningún LLM real invocado, 5) ninguna estrategia admitida ni rentabilidad demostrada |

---

## 1. INVENTARIO

### 1.1 Repositorios y worktrees

- **1 repositorio**: `origin = https://github.com/Extr3sao/bot_crypto.git`, checkout principal `C:/Users/GVLLFR0035/Downloads/bot freebuff` (sobre `sync/uncommitted-main-20261025`).
- **46 worktrees registrados al cierre**: los **26** del inventario inicial (respaldo 2026-10-25 19:29) + **20** creados durante la sesión (14 `Downloads/sync-preserve/*` para reconstruir el trabajo sucio **sin tocar** los originales, `gate-main-20261026` de validación, `wt-originmain`, `clean-sync-branch`, `roadmap-wt` y dos `tdm14a-base`). **0 worktrees eliminados** (`comm` inicial vs actual: lista de eliminados vacía).
- Worktrees sucios al inicio (15): `bot freebuff` (1338), `ff-wt-tdm06` (81), `ff-wt-tdm11` (47), `ff-wt-tdm09-repro` (36), `ff-wt-tdm12` (29), `exp004a-recovery-02k` (20), `ff-wt-tdm08` (20), `ff-wt-tdm13` (10), `ff-wt-trunkfmt` (7), `ff-wt-tdm14a` (6), `recovery-rehearsal/checkout` (5), `ff-wt-base` (2), `ff-wt-adm002` (1), `ff-wt-eco001` (1), `ff-wt-g7` (1).

### 1.2 Ramas y commits

| Métrica | Inicial | Final |
|---|---|---|
| Ramas locales | 19 | **35** (20 preexistentes + 15 de preservación) |
| Ramas remotas | 73 | 88 |
| Commits locales sin publicar | **226** | **0** (`git rev-list --branches --not --remotes=origin`) |
| Ramas sin remoto | 17 | **0** |
| Ramas divergentes / sobrescritas | — | **0** |
| Stashes / huérfanos reflog | 0 / 0 | 0 / 0 |

### 1.3 Trabajo sin commit encontrado y preservado

| Rama de preservación | SHA | Worktree de origen | Ficheros |
|---|---|---|---|
| `sync/uncommitted-main-20261025` | `5b63f265` | checkout principal | 153 (8 commits) |
| `sync/uncommitted-ff-wt-tdm06-20261025` | `f6429009` | `ff-wt-tdm06` | 74 |
| `sync/uncommitted-ff-wt-tdm11-20261025` | `1010e3f8` | `ff-wt-tdm11` | 47 |
| `sync/uncommitted-ff-wt-tdm09-repro-20261025` | `809e1b71` | `ff-wt-tdm09-repro` | 34 |
| `sync/uncommitted-ff-wt-tdm12-20261025` | `81119831` | `ff-wt-tdm12` | 29 |
| `sync/uncommitted-exp004a-recovery-02k-20261025` | `4304a8ed` | `exp004a-recovery-02k` | 19 |
| `sync/uncommitted-ff-wt-tdm08-20261025` | `87e47c01` | `ff-wt-tdm08` | 19 |
| `sync/uncommitted-ff-wt-tdm13-20261025` | `57ea2e70` | `ff-wt-tdm13` | 10 |
| `sync/uncommitted-ff-wt-tdm14a-20261025` | `c9122043` | `ff-wt-tdm14a` | 7 |
| `sync/uncommitted-ff-wt-trunkfmt-20261025` | `76f94096` | `ff-wt-trunkfmt` | 7 |
| `sync/uncommitted-recovery-rehearsal-9vicsg7h-20261025` | `a69fc7e6` | checkout de ensayo en `%TEMP%` | 4 |
| `sync/uncommitted-ff-wt-base-20261025` | `3247989a` | `ff-wt-base` | 2 |
| `sync/uncommitted-ff-wt-adm002-20261025` | `7fae86c6` | `ff-wt-adm002` | 1 |
| `sync/uncommitted-ff-wt-eco001-20261025` | `b8874ac7` | `ff-wt-eco001` | 1 |
| `sync/uncommitted-ff-wt-g7-20261025` | `3e3d6c6f` | `ff-wt-g7` | 1 |

Los worktrees originales **no se modificaron**: el trabajo se reconstruyó en worktrees separados (`sync-preserve/*`), se versionó allí y se publicó.

### 1.4 Cambios preservados

- Respaldo previo a tocar Git: `C:/Users/GVLLFR0035/Downloads/sync-backup-20261025/` con `worktrees.txt`, `branch-shas.txt`, `main-status.txt`, `main-tracked-changes.patch`, copias de los 17 ficheros modificados, copias de los 135 sin seguimiento del checkout principal y, por cada worktree, `head.txt`, `status.txt`, `tracked.patch`, `staged.patch`, `untracked.txt` y `files/`.
- **Verificación de integridad re-ejecutada hoy: `sha256sum -c SHA256SUMS.txt` → 554/554 OK.**

### 1.5 Archivos excluidos por seguridad / tamaño / política

Manifiesto `EXCLUDED_FROM_SYNC_MANIFEST.json` (24 959 ficheros, ~846 MB) con SHA-256 y motivo por fichero/árbol:

| Árbol | Ficheros | Motivo |
|---|---|---|
| `wt-sup001/`, `tdm14a-base/` | 19 030 | worktrees anidados; su contenido ya está publicado en `codepaper/supervisor-001` y `fix/tdm14a` |
| `.venv_recovery005/`, `.venv/` | 2 175 | entornos virtuales (política `.gitignore`) |
| `.tmp/` | 2 238 | scratch local (`.git/info/exclude`) |
| `__pycache__` / `*.egg-info` | 648 | generado |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/` | 387 | generado |
| `reports/`, `logs/`, `data/raw/` | 471+ | política `reports/*`, `logs/*`, `data/raw/*` |

**Ninguno se da por sincronizado.** No se publicó ningún `.env` (solo `.env.example` versionado).

---

## 2. PUBLICACIÓN

### 2.1 Ramas publicadas

Todas las ramas locales, con `git ls-remote` verificado (`local == remoto`):

`main`, `admission/integration-002`, `audit/economic-blocker-001`, `audit/g7-real-paper`,
`audit/mt0004-negative-controls`, `audit/supervisor-integration-001`, `codepaper/supervisor-001`,
`evidence/tdm11`, `evidence/tdm12`, `evidence/tdm13`, `fix/tdm14a`, `gate/integration-001`,
`integ/supervisor-002`, `paper/reald-data-001`, `project/roadmap-trading-agentic`,
`recovery/exp004a-02k-9983b050`, `recovery/mt0003-kill-switch-60455b46`, `recovery/trunk-format-001`,
`repro/economic-recovery-002`, `repro/paper-admission-001` + las 15 `sync/uncommitted-*`.

Commits publicados en esta sesión: **226 commits** + 15 ramas nuevas + el commit de roadmap **v1.7** (`b95c3119`).

### 2.2 PR creados / actualizados

| PR | Rama | Estado |
|---|---|---|
| #19 | `sync/uncommitted-main-20261025` | draft · **BLOCKED** (colección rota) |
| #36–#49 | 14 ramas `sync/uncommitted-*` | draft · preservación |
| #20–#35 | ramas de agente/evidencia | draft · `NOT_VERIFIED` |
| #18 | `admission/integration-002` → `main` | ready · **vehículo de integración** |
| #15 | `project/roadmap-trading-agentic` | ready · actualizado a **v1.7** |

Total de PR abiertos: **38** (7 ready, 31 draft).

### 2.3 Ramas sin PR (causa documentada)

- `audit/economic-blocker-001`: puntero idéntico a `main`; se rastrea por rama+SHA, evita duplicar el diff del PR #18.
- `main`: su integración es el PR #18.

### 2.4 Comparación LOCAL vs GITHUB

| | Inicial | Final |
|---|---|---|
| Commits sin publicar | 226 | **0** |
| Ramas locales sin remoto | 17 | **0** |
| Contenido de `main` en GitHub | no | sí (dentro de `admission/integration-002`) |
| Evidencias solo en local | `.tdm09`, `.tdm10`, `.ci`, `reports/` de worktrees | publicadas en las ramas correspondientes (y las excluidas, en el manifiesto) |
| Roadmap | v1.6 local | **v1.7 publicado** (`b95c3119`) |

---

## 3. INTEGRACIÓN

| Componente | Estado |
|---|---|
| Incorporado a `main` | **ninguno** (no se hizo merge ni push a `main`) |
| Pendiente | los 263 commits del linaje local, vía **PR #18** |
| Conflictos | no evaluados: no se ejecutó merge; `origin/main` es ancestro del linaje local → integración sería fast-forward |
| Dependencias ausentes | ninguna conocida: todo lo publicado es autosuficiente (los 246 ficheros sin commit quedaron versionados) |
| Fallos de CI | `CI Baseline` **failure** en todas las ramas y **también en `origin/main` desde 2026-07-10** → preexistente |
| Bloqueos de seguridad/gobernanza | `.env` no versionado; sin credenciales publicadas; `recovery/mt0003-kill-switch-*` exige revisión de **risk-manager** antes de fusionar |

---

## 4. VALIDACIÓN

Checkout **limpio** (`git worktree add --detach gate-main-20261026 e67194e7`, 2018 ficheros, sin ignorados locales), venv sincronizado del proyecto, `PYTHONPATH` apuntando al `src` limpio.

| Comando | Resultado | Exit |
|---|---|---|
| `python -m ruff check .` | 130 errores (81 auto-fixables) | 1 |
| `python -m ruff format --check .` | 444 ficheros a reformatear / 374 OK | 1 |
| `python -m mypy .` | 297 errores en 38 ficheros (812 comprobados) | 1 |
| `python -m pytest -q` | **79 failed, 3274 passed, 34 skipped, 14 errors** (512 s) | 1 |
| `python -m pytest --collect-only -q` | 3401 tests recogidos, 0 errores | 0 |
| `sha256sum -c SHA256SUMS.txt` (respaldo) | 554/554 OK | 0 |

### 4.1 ¿Regresión de la sincronización? No

- Ejecución previa del mismo commit (2026-10-25): `90 failed, 3263 passed, 31 skipped, 14 errors`.
- **ruff 130 / format 444 / mypy 297 idénticos** a los medidos en el corte v1.6 → reproducidos.
- **19 de 20** ficheros con fallos coinciden con la baseline; los fallos se concentran en `tests/unit/research/**` (RFC-035, cost-barrier, profitability-035, ST6) + 14 errores de fixture en `test_profitability_gate035.py`.
- La CI de GitHub ya fallaba sobre `origin/main` **antes** de sincronizar (2026-07-10 y 2026-09-22).
- Los ~11 tests que cambian entre ejecuciones son de hashes/timestamps (variabilidad temporal).

### 4.2 Runtime realmente ejecutado

- `pytest` completo sobre el runtime objetivo (`e67194e7`): **ejecutado**.
- Recolección sobre `5b63f265` (PR #19): **ejecutada y fallida** → `ImportError: YamlDirectorySource`.
- Runtime **paper** con datos reales: rama `paper/reald-data-001` publicada, **no ejecutada** en esta auditoría.
- **`REAL_MODEL_CALLED = false`**: cero imports de proveedores LLM en `src/`, cero llamadas a modelo real.

### 4.3 Verificación independiente

`BUILDER != VERIFIER` respetado: la construcción de reportes (`scripts/sync_audit_report.py`, `scripts/sync_exclusion_manifest.py`, `scripts/roadmap_update_v17.py`) y la verificación (`git rev-list`, `git ls-remote`, `sha256sum -c`, ejecución de gates en checkout limpio) son pasos separados y ambos dejaron salida en consola.

**`FALSE_SUCCESS = 0`**: ningún PASS declarado sin ejecución; los 31 PR en draft se declaran `NOT_VERIFIED`.

---

## 5. ROADMAP

Rama `project/roadmap-trading-agentic`, commit **`b95c3119`** (v1.7) publicado, proyecciones **JSON + CSV + XLSX** actualizadas en el mismo commit más `README.md`:

- `TAP-072` → `VERIFICADO_FOCAL`: 0 commits sin publicar, 35/35 ramas verificadas, reportes publicados.
- `TAP-073` → `BLOQUEADO`: gates re-meditos 2026-10-26 (130/444/297 + `79F/3274P/34S/14E`).
- `TAP-075` → `PENDIENTE`: 31 PR draft (#19-#35 y #36-#49).
- `TAP-076` → `BLOQUEADO`: colección rota re-verificada (3532 tests + 1 error).

Ningún estado `VERIFICADO_FOCAL` se convirtió en `CERTIFIED`.

### 5.1 Qué ya está en GitHub

Todo el código, tests, documentos, RFCs, evidencias y roadmap del proyecto.

### 5.2 Qué falta para integrar

1. Revisar y fusionar **PR #18** (fast-forward de 263 commits).
2. Poner los gates en verde (ruff/format/mypy/pytest) — baseline preexistente.
3. Restaurar `load_settings`/`YamlDirectorySource` para desbloquear el PR #19.

### 5.3 Próximo bloqueo operativo para arrancar PAPER

Autorización de host + lease `WP-005H` (`TAP-071`, issue #16) y gates en verde; el carril de PAPER con datos reales ya está publicado (`paper/reald-data-001`).

### 5.4 Próximo bloqueo económico para demostrar rentabilidad

No hay estrategia admitida: los gates de rentabilidad (`tests/unit/research/test_profitability_gate035.py`, cost-barrier) están **en rojo** en la baseline y ningún escenario ha superado costes + slippage de forma reproducible. Sin eso, `PROFITABLE` sigue en `false`.

---

## 6. DEFINICIÓN DE DONE

| # | Criterio | Estado |
|---|---|---|
| 1 | Todo trabajo local válido y publicable está respaldado y en GitHub | ✅ 35/35 ramas, 0 commits sin publicar |
| 2 | Sin commits locales sin publicar (salvo exclusiones justificadas) | ✅ `git rev-list --branches --not --remotes = 0`; exclusiones en manifiesto |
| 3 | Worktrees intactos | ✅ 0 worktrees borrados; originales sin modificar; respaldo 554/554 OK |
| 4 | Sin ramas sobrescritas ni datos eliminados | ✅ 0 divergencias, sin `reset --hard`/`clean -fd`/`push --force`/rebase |
| 5 | Sin secretos publicados | ✅ escaneo de 89 MB de parches: 0 claves; `.env` no versionado |
| 6 | Commits remotos verificados | ✅ `git ls-remote` local == remoto en las 35 ramas |
| 7 | Integraciones pendientes trazadas en PR o bloqueo | ✅ PR #18, #15, #19-#49 + bloqueos documentados |
| 8 | Informe que refleja resultados reales | ✅ este documento + `LOCAL_GITHUB_SYNC_AUDIT.*` |

**Resultado: `PARTIAL_SYNC`** — la publicación está completa (`SYNC_COMPLETE` en cuanto a publicación), pero `MAIN_INTEGRATED = false`, `RUNTIME_CERTIFIED = false`, `PROFITABLE = false`.
