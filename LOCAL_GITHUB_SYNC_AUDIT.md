# LOCAL_GITHUB_SYNC_AUDIT — Trading Agentic Portable → `Extr3sao/bot_crypto`

**Fecha:** 2026-10-25 · **Agente:** Codebuff (Buffy) · **Estado:** `PARTIAL_SYNC` (publicación completa, integración pendiente)

- Repositorio: `origin = https://github.com/Extr3sao/bot_crypto.git`
- Checkout principal: `C:/Users/GVLLFR0035/Downloads/bot freebuff`
- Respaldo previo a tocar Git: `C:/Users/GVLLFR0035/Downloads/sync-backup-20261025` (554 ficheros con `SHA256SUMS.txt`)

> `SYNC_COMPLETE != MAIN_INTEGRATED != RUNTIME_CERTIFIED != PROFITABLE`
> Publicar código **no** convierte un estado en `CERTIFIED` ni demuestra rentabilidad.

---

## 1. Inventario inicial (antes de tocar Git)

| Métrica | Valor |
|---|---|
| Repositorios Git | 1 (`bot_crypto`) |
| Worktrees registrados | 26 |
| Stashes | 0 |
| Ramas locales | 19 |
| Ramas remotas | 73 |
| Commits locales inalcanzables desde cualquier remoto | **226** |
| Ramas locales sin nombre en remoto | 17 |
| Entradas sucias en el checkout principal | 1338 (17 modificadas + 1185 del venv + 136 sin seguimiento) |
| Archivos sin seguimiento en otros worktrees sucios | 246 en 14 worktrees |
| Commits locales sin publicar | **226 → 0** (verificado tras la publicación) |

Worktrees sucios al inicio: `bot freebuff` (1338), `ff-wt-tdm06` (81), `ff-wt-tdm11` (47),
`ff-wt-tdm09-repro` (36), `ff-wt-tdm12` (29), `exp004a-recovery-02k` (20), `ff-wt-tdm08` (20),
`ff-wt-tdm13` (10), `ff-wt-trunkfmt` (7), `ff-wt-tdm14a` (6), `recovery-rehearsal…/checkout` (5),
`ff-wt-base` (2), `ff-wt-adm002` (1), `ff-wt-eco001` (1), `ff-wt-g7` (1).

---

## 2. Inventario por rama

`Ahead` se mide contra `origin/main` (`5e6f9632`). **`origin/main` es ancestro de todo el
linaje local**, así que un `Ahead` alto no implica divergencia: implica que `origin/main`
está desfasado. `Dirty`/`Untracked` son los valores del inicio de la auditoría.

