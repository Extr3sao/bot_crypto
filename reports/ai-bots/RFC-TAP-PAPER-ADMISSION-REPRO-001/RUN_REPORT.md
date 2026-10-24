# RUN REPORT — RFC-TAP-PAPER-ADMISSION-REPRO-001

Todo lo de esta tabla se ejecutó. Donde algo no se pudo ejecutar se dice `BLOCKED`, no `PASS`.

- **Artefacto verificado:** `c44f912c2fa7e25a9765323aa0032a23425446ab`
- **Commit base (antes de cualquier cambio):** `b4c8e3e2` (merge de `main` en la lane)
- **Rama:** `repro/paper-admission-001`, worktree aislado; el checkout compartido no se tocó.

## 1. Ejecución, en orden

### 1.1 Baseline (antes de tocar código)

| # | Comando | Directorio | Exit | Resultado |
| --- | --- | --- | ---: | --- |
| R-01 | `git merge-base main codepaper/supervisor-001` | compartido | 0 | `1d2192b0`; lane 301 delante, 1 detrás |
| R-02 | `git -C wt-sup001 status --porcelain` | compartido | 0 | vacío: el worktree auditado está limpio |
| R-03 | `git merge --no-edit main` | worktree RFC | 0 | merge `b4c8e3e2`, **sin conflictos** |
| R-04 | `uv sync` (venv desde cero) | worktree RFC | 0 | 118 resueltos |
| R-05 | `pytest tests/unit/ops/test_windowless.py -q` | pre-fix | 1 | **1 failed, 12 passed** |
| R-06 | `python scripts/ops_background_audit.py --json …` | pre-fix | 1 | **HIGH 3**, MEDIUM 412 |
| R-07 | `uv lock --check` | pre-fix | 1 | el lock «needs to be updated» |
| R-08 | `uv sync --frozen` (lock desalineado) | pre-fix | **0** | instaló el entorno **sin `matplotlib`** |
| R-09 | `paper_lock_campaign_verify.py --campaign <supervisor>` | pre-fix | 1 | **FAIL 28/32**, `false_success 2` |
| R-10 | `paper_supervisor_verify.py --campaign <supervisor>` | pre-fix | 0 | **PASS 33/33**, `false_success 0` |
| R-11 | `verify_claims.py` sobre `git archive 3b758e22` | pre-fix | 0 | **28/28 PASS** |

R-08 es el defecto en su forma más cruda: el comando que debía *fallar* si el lock no
corresponde salió 0 y dejó un entorno que no puede importar el runtime. Los dos verificadores
de la lane murieron con `ModuleNotFoundError: No module named 'matplotlib'` antes de juzgar nada
(`evidence/ENV_DEFECT_after_frozen_sync_*.log`).

### 1.2 Correcciones

| WP | Cambio | Ficheros |
| --- | --- | --- |
| WP-01 | `_dead_pid()` arranca el hijo por `windowless.spawn` en los dos tests que usaban `subprocess.Popen`; `exp004a_verify.py` esconde su propio hijo con `CREATE_NO_WINDOW` + `STARTUPINFO/SW_HIDE` y la auditoría exige ese mecanismo mientras dure la excepción | `tests/unit/ops/test_paper_lock_campaign.py`, `tests/unit/ops/test_session_status.py`, `scripts/exp004a_verify.py`, `scripts/ops_background_audit.py` |
| WP-02 | `judge()` lee **solo** `CAMPAIGN.json.schema_version`; si no es `TAP_PAPER_LOCK_CAMPAIGN_V1` devuelve `UNSUPPORTED_CAMPAIGN_SCHEMA` con 0 checks puntuados y 0 mutaciones | `scripts/paper_lock_campaign_verify.py` |
| WP-03 | `uv.lock` regenerado con la dependencia que `pyproject.toml` ya declaraba | `uv.lock` |
| WP-04 | Excepciones de `.gitignore` para los tres directorios de evidencia; manifiesto, verificador e informes | `.gitignore`, `reports/ai-bots/**` |

