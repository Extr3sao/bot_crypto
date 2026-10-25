# MT-0004-R1 — RUN_REPORT

| Campo | Valor |
|---|---|
| **TASK** | `MT-0004-R1` (`REISSUED`). El `MT-0004` original queda `SPEC_REISSUE_REQUIRED`: su contrato no existe en ningún objeto git. |
| **RUN_ID** | `run-20261023T190725Z-MT0004-R1` |
| **BUILD_COMMIT** | `ef7955dc5973ab863f010e02a1297a455ef276da` |
| **BASELINE** | Rama `audit/mt0004-negative-controls` cortada de `codepaper/supervisor-001@0e2ba09d`. `main` = `1d2192b0` (299 commits por detrás y sin el control de MT-0003). Working tree limpio en el commit. |
| **SCOPE** | [MT-0004-R1.md](../../MT-0004-R1.md) §4: `docs/audit/**`, dos ficheros de test nuevos, `scripts/audit/negative_controls.py`. `src/**` y los tests de MT-0002/MT-0003 declarados protegidos. |
| **IMPLEMENTED** | 6 ficheros nuevos, +1326 líneas, 0 cambios en producción. |
| **TESTS** | 58 passed en el export del commit · 350 passed en la regresión · matriz 6/6 mutantes muertos · `ruff` + `mypy` limpios. |
| **RUNTIME_VALIDATION** | `AC-3`: con el switch engaged el `AutonomousPaperRuntime` real crea 0 órdenes, el broker recibe **0** llamadas y el motor de riesgo devuelve `PASS`. |
| **PAPER_VALIDATION** | `NOT_PERFORMED` contra feed real. Se ejercita el runtime PAPER con fixtures deterministas, no una sesión de mercado. |
| **LIVE_VALIDATION** | `NOT_PERFORMED` por diseño. |
| **VERIFIER** | `VERIFIED_SCOPED` — **13/13** checks, exit 0, 344 s. Limitación: `BUILDER == VERIFIER` en autoría (independencia procedural). |
| **FALSE_SUCCESS** | 0 observado. Dos falsos verdes propios fueron detectados y corregidos antes de declarar (D-1, D-2). |
| **DEFECTS** | 5 defectos propios corregidos (D-1…D-5) + 1 defecto heredado de MT-0003 documentado y no tocado (D-6). |
| **BLOCKERS** | Contrato original perdido (`SPEC_REISSUE_REQUIRED`); G-1…G-4 abiertos; sin tarea siguiente respaldada por evidencia. |
| **EVIDENCE** | [`evidence/`](evidence) — 7 ficheros, hashes en [`evidence/06_hashes.txt`](evidence/06_hashes.txt). |
| **NEXT_READY** | `null`. Ver §10. |

---

## 1. Qué pedía MT-0004 (y qué se puede afirmar)

El encargo de la tarea MT-0004 se perdió con el corpus de auditoría. Lo único
que sobrevive, en git:

```text
src/trading_bot/app.py:61-66
  #: ... hasta que MT-0003 (kill switch en el path de decision) y
  #: MT-0004 (tests negativos) existan.

tests/unit/test_app_cli_contract.py:42-44
  #: The two commands MT-0002 was opened for. ``MT-0003``/``MT-0004`` will give
  #: them real behaviour; until then the contract is "refuse loudly".
```

Búsqueda ejecutada y agotada:

| Comprobación | Resultado |
|---|---|
| `git log --all --oneline -- reports/multiagent-audit` | 0 commits |
| `git log --all -S'MT-0004' --oneline` | 1 commit: `9c83e62a` (MT-0002) |
| `git grep -l MT-0004` en todas las refs locales | 2 ficheros, ambos comentarios |
| Búsqueda en disco fuera de git | solo los informes del run bloqueado |

Por tanto: **`SPEC_REISSUE_REQUIRED`**. Se emite [`MT-0004-R1.md`](../../MT-0004-R1.md)
con procedencia marcada `REISSUED` y una lista explícita de lo que falta
(objetivo, evidencia justificativa, dependencias, `allowed_paths`,
`protected_paths`, ACs y tests obligatorios originales). **No se presenta como
recuperado.** El criterio C-1 (tests negativos) y C-2 (superficie del kill
switch) sí están respaldados por texto commiteado.

## 2. Autoridad del repositorio

[`runtime_authority_map.md`](../../runtime_authority_map.md) registra el análisis. En
resumen: `codepaper/supervisor-001` es la línea con el control de MT-0003
(`60455b46` es ancestro); `main` no lo contiene y no lo contendrá por tener más
commits. La comprobación decisiva no es el conteo sino la alcanzabilidad del
gate:

- `kill_switch_v2` → único importador de producción: `autonomous/decision.py:36`.
- `autonomous/runtime.py:341` construye `DecisionEngine()` sin switch inyectado → lee la autoridad de proceso.
- `paper/kill_switch.py` (V0.3) → **ORPHAN**, 0 importadores.
- `paper/paper_cycle.py` → alcanzable desde `scripts/start_paper_trading.py`, **sin** importar `autonomous.decision`: no pasa por rule 0 (G-4, abierto).

Durante el run, otras lanes movieron `main` y `codepaper/supervisor-001`. Se
re-midió a las 19:10Z: `main = 47ca8dac`, sigue **sin** `60455b46` y sin el test
de MT-0003. La decisión de autoridad no cambió; el árbol de trabajo queda
anclado por SHA, no por nombre de rama.

## 3. Qué se ha implementado

| Fichero | Qué aporta |
|---|---|
| `docs/audit/runtime_authority_map.md` | mapa de autoridad, alcanzabilidad del gate, gaps, límites. |
| `docs/audit/MT-0004-R1.md` | contrato reemitido con procedencia y AC-1…AC-6. |
| `docs/audit/AUDIT_BACKLOG.yaml` | backlog versionado, solo con tareas evidenciadas. |
| `scripts/audit/negative_controls.py` | matriz de 6 mutantes, reproducible desde una revisión, fail-closed ante deriva del anclaje. |
| `tests/unit/autonomous/test_kill_switch_negative.py` | 15 casos negativos nuevos. |
| `tests/unit/test_audit_contracts_tracked.py` | guardia: ningún contrato obligatorio puede quedar ausente, ignorado o sin seguimiento. |

`src/**` **no** se ha tocado (`git diff HEAD^ HEAD -- src` vacío, V-03).

## 4. Tests ejecutados

| Conjunto | Comando | Resultado |
|---|---|---|
| Export del commit (3 suites) | `pytest tests/unit/autonomous/test_decision_kill_switch.py tests/unit/autonomous/test_kill_switch_negative.py tests/unit/test_app_cli_contract.py` | **58 passed** en 37,2 s |
| Regresión | `pytest tests/unit/autonomous tests/unit/test_app_cli_contract.py tests/unit/test_audit_contracts_tracked.py` | **350 passed** en 61,8 s, exit 0 |
| Guardia en worktree real | `pytest tests/unit/test_audit_contracts_tracked.py` | **8 passed** |
| Guardia en export sin git | idem sobre `git archive` | **falla** con "needs a git work tree" (fail-closed, no skip) |
| Guardia adversarial | contrato apuntando a `reports/lost-contract.md` | falla en `test_contracts_do_not_live_in_the_ignored_report_directory` |
| Estático | `ruff check`, `ruff format --check`, `mypy` | 0 hallazgos |
| MT-0003 recuperado | `pytest test_decision_kill_switch.py test_app_cli_contract.py` | **43 passed** en el baseline |

Suite completa del repositorio: **no ejecutada** (decenas de minutos y otras
lanes escribiendo en el mismo checkout). Cobertura alternativa: `tests/unit/autonomous`
completo, el contrato CLI completo y el fichero nuevo, más la matriz de mutantes.
El riesgo residual es una regresión fuera de esos módulos, y se declara.

## 5. Comportamiento del runtime demostrado

`AC-3`, sobre el `AutonomousPaperRuntime` real compuesto por
`tests/unit/autonomous/helpers.make_runtime` (sin mocks del camino de decisión):

- switch engaged, estrategia admitida, edge neto positivo, verifier PASS;
- el motor de riesgo determinista **sí** corre y devuelve `PASS` (advisory):
  `row.risk_evaluated is True`, `row.risk_verdict == "PASS"`;
- aun así: `orders_created == 0`, `paper_trades == 0`, `broker.calls == 0`,
  `broker.positions == {}`.

Es decir: el bloqueo no proviene de admisión, ni de coste, ni de riesgo. Proviene
de rule 0. `AC-4` añade que un paquete malformado no puede adelantarse al stop
levantando una excepción, y `AC-5` que solo un token explícito de apagado
arranca el proceso operando.

No se ha demostrado nada sobre una sesión real de PAPER ni sobre live.

## 6. Verificación independiente

[`verification.json`](verification.json) — **`VERIFIED_SCOPED`, 13/13**, exit 0.
El verificador (`reports/multiagent-audit/tools/verify_mt0004_r1.py`, fuera del árbol versionado)
exporta el commit con `git archive` y re-deriva:

| Check | Qué prueba |
|---|---|
| V-01…V-04 | commit, conjunto exacto de 6 ficheros, cero cambios protegidos, blobs y sha256 del árbol. |
| V-05, V-05c | las 3 suites de código y la guardia pasan sobre el commit exportado. |
| V-05b | la guardia **se niega a saltarse** fuera de un work tree. |
| V-06, V-07 | el primitivo discrimina (la ruta perdida sigue ignorada; el contrato no) y la guardia **falla** ante un contrato ignorado. |
| V-08 | M1 y M6 reaplicados con literales propios del verificador, sin usar el arnés del builder. |
| V-09 | el arnés entregado reproduce desde la revisión: 6/6 muertos. |
| V-10 | el arnés falla cerrado si el anclaje deriva (`ANCHOR ERROR`). |
| V-11 | el backlog registra `MT-0004` como perdido y `MT-0004-R1` como reemitido. |

**Limitación que condiciona el veredicto:** `BUILDER == VERIFIER` en autoría. La
independencia es procedural (script separado, literales propios, export por
commit), no una segunda persona. V-08 cubre 2 de 6 mutantes de forma
independiente; M2–M5 los cubre V-09 ejecutando el arnés entregado. Ambas cosas
están escritas en el JSON, no ocultas.

## 7. Defectos encontrados y resueltos

| ID | Defecto | Cómo apareció | Estado |
|---|---|---|---|
| D-1 | El test de entorno fijaba `REPO_ROOT/src` y lanzaba el subproceso contra el checkout limpio. | **M6 sobrevivió** en la primera matriz. | Corregido: `SRC_DIR` se deriva del módulo importado y el hijo verifica que importó el árbol bajo test. |
| D-2 | El snippet `-c` usaba `trading_bot.__file__` sin importar el nombre. | El baseline falló con `NameError`. | Corregido. |
| D-3 | El verificador no creaba el directorio de export antes de `git archive -o`. | Crash en V-04. | Corregido + `except` que convierte un crash en `V-00` fallido y JSON escrito. |
| D-4 | El verificador esperaba que la guardia pasara dentro de un export sin git. | V-05 falló. | Expectativa errónea: separado en V-05 (código), V-05b (fail-closed) y V-05c (worktree). |
| D-5 | V-07 buscaba el mensaje de assert en la salida, que `--tb=no` oculta. | V-07 falló con el comportamiento correcto. | Corregido: se afirma sobre el test concreto que debe fallar. |
| D-6 | **Heredado, no tocado:** el test de entorno de MT-0003 también fija `REPO_ROOT/src`, así que no detectaría un mutante de la política de arranque. | Lo reveló la matriz (M6). | Documentado. `test_decision_kill_switch.py` es protegido; la sensibilidad la aporta ahora el fichero nuevo. |

D-1 y D-6 son el mismo patrón en dos sitios: un test que lanza un subproceso
contra una ruta fija mide otro árbol. El arnés de mutantes es lo que lo expuso.

## 8. Qué no se ha verificado

- **La suite completa.** Ver §4.
- **PAPER contra feed real** y cualquier forma de LIVE.
- **G-1…G-4.** Siguen abiertos: sin persistencia, sin activación en caliente
  desde CLI, sin medición del path live, y `paper_cycle.py` sin rule 0.
- **La autoría del contrato original.** No existe; `MT-0004-R1` es una reemisión.
- **La papelera de Windows.** No fue legible en el run anterior; no se usa como
  prueba de nada.

## 9. Evidencia

| Fichero | Contenido |
|---|---|
| [`evidence/00_scope.txt`](evidence/00_scope.txt) | rama, HEAD, padre, ancestría de MT-0003, `git show --name-status`, diff protegido vacío |
| [`evidence/01_tests_regression.txt`](evidence/01_tests_regression.txt) | 350 passed, exit 0 |
| [`evidence/02_static.txt`](evidence/02_static.txt) | ruff check/format + mypy, exit 0 cada uno |
| [`evidence/03_mutants.{txt,json}`](evidence/03_mutants.txt) | matriz completa con tiempos y test que mata cada mutante |
| [`evidence/04_guard_negative_control.txt`](evidence/04_guard_negative_control.txt) | la guardia rechaza un contrato ignorado |
| [`evidence/05_guard_fail_closed.txt`](evidence/05_guard_fail_closed.txt) | la guardia no se salta la comprobación sin git |
| [`evidence/06_hashes.txt`](evidence/06_hashes.txt) | blob git + sha256 de los 6 entregables |

## 10. Siguiente tarea

`NEXT_READY = null`. Tras MT-0004-R1 solo queda la lista de gaps, y ninguno
tiene contrato. Nombrar uno sería inventar una especificación, que es
exactamente lo que este run se niega a hacer. La recomendación registrada en el
backlog es abrir ticket para **G-2** (no hay superficie de activación en
caliente): es el único gap cuya corrección está enteramente en el árbol y no
depende de un exchange ni de una sesión de mercado.