| Branch | Local HEAD | Remote HEAD | Ahead | Worktree | Dirty | Untracked | Runtime reachable | Tests | Evidence | Sync status | Target PR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `main` | `e67194e7` | `5e6f9632` | +263 / −0 | `bot freebuff` | 1338 → 0 | 1185 venv + 136 | RUNTIME_REACHABLE | **FAIL** 90F/3263P/14E | — | `ALREADY_PUBLISHED` (contenido en `origin/admission/integration-002`); **no se hizo push** | #18 |
| `admission/integration-002` | `3c967185` | `3c967185` | +? | `ff-wt-adm002` | 1 | 0 | NOT_VERIFIED | CI en GitHub | reports | `ALREADY_PUBLISHED` | #18 (abierto) |
| `audit/economic-blocker-001` | `e67194e7` | `e67194e7` | +263 | — | — | — | NOT_VERIFIED | NOT_RUN | — | `PUBLISHED` | sin PR (idéntica a `main`) |
| `audit/g7-real-paper` | `ea87dc1f` | `ea87dc1f` | +614 | `ff-wt-g7` | 1 | 0 | NOT_VERIFIED | CI **FAIL** | reports G-7 | `PUBLISHED` | #35 (draft) |
| `audit/mt0004-negative-controls` | `d5e599ec` | `d5e599ec` | +602 | `ff-wt-mt0004` | 0 | 0 | NOT_VERIFIED | CI **FAIL** | reports | `PUBLISHED` | #34 (draft) |
| `audit/supervisor-integration-001` | `a8abd83e` | `a8abd83e` | +264 | `ff-wt-audit001` | 0 | 0 | NOT_VERIFIED | NOT_RUN | reports (24) | `PUBLISHED` | #22 (draft) |
| `codepaper/supervisor-001` | `3b758e22` | `3b758e22` | +560 | `bot freebuff/wt-sup001` | 0 | 0 | NOT_VERIFIED | NOT_RUN | reports | `PUBLISHED` | #23 (draft) |
| `evidence/tdm11` | `504256ec` | `504256ec` | +264 | `ff-wt-tdm11` | 47 | 47 | `TEST_ONLY` | CI **FAIL** | evidence (11) | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #30 (draft) |
| `evidence/tdm12` | `a96e9c80` | `a96e9c80` | +265 | `ff-wt-tdm12` | 29 | 29 | `TEST_ONLY` | CI **FAIL** | evidence (25) | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #31 (draft) |
| `evidence/tdm13` | `04fb8bc8` | `04fb8bc8` | +268 | `ff-wt-tdm13` | 10 | 10 | `TEST_ONLY` | CI **FAIL** | evidence (62) | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #32 (draft) |
| `fix/tdm14a` | `f8ae0243` | `f8ae0243` | +271 | `ff-wt-tdm14a` | 6 | 6 | `TEST_ONLY` | CI en curso | evidence (64) | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #29 (draft) |
| `gate/integration-001` | `55f991b7` | `55f991b7` | +273 | `ff-wt-gate001` | 0 | 0 | NOT_VERIFIED | NOT_RUN | reports (436) | `PUBLISHED` | #20 (draft) |
| `integ/supervisor-002` | `7d18140c` | `7d18140c` | +269 | `ff-wt-integ002` | 0 | 0 | NOT_VERIFIED | NOT_RUN | reports (168) | `PUBLISHED` | #21 (draft) |
| `paper/reald-data-001` | `8c2bc174` | `8c2bc174` | +265 | `ff-wt-prd001` | 0 | 0 | `RUNTIME_REACHABLE` (campaña PAPER real) | CI **FAIL** | docs (43) | `PUBLISHED` | #33 (draft) |
| `recovery/exp004a-02k-9983b050` | `c727b614` | `c727b614` | +572 | `exp004a-recovery-02k` | 20 | 19 | NOT_VERIFIED | NOT_RUN | docs | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #26 (draft) |
| `recovery/mt0003-kill-switch-60455b46` | `60455b46` | `60455b46` | +557 | — | 0 | 0 | NOT_VERIFIED | NOT_RUN | reports | `PUBLISHED` | #24 (draft, **crítico de riesgo**) |
| `recovery/trunk-format-001` | `dc21870f` | `dc21870f` | +265 | `ff-wt-trunkfmt` | 7 | 6 | NOT_VERIFIED | NOT_RUN | reports (17) | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #25 (draft) |
| `repro/economic-recovery-002` | `c1c1dbfe` | `c1c1dbfe` | +280 | `ff-wt-eco001` | 1 | 1 | NOT_VERIFIED | NOT_RUN | docs | `PUBLISHED` + `LOCAL_UNCOMMITTED` preservado | #27 (draft) |
| `repro/paper-admission-001` | `fda95664` | `fda95664` | +567 | `ff-wt-repro001` | 0 | 0 | NOT_VERIFIED | CI **FAIL** | reports (1327) | `PUBLISHED` | #28 (draft) |
| `sync/uncommitted-main-20261025` | `5b63f265` | `5b63f265` | +271 | `bot freebuff` | 1338 → 0 | 135 → 0 | **`BLOCKED`** (recolección rota) | **FAIL** (collection error) | `.tdm09`, `.tdm10`, `.ci`, `data/rfc048` | `PUBLISHED_WIP` | #19 (draft) |
| `project/roadmap-trading-agentic` | `1022e3b7` | `1022e3b7` | (rama remota) | `roadmap-wt` | 0 | 0 | NOT_VERIFIED | CI **FAIL** | roadmap xlsx/json/csv | `PUBLISHED` (v1.6) | #15 (abierto) |

### 2.1 Ramas de preservación creadas por la auditoría

El estado sin commit de cada worktree sucio se reconstruyó en un worktree **separado**
(la copia original nunca se tocó) y se publicó como WIP:

