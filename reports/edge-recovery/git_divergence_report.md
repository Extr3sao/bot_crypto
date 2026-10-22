# GIT DIVERGENCE REPORT — WP-EDGE-00

> Generado: 2026-10-12T09:0x UTC · Lectura no destructiva: `fetch`, `status`, `log`,
> `worktree list`, `ls-remote`. **No** se hizo `reset`, `clean`, `checkout` destructivo,
> `stash` ni `push --force`. Ningún trabajo preexistente se ha borrado ni mezclado.

## 1. Estado local vs remoto

| | |
|---|---|
| Repositorio raíz | `C:/Users/GVLLFR0035/Downloads/bot freebuff` |
| Remoto `origin` | `https://github.com/Extr3sao/bot_crypto.git` (fetch y push) |
| Rama local | `main` (única rama local) |
| `LOCAL_HEAD` | `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` — *"Name the commit that carries the lane in the record that verifies it."* |
| `origin/main` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` — 2026-09-22 *"chore(quality): zero-out ruff/mypy/format gates on main (PC2 clean-clone baseline)"* |
| `merge-base` | `5e6f963…` (== tip remoto) |
| Divergencia | **259 commits locales por delante, 0 detrás** (no divergente: fast-forward posible) |
| Rango de fechas local | 2026-09-25 → 2026-10-12 |
| Ramas remotas | 62 (`origin/HEAD → origin/main`); **ninguna contiene HEAD** (`git branch -r --contains HEAD` vacío) |
| PR refs públicos | 7 (ninguno apunta a HEAD) |
| Stashes | ninguno |
| Worktrees | 7: el principal + 6 *detached* (`wp9-clean`, `wp8-base`, `wp8-diff2`, `wp8-head`, `rfc035s3-lab`, `verify-lab`) |

**Conclusión:** todo el trabajo posterior al 2026-09-22 existe **solo** en este checkout.
No hay push que haya publicado HEAD; el remoto `main` está 259 commits por detrás.

## 2. Árbol de trabajo (sin commit)

`git status --porcelain=v1`: **123 entradas** = 29 modificadas (rastreadas) + 94 sin rastrear.
Nada estaba *staged*.

### 2.1 Modificadas (rastreadas) — 29

| Grupo | Ficheros | Origen aparente |
|---|---|---|
| `data/st6/*` (18) | ledger, ventanas, reportes del scheduler ST-6 | Scheduler ST-6 ejecutándose (2026-10-09 → 12) |
| `data/recovery/*` (3) | WP-8 rehearsal report, WP-9/independiente | Lané recovery previa |
| `evidence/real_decisions/*` (2) | `evaluations.jsonl`, `outcomes.jsonl` | Runtime real de decisiones |
| `scripts/` (2) | `cap004c_verify.py`, `st6_scheduler_witness.py` | Lanes CAP-004C / ST-6 |
| `docs/source_registry.md` | registro de fuentes | Gov/observabilidad |
| Raíz (3) | `RUN_REPORT.md`, `RUN_REPORT.json`, `FINAL_REPORT.md` | Campaña PAPER-DATA-ACCUMULATION-V1 |

### 2.2 Sin rastrear — 94 (agrupadas)

| Grupo | Contenido | Lane aparente |
|---|---|---|
| `data/st6/*` (33) | `raw/*.json.gz`, `snapshots/…`, `ST6_HEALTH*`, `ST6_RUNS.jsonl` | Scheduler ST-6 |
| `docs/research/*` (13) | work packages (WP-CAND-*, WP-IMP-*, WP-RISK-*, WP-HTF-PIT-*), experiment specs, runtime reconciliation | Research |
| `tests/unit/*` (8) | tests RFC-035e/s2, experimental, **4 tests SWING** | Research / SWING |
| `src/trading_bot/*` (2) | `research/experimental/`, `research/swing/` | Research / SWING |
| `scripts/` (8) | `rfc035*`, `source_candidate_experiment.py`, `swing_preregister.py`, `swing_run.py`, `swing_verify.py` | Research / SWING |
| `.ci/*` (≈28) | certificaciones cost-barrier, adversarial, stdout JSON/MD | Certificación CI local |
| `data/swing/` (4.3 MB) | 11 artefactos de la lane SWING + verificación | SWING (sin commit) |
| `data/rfc035e/`, `data/rfc035s3/` | artefactos de research | RFC-035 |

### 2.3 Trabajo del propio WP-EDGE-00 (nuevo, de este WP)

`reports/edge-recovery/**` y `scripts/wp_edge_00_verify.py` — los únicos paths que este WP
prepara para commit (scope acotado). No se mezcla con las lanes anteriores.

## 3. Política aplicada (y no aplicada)

Aplicada:

- `git fetch origin` (no destructivo) — OK, sin cambios de refs locales.
- Inventario completo sin descartar ni reescribir nada.
- Commit **solo** de los paths del WP-00 sobre una rama de trabajo
  `agent/edge-recovery/WP-EDGE-00-baseline` (nunca `main`).
- Intento de push **fast-forward** de esa rama al remoto autorizado, sin `--force`.
- Registro del resultado en `git_sync_status.json`.

No aplicada (prohibida o innecesaria):

- `push` a `main`, `push --force`, `reset --hard`, `clean -fd`, `rebase` destructivo,
  borrado de ramas o worktrees, `stash` de trabajo ajeno.

## 4. Riesgos y observaciones

1. **Concentración de trabajo local no publicado**: 259 commits (5 lanes y media) dependen de
   este checkout. Cualquier pérdida de disco implicaría pérdida de trabajo no reconstruible.
   Mitigación: publicar por ramas (como hace este WP) sin tocar `main`.
2. **`.ci/*` sin rastrear**: las certificaciones cost-barrier no están versionadas; si se quieren
   conservar como evidencia, deben commitearse por su lane (no por este WP).
3. **`data/st6/raw/*.json.gz`** crecen de forma continua (18 MB hoy): si se decide publicarlos,
   revisar tamaño/licencia antes (el RFC pide no subir datasets pesados sin revisión).
4. **Los informes raíz** (`RUN_REPORT.md`/`FINAL_REPORT.md`) pertenecen a otra campaña y están
   modificados en el árbol; este WP **no** los toca.
5. **Verificar destino antes de push**: `origin` es el único remoto y coincide con el repositorio
   autorizado del RFC (`Extr3sao/bot_crypto`). El push de este WP va **solo** a
   `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline`.
