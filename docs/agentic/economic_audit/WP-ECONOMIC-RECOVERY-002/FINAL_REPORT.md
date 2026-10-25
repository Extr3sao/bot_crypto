# WP-ECONOMIC-RECOVERY-002 — Reproducibilidad de la evidencia

**Estado:** completo, con **una regresión declarada** y **cuatro bloqueos** (§6, §7).
Nada de lo declarado aquí se apoya en una afirmación sin comando: cada número tiene
su artefacto y su verificador independiente (§5).

| campo | valor |
| --- | --- |
| rama | `repro/economic-recovery-002` |
| base | `e67194e7` (extremo de `audit/economic-blocker-001`) |
| commits propios | `eb53e631` (arreglos), `64fa5112` (endurecimiento de tests), más el commit de entregables |
| Python | 3.11.15 |
| verificador independiente | [`INDEPENDENT_VERIFICATION.json`](INDEPENDENT_VERIFICATION.json) — **19 PASS · 0 FAIL · 0 NOT_ASSESSED**, exit 0 |

---

## 1. Qué se pidió, qué se midió

El WP anterior dejó tres defectos de reproducibilidad. Este WP los cierra **sin tocar
economía**: no se movió una comisión, un slippage, un umbral de admisión ni una señal.
El verificador lo comprueba sobre el diff (`no_runtime_or_configuration_logic_changed`):
entre `e67194e7` y `64fa5112` el único fichero de `src/`+`config/` modificado es
`config/strategy_admission.json`, y su contenido semántico es idéntico (§2).

| medición | WP-001 | WP-002 |
| --- | --- | --- |
| nodos que fallan en el árbol | 103 | **104** |
| nodos que fallan en checkout limpio | 124 (`git archive`, sin `.git`) | **104** (`git clone` real) |
| nodos que fallan **sólo** en el checkout limpio | 21 | **0** |
| ficheros versionados reescritos por la suite | 1 (`RFC047_RUNTIME_VERIFICATION.json`, 92 líneas) | **0** |
| `build_strategy_admission.py --check` | exit 1 | **exit 0** |

Los 104 del árbol y los 104 del clon son **el mismo conjunto**, nodo por nodo
([`REPRODUCIBILITY_COMPARISON.json`](REPRODUCIBILITY_COMPARISON.json):
`only_working=0`, `only_clone=0`).

---

## 2. `PROVENANCE_ANCHOR_STALE` — el ancla apuntaba a nada

**Lo que había.** El ledger registraba para `docs/STRATEGY_ADMISSION_MATRIX.json` el
SHA-256 `5f794c36…`. Ese valor **no coincide con ninguna revisión commiteada** de ese
fichero: hay una sola revisión (`3271a975`) y su digest es `4e15882c…`. No era "la
matriz anterior": era un estado de matriz que nunca entró en git.

**Por qué nadie se enteró.** Los veredictos de admisión eran correctos (24 estrategias,
0 admitidas), así que el runtime —que falla cerrado— funcionaba. Y `--check` comparaba
**texto decodificado** con `read_text`, que normaliza `\r\n`: en Windows el fichero
escrito por el builder quedaba con CRLF mientras el blob está en LF, y el `--check`
daba "up to date" sobre bytes que ya no eran los del blob. El ancla estaba rota por
partida doble: valor equivocado y comprobación incapaz de verlo.

**La reparación** ([`ANCHOR_REPAIR.json`](ANCHOR_REPAIR.json), commit `eb53e631`):

1. el ledger se reconstruye desde la matriz commiteada — **una sola línea de diff**, el
   digest; el resto del payload es idéntico (`ledger_payload_unchanged_except_sources:
   true`);
2. `build_strategy_admission.py` escribe con `newline="\n"` y su `--check` compara
   **bytes**: el artefacto deja de depender de quién lo construye;
3. `.gitattributes` fija con `-text` los cuatro ficheros de la cadena
   (`config/strategy_admission.json`, la matriz, los resultados V3 y el modelo de
   costes), porque un `git clone` en Windows con `core.autocrlf=true` —el valor por
   defecto del sistema en esta máquina— convertía las 614 líneas de la matriz a CRLF y
   rompía el digest de un fichero que nadie había editado;
4. un test nuevo, [`test_strategy_admission_ledger.py`](../../../../tests/unit/research/test_strategy_admission_ledger.py),
   compara el artefacto commiteado con el reconstruido, verifica cada digest de
   `_sources` contra su fichero y prohíbe CRLF. **Un ledger que derive falla la suite**,
   no espera a la próxima auditoría.