| Rama de preservación | SHA | Origen | Ficheros |
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

Todas verificadas: `git rev-parse <rama>` == `git rev-parse origin/<rama>`.

---

## 3. Clasificación de estados

| Estado | Qué significa | Dónde cae |
|---|---|---|
| `UNPUBLISHED` | commit local sin remoto | **0 al cierre** (226 al inicio) |
| `REMOTE_DIVERGED` | remoto avanzado de forma incompatibile | **0** (ninguna rama se sobrescribió) |
| `ALREADY_PUBLISHED` | ya estaba en remoto | `admission/integration-002`, y todo el contenido de `main` |
| `LOCAL_UNCOMMITTED` | cambios sin commit en un worktree | 15 worktrees → **preservados y publicados** en ramas `sync/uncommitted-*` |
| `RECOVERABLE_ORPHAN` | commit huérfano recuperable (reflog/stash) | **0** (reflog sin huérfanos, 0 stashes) |
| `BLOCKED` | publicado pero no integrable | `sync/uncommitted-main-20261025` (recolección rota), `recovery/mt0003-*` (crítico de riesgo), resto de PR draft `NOT_VERIFIED` |

**Código publicado ≠ código integrado en `main`.** `origin/main` sigue en `5e6f9632`;
ninguna rama se fusionó y `main` no se fuerza.

---

## 4. Protección del trabajo local (orden ejecutado)

1. `git worktree list --porcelain`, `git stash list`, `git reflog --all` — inventario completo.
2. Respaldo **fuera** de todo directorio a modificar:
   `sync-backup-20261025/` con `worktrees.txt`, `branch-shas.txt`, `main-status.txt`,
   `main-tracked-changes.patch`, copias de los 17 ficheros modificados, copias de los
   135 ficheros sin seguimiento del checkout principal, y por cada uno de los 26
   worktrees: `path.txt`, `head.txt`, `status.txt`, `tracked.patch`, `staged.patch`,
   `untracked.txt` y `files/` con los 246 ficheros sin seguimiento.
3. `SHA256SUMS.txt` con el digest de los 554 ficheros del respaldo (verificación).
4. Escaneo de secretos sobre las líneas añadidas de los 234 commits a publicar
   (89 MB de parche): **0** claves con forma (private keys, `ghp_`, `github_pat_`,
   `AKIA`, `xox[bars]-`, `sk-`, `AIza`, `Bearer`). Únicos coincidentes: tokens de
   candado `TAP_SINGLE_WRITER_LOCK_V1` (32 hex, no son credenciales) y aserciones
   `expected_token` de tests. `.env` no versionado (solo `.env.example`).
5. Ningún `git reset --hard`, `git clean -fd`, `git push --force`, rebase, borrado de
   worktree/rama/commit/stash. Ningún checkout en un worktree con cambios pendientes.

---

## 5. Exclusiones (nada declarado como sincronizado)

Manifiesto: **`EXCLUDED_FROM_SYNC_MANIFEST.json`** (24 959 ficheros, 846 MB) con
SHA-256 por fichero o digest de árbol y el motivo:

| Árbol | Ficheros | Motivo |
|---|---|---|
| `wt-sup001/` | 16 934 | worktree anidado; contenido ya publicado en `codepaper/supervisor-001` |
| `tdm14a-base/` | 2 096 | worktree anidado; contenido ya publicado en `fix/tdm14a` |
| `.venv_recovery005/` | 2 166 | entorno virtual (política `.gitignore`) |
| `.tmp/` | 2 238 | scratch local (`.git/info/exclude`) |
| `.venv/` | 9 | entorno virtual |
| `src/`, `tests/`, `scripts/` (`__pycache__`, `egg-info`) | 648 | generado |
| `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/` | 387 | generado |
| `reports/` (383), `logs/`, `data/raw/alpha002/` | 471 | política `reports/*`, `logs/*`, `data/raw/*` de `.gitignore` |

Ninguno de estos ficheros se da por sincronizado.

---

## 6. Publicación — resultado verificado

Verificación `git rev-list --branches --not --remotes=origin --count` tras la publicación:

| Métrica | Inicial | Final |
|---|---|---|
| Commits locales inalcanzables desde cualquier `origin/*` | 226 | **0** |
| Ramas locales sin remoto | 17 | **0** (35/35 con remoto) |
| Ramas con `SHA local == SHA remoto` | 18 | **35** |
| Ramas divergentes / sobrescritas | — | **0** (todas `ahead=0 behind=0`, `main` solo adelantada) |
| Stashes | 0 | 0 (no había nada en stash) |
| Commits huérfanos recuperables (reflog) | **40** (se re-miraron con `git reflog --all`) | **40 preservados y publicados** como tags `sync/orphan-<sha12>` |

### 6.1 Cierre de la sesión (2026-10-26, revisión independiente)

- **40 commits huérfanos** alcanzables solo desde el reflog (versiones sustituidas por `amend`/`rebase`
  del 23-25/10) fueron etiquetados `sync/orphan-<sha12>` y publicados con
  `git push origin 'refs/tags/sync/orphan-*'` → **40/40 verificados con `git ls-remote --tags`**.
  Sin esto habrían expirado con el reflog (90 días) sin copia en GitHub.
- **Commits nuevos aparecidos durante la sesión y publicados**: `fix/tdm14a` (`5f42de14`, `409050c3`,
  `c8a8af16` + 8 commits de cierre TDM-14A, carrera con otro agente), `project/roadmap-trading-agentic`
  `b95c3119` (v1.7) y la rama nueva `feat/wp-signal-001-003` (`98371acf`, WIP).
- **Verificación de gates independiente** (`BUILDER != VERIFIER`): un `git clone` **nuevo** de
  `e67194e7` (`gate-check-main-20261026`, 0 entradas sucias) con su propio `uv sync`, ejecutado con
  los flags de CI (`pytest -m "not slow and not market" --cov --cov-fail-under=90`):

  | Comando | Resultado | Exit |
  |---|---|---|
  | `uv sync --all-extras --dev` | OK | 0 |
  | `ruff format --check .` | 444 a reformatear / 374 OK | 1 |
  | `ruff check .` | 130 errores (81 auto-fixables) | 1 |
  | `mypy .` | 297 errores en 38 ficheros (812 comprobados) | 1 |
  | `pytest -m "not slow and not market" --cov --cov-fail-under=90` | 78 failed, 3275 passed, 31 skipped, 3 deselected, 14 errors (786 s) | 1 |
  | cobertura | 76,01 % < 90 % requerido | 1 |

  Reproduce **exactamente** ruff 130 / format 444 / mypy 297 de la medición del worktree
  `gate-main-20261026` con un método distinto (clone vs worktree) → el rojo es del commit,
  no del checkout ni de esta sincronización.

