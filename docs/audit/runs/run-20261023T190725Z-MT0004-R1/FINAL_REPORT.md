# FINAL_REPORT — MT-0004-R1

**RUN_ID** `run-20261023T190725Z-MT0004-R1` · **Commit** `ef7955dc5973ab863f010e02a1297a455ef276da` ·
**Rama** `audit/mt0004-negative-controls` · **Fecha** 2026-10-23

## Estado, sin adornos

| Nivel | Estado |
|---|---|
| `RECOVERED` | Sí para **MT-0003**: su commit `60455b46` es ancestro del baseline, el control está en el árbol y sus 43 tests pasan. |
| `REISSUED` | Sí: `MT-0004-R1`. El `MT-0004` original es **irrecuperable** (`SPEC_REISSUE_REQUIRED`). |
| `IMPLEMENTED` | Sí: 6 ficheros nuevos, +1326 líneas, 0 cambios en producción. |
| `TESTED` | Sí, alcance declarado: 58 passed en el export, 350 en la regresión, 6/6 mutantes muertos. |
| `RUNTIME_VERIFIED` | Sí **en proceso**, con fixtures deterministas: el runtime PAPER real no llama al broker con el gate engaged y el riesgo devuelve PASS. No es una sesión de mercado. |
| `INDEPENDENTLY_VERIFIED` | `VERIFIED_SCOPED` 13/13, con una salvedad: `BUILDER == VERIFIER` en autoría. |
| `BLOCKED` | El contrato original de MT-0004: no está en ningún objeto git. |

**No** se declara `GLOBAL_GATE_VERIFIED`, `LIVE_READY` ni `PRODUCTION_READY`. No
está en el poder de esta tarea.

## 1. Qué pedía exactamente MT-0004

No se sabe. Solo sobreviven dos comentarios commiteados: `app.py:61-66` lo
describe como «tests negativos» junto a MT-0003, y `test_app_cli_contract.py:42-44`
dice que MT-0003/MT-0004 darán comportamiento real a `kill-switch` y `status`.
De ahí se puede sostener dos cosas —que trata de tests negativos y que pertenece
a la superficie del kill switch— y nada más: ni objetivo, ni evidencia
justificativa, ni `allowed_paths`, ni criterios de aceptación, ni tests
obligatorios.

Por eso no se «reconstruyó» el ticket: se reemitió como `MT-0004-R1`, con la
procedencia escrita, las dos únicas restricciones respaldadas y una lista
explícita de lo que falta. Un fichero reconstruido a partir de un paréntesis
sería una invención con historial git.

## 2. Qué se ha cambiado

`ef7955dc` añade seis ficheros, todos nuevos, ninguno de producción:

- **`docs/audit/runtime_authority_map.md`** — qué rama manda y por qué (no por
  número de commits, sino por alcanzabilidad del gate), clasificación de cada
  componente, estado de G-1…G-4 y lo que el mapa no puede afirmar.
- **`docs/audit/MT-0004-R1.md`** — contrato reemitido: alcance, `allowed_paths`,
  `protected_paths`, AC-1…AC-6, plan de pruebas, requisitos de verificación.
- **`docs/audit/AUDIT_BACKLOG.yaml`** — backlog versionado; solo tareas con
  evidencia (MT-0002, MT-0003, MT-0004 perdido, MT-0004-R1). Lo desconocido va a
  `unrecoverable`, no se inventa.
- **`scripts/audit/negative_controls.py`** — matriz de mutantes reproducible
  desde una revisión; falla cerrado si un anclaje deja de coincidir exactamente
  una vez.
- **`tests/unit/autonomous/test_kill_switch_negative.py`** — 15 casos negativos:
  el broker no recibe ni una llamada aunque el riesgo apruebe; un paquete
  malformado no puede adelantarse al stop; objetos de estado rotos bloquean;
  solo un token explícito de apagado arranca el proceso operando; un paquete
  bloqueado no se evalúa como shadow.
- **`tests/unit/test_audit_contracts_tracked.py`** — guardia permanente contra la
  causa raíz: falla si un contrato obligatorio está ausente, vacío, ignorado o
  sin seguimiento git, y se niega a saltarse cuando no puede probarlo.

## 3. Tests ejecutados

| Conjunto | Resultado |
|---|---|
| Suites de código sobre el commit exportado | **58 passed**, 37,2 s |
| Regresión (`tests/unit/autonomous` + contrato CLI + guardia) | **350 passed**, 61,8 s, exit 0 |
| Guardia en worktree real / en export sin git | **8 passed** / **falla cerrada** ("needs a git work tree") |
| Guardia con un contrato ignorado | **falla** en `test_contracts_do_not_live_in_the_ignored_report_directory` |
| Matriz de mutantes | **6/6 muertos**, baseline verde, 151 s |
| `ruff check` · `ruff format --check` · `mypy` | 0 hallazgos, exit 0 |
| MT-0003 recuperado | **43 passed** en el baseline |