**El eslabón de arriba sigue roto, y se declara.** `scripts/build_admission_matrix.py`
lee seis `reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json` que están gitignorados
y **no existen aquí (0/6)**. Re-ejecutarlo sin esos ficheros no reproduce la matriz: la
degradaría en silencio a una sola familia —exactamente el mecanismo que produce un ancla
caducada—. Por eso el ancla autoritativa es la matriz commiteada y la regeneración de
ésta queda como bloqueo declarado, no como algo que este WP invente.

---

## 3. `TEST_SUITE_WRITES_TRACKED_DATA` — la suite reescribía el repo que medía

**Causa raíz, no el síntoma.** `scripts/rfc047_builder.py:build_runtime()` persiste
`data/st6/RFC047_RUNTIME_VERIFICATION.json` como efecto lateral, y un test llamaba a
`build_runtime()` para leer la decisión. El artefacto versionado —que *es* la evidencia—
se sobrescribía con lo que hubiera en el checkout, y su `built_at_utc` cambiaba en cada
ejecución (92 líneas de diff medidas por el WP anterior).

**Arreglo.** `build_runtime(..., persist=True)`: el test pide `persist=False` y lee el
documento devuelto. `write_json` y el informe Markdown escriben con `newline="\n"` para
que un rebuild en Windows no cambie los bytes de artefactos cuyos digests están fijados
en otros sitios.

**Prueba, no promesa.** El script de medición hashea **2018 ficheros versionados** antes
y después de cada corrida. Resultado en árbol y en clon:
`tracked_files_rewritten = []`, y el SHA-256 de `RFC047_RUNTIME_VERIFICATION.json` es el
mismo antes y después de ejecutar su propio fichero de tests. La suite deja de mutar el
repositorio.

---

## 4. Los 21 fallos "exclusivos del checkout limpio": qué eran de verdad

El WP anterior los midió con `git archive HEAD | tar -x`, que produce los ficheros
versionados **pero no `.git`**. Nueve de esos 21 fallaban por eso y sólo por eso: tests
que consultan el historial (`git show`, `git log`, rehearsal de commit limpio). El
método fabricaba el defecto que decía medir.

Medido con un `git clone` real ([`REPRODUCIBILITY_COMPARISON.json`](REPRODUCIBILITY_COMPARISON.json)),
los 21 **pasan en árbol y en clon**. Lo que los hacía fallar era, por grupos:

| causa real | nodos | cómo se comprobó | arreglo |
| --- | --- | --- | --- |
| el "checkout limpio" no tenía `.git`: los tests consultan historial (`git show`, `git grep`, rehearsal) | **17** | los 8 no-recovery fallan en un `git archive` con exit 128 (`not a git repository`) o una lista vacía de `git grep`, y pasan en el clon | método: `git clone`, no `git archive` |
| `PYTHON = REPO/.venv/Scripts/python.exe` en los tests del tick (no existe en un clon; además sólo Windows) | 2 | `FileNotFoundError: [WinError 2]` del subproceso | `Path(sys.executable)` |
| el log de ejecución `data/st6/ST6_RUNS.jsonl`, escrito por el propio test | 2 | `assert runs, "the autonomous layer has never ticked"` | el test se salta con motivo cuando el checkout no tiene log |

Los 21 pasan también en un clon **sin `.venv`** (verificador:
`the_previously_clean_only_nodes_pass_in_a_fresh_clone`, 25 nodos, exit 0).

**El log de ejecución, con procedencia determinada** (no se ha borrado): 24 eventos,
`ALREADY_RUNNING` y `REFUSED_INVALID_ARGUMENTS`, **cero `COLLECTED`**. Es residuo de los
propios tests —uno sostiene el lease, otro pasa `--rounds 0`—, no evidencia de campaña.
Versionarlo habría metido un log de máquina en el repo y, peor, habría vuelto a convertir
un test en escritor de un fichero versionado. Se deja donde está y se documenta.

**Las dependencias que sí existen** ([`DECLARED_DEPENDENCIES.json`](DECLARED_DEPENDENCIES.json)):
19 rutas que un checkout limpio no tiene, ninguna versionada, agrupadas por quién debía
producirlas: 16 son salidas gitignored de productores que están en el repo
(`reports/profitability_gate035/*`, `reports/rfc035/search_round_3/*`,
`reports/strategy-baseline/COST_BARRIER.json`, `data/raw/alpha003/price/*`), 1 es
evidencia de host (`data/st6/ST6_HEALTH_STATUS.json`) y 2 son **entregables que nunca se
commitearon** (`reports/rfc046/IMPACT_ASSESSMENT.md`,
`docs/research/work_packages/WP-HTF-PIT-001_htf_availability_unit_fix.md`). Éstas
explican fallos **preexistentes** que fallan en los dos árboles; ninguna de las 21.