### 1.3 Verificación (después de las correcciones, mismo árbol)

| # | Comando | Exit | Resultado |
| --- | --- | ---: | --- |
| R-12 | `pytest tests/unit/ops -q` | 1 → 0 | 1 fallo intermitente ajeno (ver §3), luego **86 passed** |
| R-13 | `python scripts/ops_background_audit.py --json …` | 0 | **HIGH 0**, CLEAN, MEDIUM 406 |
| R-14 | `pytest tests/unit/ops/test_windowless.py -q` | 0 | **14 passed** (13 + el control negativo nuevo) |
| R-15 | `paper_lock_campaign_verify.py --campaign <supervisor>` | 1 | **refusal** `UNSUPPORTED_CAMPAIGN_SCHEMA`, 0 checks puntuados, 0 mutaciones, `false_success 0` |
| R-16 | campaña honesta (fixture del productor) | 0 | **PASS 33/33**, 10 mutaciones, 0 `invalid`, 0 `undetected` |
| R-17 | `paper_supervisor_verify.py --campaign <supervisor>` | 0 | **PASS 33/33**, `false_success 0` |
| R-18 | `uv lock --check` | 0 | 118 resueltos |
| R-19 | `pytest tests/unit/research/test_exp004a_verify_adversarial.py -q` | 0 | 20 passed (el verificador tocado sigue pasando su propia suite) |
| R-20 | `python .../verify_repro.py` | 0 | **12/12 gates, 4/4 controles, `false_success 0`** |

R-15 sale 1 a propósito: un rechazo no es un `PASS`. El payload lo distingue con
`refusal.code`; el código de salida no, y eso queda anotado como defecto abierto (§4).

### 1.4 Checkout limpio (rehearsal)

Worktree nuevo en `ff-wt-clean001`, `--detach` en `c44f912c`, sin `.venv`:

| # | Comando | Exit | Resultado |
| --- | --- | ---: | --- |
| R-21 | `git status --porcelain` | 0 | vacío: checkout prístino |
| R-22 | `uv sync --frozen` | 0 | **111 paquetes instalados**, lock intacto tras el sync |
| R-23 | `python -c "import matplotlib"` | 0 | `matplotlib 3.11.2 on 3.11.15` |
| R-24 | `uv lock --check` | 0 | 118 resueltos |
| R-25 | `pytest tests/unit/ops -q` | 0 | **86 passed** |
| R-26 | `python .../verify_repro.py` | 0 | **12/12 gates, `false_success 0`** |

Transcripción completa: `evidence/CLEAN_CHECKOUT_REHEARSAL.log`.

## 2. Verificación independiente

`verify_repro.py` no comparte aritmética con el que hizo las correcciones: recalcula hashes
desde bytes, ejecuta cada gate como subproceso y lee el *payload* que la herramienta escribió.
Los hashes de los seis documentos están **congelados en el propio verificador**, no leídos del
manifiesto que audita.

| Gate | Qué comprueba | Resultado |
| --- | --- | --- |
| V01 | los 6 documentos + `verify_claims.py` son byte a byte los del diagnóstico | PASS |
| V02 | manifiesto ↔ árbol (preservados, código, evidencia) | PASS |
| V03 | esos ficheros **no** estaban en Git en el commit base | PASS |
| V04 | auditoría de lanzadores sin `HIGH` | PASS |
| V05 | contrato `test_windowless` | PASS (14) |
| V06 | campaña de otro schema → rechazo, 0 checks puntuados | PASS |
| V07 | campaña del propio schema → PASS 33/33, 10/10 mutaciones detectadas | PASS |
| V08 | verificador del supervisor (código ajeno, sin tocar) → PASS 33/33 | PASS |
| V09 | `uv lock --check` | PASS |
| V10 | `matplotlib` declarado, en el lock e importable | PASS |
| V11 | solo se tocó lo permitido; ni ledger ni riesgo ni visión | PASS |
| V12 | ledger intacto y `admitted_for_paper == 0` | PASS (24 estrategias, 0 admitidas) |