La suite completa del repositorio **no** se ejecutó (coste alto y otras lanes
escribiendo en el mismo checkout). Se declara como límite, no como cobertura.

## 4. Comportamiento del runtime demostrado

Con el kill switch engaged y un paquete que de otro modo autorizaría —estrategia
admitida, edge neto positivo, verifier PASS— el `AutonomousPaperRuntime` real:

- crea **0** órdenes y **0** paper trades;
- deja `broker.calls == 0` y `broker.positions == {}`;
- **sí** ejecuta el motor de riesgo, que devuelve `PASS` (advisory).

El bloqueo no viene de admisión, ni de coste, ni de riesgo: viene de rule 0. Eso
es lo que distingue este test de uno que solo cuenta órdenes.

## 5. Qué falló y cómo se resolvió

Cinco defectos propios, todos encontrados por los propios controles:

1. **El test de entorno medía otro árbol.** Fijaba `REPO_ROOT/src`, así que el
   subproceso importaba el checkout limpio. Lo delató que **M6 sobreviviera** —
   el mutante más importante para la política de arranque. Ahora la ruta se
   deriva del módulo importado y el hijo comprueba que importó el árbol bajo test.
2. `NameError` en el snippet `-c`; detectado por el baseline.
3. El verificador no creaba el directorio de export; crash en V-04.
4. El verificador esperaba que la guardia pasara en un export sin git; la
   expectativa era errónea y se separó en tres checks.
5. El verificador buscaba el texto del assert en una salida que `--tb=no` oculta;
   corregido para afirmar sobre el test que debe fallar.

Además queda **D-6**, heredado y no tocado: el test de entorno de MT-0003 tiene
el mismo defecto del punto 1, y por eso no detectaría una mutación de la política
de arranque. Su fichero está protegido; la sensibilidad la aporta el fichero
nuevo, y así queda registrado.

## 6. Qué no se ha podido verificar

- La suite completa y cualquier regresión fuera de los módulos ejecutados.
- PAPER contra feed real, y por supuesto live.
- G-1 (sin persistencia), G-2 (sin activación en caliente), G-3 (path live no
  medido) y G-4 (`paper_cycle.py` sigue sin rule 0). Ninguno se cierra aquí.
- La independencia real del verificador: es procedural, no una segunda persona.

## 7. Commit y evidencia

Commit `ef7955dc5973ab863f010e02a1297a455ef276da`, seis ficheros, +1326/−0.
`git diff HEAD^ HEAD -- src .github pyproject.toml .gitignore uv.lock` vacío.

- [RUN_REPORT.md](RUN_REPORT.md) · [RUN_REPORT.json](RUN_REPORT.json) · [verification.json](verification.json)
- [evidence/00_scope.txt](evidence/00_scope.txt) · [01_tests_regression.txt](evidence/01_tests_regression.txt) · [02_static.txt](evidence/02_static.txt) · [03_mutants.txt](evidence/03_mutants.txt) · [04_guard_negative_control.txt](evidence/04_guard_negative_control.txt) · [05_guard_fail_closed.txt](evidence/05_guard_fail_closed.txt) · [06_hashes.txt](evidence/06_hashes.txt)
- Contratos: [MT-0004-R1.md](../../MT-0004-R1.md) · [runtime_authority_map.md](../../runtime_authority_map.md) · [AUDIT_BACKLOG.yaml](../../AUDIT_BACKLOG.yaml)

## 8. Veredicto independiente

**`VERIFIED_SCOPED`** — 13/13 checks, exit 0, 344 s. Todos los criterios del
alcance declarado se cumplen; ninguna propiedad fuera del alcance se reclama. La
salvedad de autoría (`BUILDER == VERIFIER`) está escrita en el propio JSON y
obliga a leer el veredicto como «verificado de forma reproducible», no como
«revisado por un tercero».

## 9. Siguiente tarea READY

`null`. No hay ninguna tarea con contrato que pueda ejecutarse. La recomendación
registrada es abrir ticket para **G-2** (superficie de activación en caliente),
el único gap cuya corrección vive entera en el árbol. Hasta entonces, cualquier
`NEXT_READY` sería un nombre inventado.

## 10. La lección estructural

El bloqueo anterior no fue un fallo de implementación: fue un fichero de
autoridad en una ruta ignorada. Ahora los contratos viven en `docs/audit/`,
versionados, y una guardia hace fallar el build si uno de ellos se ignora, se
pierde o deja de estar trackeado. La prueba de que la guardia no es decorativa
está en V-05b y V-07: se niega a saltarse fuera de git y falla cuando le
introducen un contrato en `reports/`.