Fichero de trazas crudas: [`parts/clone_dependency_tracebacks.txt`](parts/clone_dependency_tracebacks.txt).

---

## 5. Verificación independiente

[`scripts/wp_eco002_verify.py`](../../../../scripts/wp_eco002_verify.py) no importa
ningún script del WP: re-hashea, re-ejecuta el `--check` del builder, re-clona el repo y
re-corre los tests que el WP dice haber arreglado. **19 PASS · 0 FAIL · 0 NOT_ASSESSED**,
exit 0. Incluye dos clones: uno con `core.autocrlf=false` (los 21 nodos + el test del
ledger, sin `.venv`) y otro con el **valor por defecto de esta máquina**
(`core.autocrlf=true`), donde comprueba que los cuatro ficheros de la cadena siguen en LF
y el test del ledger pasa.

---

## 6. La regresión declarada: el pin del cost-barrier

`config/strategy_admission.json` es **entrada declarada y pinneada** del gate de deriva
del cost-barrier (WP-7): `data/recovery/COST_BARRIER_EXPLORER.json` registra su SHA-256
`6c4dd0be…`, que es el del ledger **con el ancla caducada**. Reparar el ancla cambia los
bytes de ese fichero, así que:

- el gate pasa de `CHECK_ONLY_WITH_ADVISORIES` (exit 2) a `INTEGRITY_FAILURE` (exit 5);
- **un** nodo preexistente cambia de verde a rojo:
  `test_cost_barrier_gate.py::test_a_missing_required_input_blocks_rather_than_fails`
  (el gate ahora informa deriva de pin, que tiene precedencia sobre "bloqueado").

**El gate tiene razón**: su entrada certificada ya no coincide con el pin. Las dos
salidas fáciles son peores: dejar el ancla caducada (el objetivo del WP) o editar el pin
a mano (falsificar la evidencia). El remedio correcto es **regenerar y re-verificar el
bundle del cost-barrier** con `reports/strategy-baseline/COST_BARRIER.json` presente, lo
que mueve evidencia económica publicada y **queda fuera de este WP**. Que los números no
se muevan es una expectativa razonable —el payload del ledger es idéntico salvo el
ancla— pero **no está probado aquí** y por eso no se afirma: el `reproduce:verifier_passes`
del gate sí sigue en PASS (13 controles, 0 fallos), que es todo lo que se puede decir sin
re-ejecutar la certificación.

---

## 7. Límites y bloqueos

1. **Matriz de admisión no reconstruible** desde un checkout limpio (0/6 entradas
   `reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json`). El ancla es la matriz
   commiteada. Bloqueo de datos, declarado en `ANCHOR_REPAIR.json`.
2. **Pin del cost-barrier derivado** (§6). Requiere re-certificación autorizada.
3. **`ruff format --check .` ya fallaba antes** de este WP (tres ficheros: los mismos que
   toco). No se reformatearon enteros para no mezclar 500 líneas de ruido con el arreglo;
   se comprobó que mis cambios **no añaden** ninguna violación de formato (el diff de
   `ruff format --diff` tiene el mismo número de líneas antes y después en cada fichero).
4. **`data/st6/ST6_RUNS.jsonl` permanece** en el árbol, sin versionar y sin borrar: su
   procedencia está determinada y su contenido es residuo de test (§4).
5. **El árbol no está libre de rojo**: 104 nodos preexistentes fallan en los dos árboles.
   Este WP no los arregla; garantiza que fallan **igual** en un clon limpio, que es la
   única forma de que un rojo signifique algo.

---

## 8. Reproducir

```bash
uv run python scripts/wp_eco002_reproducibility.py --phase working   # ~4 min
uv run python scripts/wp_eco002_reproducibility.py --phase clone     # ~5 min
uv run python scripts/wp_eco002_reproducibility.py --phase healthy
uv run python scripts/wp_eco002_reproducibility.py --phase focused
uv run python scripts/wp_eco002_reproducibility.py --phase assemble
uv run python scripts/wp_eco002_anchor.py
uv run python scripts/wp_eco002_dependencies.py
uv run python scripts/wp_eco002_verify.py                            # ~4 min (dos clones)
```