**Controles negativos (4/4 detectados, `false_success = 0`):** flip de un byte en un documento,
campaña sin schema, excepción de ventana sin mecanismo, hash del manifiesto alterado.

Uno de ellos hizo su trabajo antes de publicarse: `declared_local_hiding_removed` salió `false`
en la primera pasada porque el control tenía un bug (módulo sin registrar en `sys.modules` antes
de ejecutar un `dataclass`). El fallo era del control, no del mecanismo, y se corrigió.

## 3. Errores y anomalías observados

1. **`test_single_writer_lock.py::test_only_one_of_many_processes_reclaims_the_same_lock`
   falló una vez** con `LOCK_UNATTRIBUTED` al correr la suite completa bajo carga; en aislamiento
   pasó 3/3 y la suite completa volvió a dar `86 passed`. El fichero no lo toca este RFC: es
   una carrera preexistente y sensible a la carga, no una regresión. Queda abierta (§4.2).
2. **El manifiesto nombraba 20 logs que Git no llevaba.** La regla global `*.log` los excluía y
   el rehearsal en checkout limpio lo detectó (V02). Se añadió la excepción y se rehizo el
   commit. Sin el rehearsal, el paquete habría viajado incompleto.
3. **El manifiesto se hasheaba a sí mismo** en `code_changes` y quedaba desactualizado al
   escribirse. Se excluyó `reports/**` de esa lista.
4. **El merge de `main` no rompió nada:** las tres comprobaciones del baseline dan el mismo
   resultado en `3b758e22` y en `b4c8e3e2`.

## 4. Defectos abiertos

| # | Defecto | Impacto | Por qué no se corrige aquí |
| --- | --- | --- | --- |
| 4.1 | `verify_claims.py` resuelve su sujeto como `ROOT/wt-sup001`, así que fuera de ese layout da `4/28` por `FileNotFoundError` | el verificador del diagnóstico no es portable | preservarlo con sus hashes era el requisito; reescribirlo invalidaba la trazabilidad |
| 4.2 | `LOCK_UNATTRIBUTED` intermitente en la carrera de 6 procesos | puede hacer fallar CI bajo carga | fuera de los tres defectos del mandato; necesita un análisis propio |
| 4.3 | `uv sync --frozen` sigue saliendo 0 ante un desajuste pyproject/lock | el lock correcto hoy no impide el mañana | el gate existe (`verify_repro.py`, V09) pero no está cableado en CI |
| 4.4 | `paper_lock_campaign_verify.py` sale 1 tanto si juzga `FAIL` como si rechaza | un consumidor que solo mire el exit code confunde un rechazo con un fallo | cambiar el código de salida rompería a los llamadores actuales; el payload ya lo distingue |
| 4.5 | `scripts/paper_lock_campaign_verify.py` tiene un `no-untyped-def` preexistente y 4 ficheros arrastran drift de `ruff format` | ruido en `mypy`/`format` | reformatear 4 ficheros habría enterrado el diff real |
| 4.6 | No hay campaña de lock real en el repo | el `PASS` de R-16 es sobre fixture | regenerarla exige lanzar 6 sesiones con crashes; fuera del alcance |

## 5. Límite de la independencia

`BUILDER != VERIFIER` se cumple **en método**, no en identidad: el verificador recalcula desde
bytes y ejecuta las herramientas, pero lo escribió el mismo agente que hizo las correcciones.
Con los agentes disponibles en esta sesión no hay forma de cerrar esa brecha. Se declara en vez
de disimularla. Lo que sí es ajeno al builder: `paper_supervisor_verify.py` (V08),
`ops_background_audit.py` (V04) y `verify_claims.py` (preservado) siguen dando el mismo veredicto
que antes de tocar nada.