- `main` local `e67194e7` sigue **263 commits por delante** de `origin/main` `5e6f9632` y **no se hizo push**:
  su contenido ya está en GitHub dentro de `origin/admission/integration-002` `3c967185` (PR #18), que lo
  contiene íntegro (`main..origin/admission/integration-002 = 0`). Integración controlada, no fuerza.
- **31 PR en draft** abiertos por la auditoría: `#19` (checkout principal) y `#36`–`#49` (14 ramas de
  preservación), más `#20`–`#35` de las ramas de agente ya publicadas.
- **Sin PR (documentado):** `audit/economic-blocker-001` (puntero idéntico a `main`, se rastrea por rama+SHA)
  y `main` (su integración es el PR #18).
- Push verificado con `git ls-remote --heads origin` para las 35 ramas.

---

## 7. Validación — gates ejecutados (2026-10-26)

Checkout **limpio** creado con `git worktree add --detach gate-main-20261026 e67194e7` (commit que pretende
integrar el PR #18), sin archivos ignorados locales, ejecutando el venv sincronizado del proyecto con
`PYTHONPATH` apuntando al `src` del checkout limpio (`TEST_TARGET == RUNTIME_TARGET`):

| Comando | Resultado | Exit | Estado |
|---|---|---|---|
| `python -m ruff check .` | **130 errores** (81 auto-fixables) | 1 | **FAIL** |
| `python -m ruff format --check .` | **444 ficheros** a reformatear / 374 ya formateados | 1 | **FAIL** |
| `python -m mypy .` | **297 errores en 38 ficheros** (812 comprobados) | 1 | **FAIL** |
| `python -m pytest -q` | **79 failed, 3274 passed, 34 skipped, 14 errors** (512 s) | 1 | **FAIL** |
| `python -m pytest --collect-only -q` | 3401 tests recogidos, 0 errores de colección | 0 | PASS |

### 7.1 ¿Es regresión de la sincronización? No — es baseline preexistente

| Evidencia | Resultado |
|---|---|
| Ejecución previa del mismo commit `e67194e7` (2026-10-25 20:08) | `90 failed, 3263 passed, 31 skipped, 3 deselected, 14 errors` |
| Ejecución de hoy (2026-10-26) | `79 failed, 3274 passed, 34 skipped, 14 errors` |
| `ruff check` / `ruff format --check` / `mypy` | **130 / 444 / 297 — idénticos a los del corte v1.6** (reproducidos) |
| Ficheros con fallos en común entre ambas ejecuciones | **19 de 20** (solo aparece `test_st6_forward_regime.py` hoy) |
| Concentración de fallos | `tests/unit/research/**` (RFC-035, cost-barrier, profitability-035, ST6) + 14 errores en `test_profitability_gate035.py` |
| CI de GitHub (`CI Baseline`) sobre `origin/main` | **failure desde 2026-07-10 y 2026-09-22** → el rojo ya existía antes de sincronizar |
| `origin/main` `5e6f9632` en checkout limpio propio | `582 passed` exit 0 (suite antigua, 263 commits por detrás) |

Los ~11 tests que cambian de resultado entre ejecuciones son de hashes/timestamps (verificación de
digests y run-log): variabilidad temporal, no regresión introducida por esta sincronización.

### 7.2 Bloqueo real detectado en la rama publicada (PR #19)

Sobre el puntero de `sync/uncommitted-main-20261025` (`5b63f265`):

```
tests/unit/config/test_failfast.py:23: in <module>
    from trading_bot.config.settings import YamlDirectorySource
E   ImportError: cannot import name 'YamlDirectorySource' ...
!!!! Interrupted: 1 error during collection — 3532 tests collected, 1 error
```

Causa: el commit local `c16c241b` ("config(WP-TDM-07): state the load_settings contract instead of letting a
shim break it") elimina el shim de `src/trading_bot/config/settings.py` **sin actualizar**
`tests/unit/config/test_failfast.py`. Verificado en vivo: `main`/`origin/main`/`admission/integration-002`
sí conservan el símbolo (5 coincidencias); `5b63f265` no (0).

→ **`sync/uncommitted-main-20261025` queda `BLOCKED`: publicado, preservado, NO integrable** hasta
restaurar la implementación real de `load_settings` o completar el shim y actualizar el test.
Esto **no** afecta a `main` ni al PR #18: la colección en `e67194e7` es correcta (3401 tests, 0 errores).

### 7.3 `FALSE_SUCCESS`

`FALSE_SUCCESS = 0`. Ningún PASS declarado sin ejecución: los gates anteriores se ejecutaron y sus logs
completos están en `/tmp/g_main_*.log` y `/tmp/pytest_baseline.log`. Los PR en draft NO se marcan como
verificados: sus gates no se ejecutaron sobre esas ramas.

---

## 8. Runtime Trading Agentic — estado por capacidad

| Capacidad | Estado | Evidencia / límite |
|---|---|---|
| Market Data e adquisición incremental | `IMPLEMENTED` | `src/trading_bot/market_data`, tests unitarios; ejecución incremental `NOT_VERIFIED` en esta auditoría |
| Market / Asset Intelligence | `IMPLEMENTED` | `src/trading_bot/research`, `market_structure`, `scanner` |
| Strategy Registry y Strategy Router | `IMPLEMENTED` | `src/trading_bot/strategies`, `strategy_lifecycle` |
| Estrategias y experimentos | `TEST_ONLY` | corpus de experimentos en `research/`; ninguna estrategia admitida a dinero real |
| LLM y agentes reales | `NOT_VERIFIED` — **`REAL_MODEL_CALLED = false`** | cero imports de proveedores LLM en `src/`; solo mocks/test doubles. Documentado en roadmap v1.6 |
| AI-BOTS y AI Vision | `EXPERIMENTAL` | RFC-AI-BOTS-002/003 con registries en `wt-sup001/` (rama `codepaper/supervisor-001`, PR #23); sin módulo `vision` en `src/` |
| Multi-Agent Communication | `NOT_VERIFIED` | sin módulo de bus/mensajería en `src/`; evidencia solo en docs/agentic y en worktrees |
| Decision Engine y Critic | `IMPLEMENTED` | `src/trading_bot/autonomous/decision.py`, `supervisor.py`, `observability.py` |
| RiskManager | `IMPLEMENTED` | `src/trading_bot/risk/`; límites y leverage **no modificados** por la auditoría |
| PaperBroker | `RUNTIME_REACHABLE` | `src/trading_bot/paper/{broker,paper_orchestrator,kill_switch*}.py`; campaña real en `paper/reald-data-001` (PR #33) |
| Portfolio Accounting y PnL | `IMPLEMENTED` | `src/trading_bot/portfolio/`, `paper/portfolio_manager.py` |
| Reconciliation | `IMPLEMENTED` | `paper/reconciliation.py`, `reconciliation_v4.py` |
| DecisionTrace y evidencias | `IMPLEMENTED` | `src/trading_bot/autonomous/trace.py`; corpora `.tdm09`, `.tdm10`, `.ci` publicados |
| Dashboard | `IMPLEMENTED` | `scripts/{cap004d_daily_dashboard,paper_lab_dashboard,strategy_ecosystem_dashboard}.py`, `docs/PAPER_DASHBOARD.md` |
| Scripts y herramientas de arranque | `IMPLEMENTED` | `scripts/` (600+ ficheros) |
| Tests y certificaciones | `TEST_ONLY` (suite en rojo) | ver §7: 79F/3274P/14E en `main`, gates ruff/mypy/format en rojo |
| Roadmap y RFCs | `IMPLEMENTED` | `docs/` 145 ficheros, RFC-046..049, `docs/roadmap/` (xlsx+json+csv) |

Ningún componente depende hoy de un fichero que solo exista en un worktree local: los 246 ficheros sin
commit se publicaron en ramas `sync/uncommitted-*` y sus SHA constan en el manifiesto de exclusiones.

---

## 9. Roadmap

`docs/roadmap/` proyecta el estado en **xlsx + json + csv** (76 tareas, IDs estables `TAP-001..076`).
Actualización de corte: **v1.6 → v1.7** en la rama `project/roadmap-trading-agentic` (PR #15):

- `TAP-072` (auditoría de sincronización): 35/35 ramas publicadas, 0 commits sin publicar, 31 PR draft.
- `TAP-073` (gates): re-medición 2026-10-26 — ruff 130 / format 444 / mypy 297 (idénticos a v1.6),
  pytest `79 failed / 3274 passed / 34 skipped / 14 errors`; 19/20 ficheros coinciden con la baseline.
- `TAP-075` (PRs de trazabilidad): de 17 PR (#19-#35) a **31 PR draft (#19-#35 y #36-#49)**.
- `TAP-076` (preservación del checkout principal): sigue `BLOQUEADO` por el error de colección (§7.2).

Se conservan los estados `VERIFICADO_FOCAL`; **nada se convierte en `CERTIFIED`** por el hecho de publicar.

---

## 10. Estado declarado

```
PARTIAL_SYNC
```

`SYNC_COMPLETE` en cuanto a **publicación**: 0 commits locales sin publicar, 35/35 ramas verificadas en
remoto, 0 datos perdidos, 0 secretos publicados, worktrees intactos.

`MAIN_INTEGRATED = false`, `RUNTIME_CERTIFIED = false`, `PROFITABLE = false`:

1. `origin/main` sigue 263 commits por detrás; la integración depende del PR #18.
2. Gates de `main` en rojo (ruff/format/mypy/pytest) — baseline preexistente (§7.1).
3. PR #19 `BLOCKED` por error de colección (§7.2).
4. Los 31 PR restantes están en draft: `NOT_VERIFIED`, gates no ejecutados sobre esas ramas.
5. `REAL_MODEL_CALLED = false`: ningún modelo LLM real invocado por el runtime.
