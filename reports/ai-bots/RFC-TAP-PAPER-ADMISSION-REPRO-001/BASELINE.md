# BASELINE — RFC-TAP-PAPER-ADMISSION-REPRO-001

Capturado **antes** de cualquier cambio de código, y vuelto a capturar sobre el árbol ya
integrado para separar «lo que fallaba» de «lo que rompió el merge».

## 1. Commits y árbol

| Qué | Valor | Cómo se obtuvo |
| --- | --- | --- |
| `main` (base del RFC) | `0e13160a8d5522961978fe3bd6b904b3a14be1c3` | `git rev-parse main` |
| `codepaper/supervisor-001` (lane auditada) | `3b758e22f0c9835646c9eba9db6634757970b126` | `git rev-parse codepaper/supervisor-001` |
| merge-base de ambas | `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` | `git merge-base main codepaper/supervisor-001` |
| divergencia | lane **301** commits delante, **1** detrás de `main` | `git rev-list --count` |
| worktree `wt-sup001` | `HEAD = 3b758e22`, árbol **limpio** (0 entradas en `git status`) | `git -C wt-sup001 status --porcelain` |
| rama del RFC | `repro/paper-admission-001`, creada desde `3b758e22` | `git worktree add -b ...` |
| integración de `main` | merge `b4c8e3e2`, **sin conflictos**, sin ficheros en conflicto | `git merge --no-edit main` |

La trazabilidad es completa: el worktree que auditó el diagnóstico está en el mismo commit que
la rama, sin cambios sin registrar, y esa rama se integra sobre `main` sin sobrescribir nada
(el merge solo añade el commit `0e13160a` y lo que trae).

El checkout compartido **no se modificó**: los cambios del RFC viven en un worktree aparte.
Los ficheros modificados sin commitear que hay en `main` pertenecen a otras lanes y no se
tocaron.

## 2. Entorno

| Componente | Versión |
| --- | --- |
| SO | Windows 10.0.26200 |
| Python | 3.11.15 (`uv` managed, `cpython-3.11-windows-x86_64-none`) |
| `uv` | 0.11.26 |
| `pytest` | 9.1.1 |
| `git` | 2.51.1.windows.1 |

`.venv` se creó con `uv sync` **desde cero** en el worktree del RFC: los resultados de este
documento no dependen de un entorno preexistente.

## 3. Los seis documentos preservados

Copiados byte a byte desde el checkout compartido a este worktree, y versionados en su ruta
original. Estos son los hashes de referencia; `verify_repro.py` los lleva congelados y falla si
un solo byte cambia.

| Documento | SHA-256 |
| --- | --- |
| `FINAL_REPORT.md` | `e30fa25fe329a26bcd57783659dfb880abba7ed66888ba94890f37925e21bb59` |
| `NEXT_EXPERIMENT.md` | `6759808f41571bed4b418d70b836fade46fbc497f5e3354b081841e924896997` |
| `OPERATIONAL_BLOCKERS.md` | `94a9c64ef526deb730ae2a61606094312ebbc5fd7bb3777346aaf9480f7e2e97` |
| `PAPER_ADMISSION_DIAGNOSIS.md` | `36255748b45d1085588e8f7de79b7f038f12c21ffa2181e41e549a4fb46a9f03` |
| `RUNTIME_AUTHORITY_MAP.md` | `4540e3c75bffb1011a07c6d265849439b42ee5f235b3e29a47153d0241f80b84` |
| `STRATEGY_ECONOMIC_STATUS.md` | `d8e9e015587af9755da637c97f304a70dacba4b5e346929b967343e9138379f3` |
| `verify_claims.py` (verificador de la lane) | `e423ef3fcd5990db83e8897bd702f76fda204646b35f56b20b64b77ed3d9c2b1` |

## 4. Estado medido antes de tocar código

Capturado dos veces: en `3b758e22` (lo que auditó el diagnóstico) y en `b4c8e3e2` (el árbol ya
integrado). Las tres comprobaciones dan **el mismo resultado en ambos**, así que el merge no
introdujo ninguno de los defectos.

| # | Comprobación | Comando | Resultado | Log |
| --- | --- | --- | --- | --- |
| B-1 | contrato sin ventana | `pytest tests/unit/ops/test_windowless.py -q` | **1 failed, 12 passed**, exit 1 | `evidence/BASELINE_MERGED_pytest_windowless.log` |
| B-2 | auditoría de lanzadores | `python scripts/ops_background_audit.py --json ...` | **HIGH 3**, exit 1 | `evidence/BASELINE_MERGED_audit.json` |
| B-3 | lock del entorno | `uv lock --check` | **exit 1** («the lockfile needs to be updated») | `evidence/BASELINE_MERGED_uv_lock_check.log` |
| B-4 | verificación de lock | `paper_lock_campaign_verify.py --campaign <supervisor>` | **FAIL 28/32**, `false_success 2`, exit 1 | `evidence/BASELINE_MERGED_lock_verifier.log` |
| B-5 | verificación del supervisor | `paper_supervisor_verify.py --campaign <supervisor>` | **PASS 33/33**, `false_success 0`, exit 0 | `evidence/BASELINE_MERGED_SUPERVISOR_VERIFY.json` |
| B-6 | claims del diagnóstico | `python .../CODEX-PAPER-ADMISSION-DIAG-001/verify_claims.py` | **28/28 PASS**, exit 0 | `evidence/BASELINE_verify_claims.log` |
| B-7 | suite de ops | `pytest tests/unit/ops -q` | **1 failed, 82 passed** (solo B-1) | `evidence/BASELINE_pytest_ops.log` |

### Los 3 offenders de B-2

| Fichero | Línea | Origen |
| --- | --- | --- |
| `scripts/exp004a_verify.py` | 1216 | preexistente en `main` |
| `tests/unit/ops/test_paper_lock_campaign.py` | 44 | añadido por la lane (`ce02a810`) |
| `tests/unit/ops/test_session_status.py` | 65 | añadido por la lane (`ce02a810`) |

### B-4, en detalle

`paper_lock_campaign_verify.py` puntuó la campaña del **supervisor** (`CAMPAIGN.json` declara
`TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`) como si fuera una campaña de lock: 32 checks, 4 en falso
(`at_least_five_recoveries`, `both_crash_sites_covered`, `concurrent_reclaim_has_one_winner`,
`stale_owner_was_refused`), 10 mutaciones `invalid` y **2 `false_success`**
(`reclaim_row_removed`, `resume_start_removed`). El verificador correcto para esos artefactos
(B-5) da `PASS 33/33`.

### B-3, en detalle

`pyproject.toml` declara `matplotlib>=3.8,<4.0` desde la lane de visión; `uv.lock` resuelve
**118** paquetes y no contiene `matplotlib`, porque el lock no se regeneró al añadir la
dependencia. El daño no es solo el `--check`: `uv sync --frozen` **sale 0** y deja el entorno
sin `matplotlib`, con lo que el runtime ni siquiera importa
(`evidence/ENV_DEFECT_after_frozen_sync_lock_verifier.log`).

## 5. Lo que este baseline no captura

- **No hay campaña de lock real.** La lane solo conserva la campaña del supervisor; la campaña
  honesta de `paper_lock_campaign.py` se reconstruye en el test como fixture sintético con la
  misma forma que la del productor. Se declara: el `PASS` de WP-02 es sobre fixture, no sobre
  una ejecución de 6 crashes en este RFC.
- **B-6 se ejecutó sobre el árbol congelado de `3b758e22`** (`git archive` en `wt-sup001/`,
  retirado después). `verify_claims.py` resuelve `ROOT/"wt-sup001"`, así que en un checkout
  normal no encuentra su sujeto; es un verificador de *snapshot*, no portable. No se modificó:
  cambiarlo habría invalidado los hashes que el RFC debe preservar.
