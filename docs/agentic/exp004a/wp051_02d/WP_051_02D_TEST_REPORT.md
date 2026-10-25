# WP-051-02D — informe de pruebas

**Run**: `wp051-02d/EXP-004A/2026-10-21`
**Intérprete**: `.venv/Scripts/python.exe` (Python 3.11.15), pytest 9.1.1, ruff con la configuración del repo.
**Regla de este informe**: se reporta lo que terminó. Una suite que no terminó se declara como no
ejecutada, no como superada.

---

## 1. Suites ejecutadas

| Comando | Resultado | Exit | Duración | Log |
| --- | --- | --- | --- | --- |
| `pytest tests/unit/research/test_exp004a_provenance.py tests/unit/research/test_exp004a_capture.py -q` | **46 passed** | 0 | 29.15 s | `evidence/pytest_provenance_capture.log` |
| `pytest tests/unit/research/test_prospective_admission.py -q` | **36 passed** | 0 | 1.61 s | `evidence/pytest_admission.log` |
| `pytest tests/unit/research/test_prereg_gate.py test_prereg_gate_two_phase.py test_prereg_gate_escape.py -q` | **69 passed, 1 skipped** | 0 | 103.92 s | `evidence/pytest_prereg_gate.log` |
| `pytest tests/unit/research/test_exp004a_verify_adversarial.py -q` | **20 passed** | 0 | 13.13 s | `evidence/pytest_adversarial.log` |
| `pytest tests/unit/research/test_edge03_forward.py -q` | **33 passed** | 0 | 184.24 s | `evidence/pytest_edge03_forward.log` |
| `ruff check` sobre los ficheros tocados | **All checks passed** | 0 | — | — |

El único `skip` es el preexistente de `test_prereg_gate.py:591` (*symlinks unavailable in this
environment*), no una prueba desactivada por este WP.

**No ejecutado**: la suite completa `tests/unit/research` no se ha corrido; en WP-051-02C agotó 600 s
sin terminar. Se ejecutan y se reportan por separado los conjuntos afectados por este cambio.

## 2. Cobertura nueva

`tests/unit/research/test_exp004a_provenance.py` (22 pruebas) construye un repositorio Git temporal y
cubre, con positivos y negativos:

| Propiedad | Prueba |
| --- | --- |
| Una sucesora commiteada que nombra su commit es aceptada | `test_a_committed_successor_naming_its_generator_commit_is_accepted` |
| El registro declara la debilidad de su reloj | `test_the_record_says_what_its_clock_is_worth` |
| Digest de la original erróneo → rechazo | `test_a_successor_that_cites_the_wrong_original_digest_is_refused` |
| La original nunca se abre en escritura | `test_the_original_is_never_opened_for_writing` |
| SHA abreviado o cero → rechazo | `test_an_abbreviated_or_zero_commit_is_not_an_identifier` |
| Commit inexistente → rechazo | `test_a_commit_that_does_not_exist_in_the_repository_is_refused` |
| Generador editado tras declarar → rechazo | `test_a_generator_edited_after_the_declaration_is_refused` |
| Blob declarado distinto del commit → rechazo | `test_a_commit_that_holds_different_generator_bytes_is_refused` |
| Vigencia posterior a la ventana → rechazo | `test_a_declaration_effective_after_the_window_opens_cannot_authorise_it` |
| Emisión posterior a la vigencia → rechazo | `test_issue_date_may_not_follow_the_effective_date` |
| Declaración commiteada dentro de la ventana → rechazo | `test_a_declaration_committed_inside_the_window_is_refused` |
| Declaración sin commit → sin autoridad temporal | `test_an_uncommitted_declaration_has_no_temporal_authority` |
| Declaración editada tras commit → sucia | `test_an_edited_but_committed_declaration_is_reported_as_dirty` |
| Deriva por campo (p. ej. `row_count`) | `test_entry_drift_is_named_field_by_field` |
| Entrada que cita otro commit | `test_an_entry_naming_a_different_commit_than_the_declaration_is_refused` |
| Sucesora que inventa contrato de tape | `test_a_successor_may_not_invent_the_tape_slice_contract` |
| Barras posteriores a la vigencia son elegibles | `test_bars_fetched_after_effect_are_eligible` |
| Barra anterior a la vigencia no es elegible | `test_a_bar_fetched_before_the_declaration_existed_is_not_eligible` |
| Barra fuera de ventana no es elegible | `test_a_bar_outside_the_declared_window_is_not_eligible` |
| Declaración ausente → error con código | `test_authorize_raises_with_every_defect_when_the_declaration_is_absent` |
| El error lleva todos los defectos, no el primero | `test_authorize_carries_more_than_the_first_defect` |

## 3. Controles sobre el comando declarado

Cada fila de `evidence/CLI_CONTROLS.json` es un proceso real (`python scripts/exp004a_capture.py …`)
con su código de salida:

| Control | Exit esperado | Exit obtenido |
| --- | --- | --- |
| `st6:tape` sin contrato de slice | 2 | **2** |
| Ventana sin barras | 3 | **3** |
| Declaración ausente | 2 | **2** |
| Barra capturada antes de la vigencia | 5 | **5** |
| Slice correcto y elegible | 0 | **0** |
| Sobrescritura del dataset | 2 | **2** |

Persistencia verbatim: `verbatim_bytes = true` — el fichero escrito es byte a byte la selección de
líneas del store, sin re-serialización.

## 4. Preflight del builder

`scripts/exp004a_provenance_preflight.py --out docs/agentic/exp004a/wp051_02d` → **15/15 controles
PASS, exit 0** (`WP_051_02D_PREFLIGHT.json`). Incluye: esquema, original intacta, vínculo de sucesión,
SHA completo, bytes del commit, worktree limpio, orden temporal, commit anterior a la ventana,
entradas sin deriva, ventana idéntica, datasets ausentes, `st6:tape` rechazado, sobrescritura
rechazada, permiso de escritura y ausencia de ruta de orden.

## 5. Verificación independiente

Ejecutada por otro rol (`verifier-c/EXP-004A/WP-051-02D`), que no importa `trading_bot` ni el
preflight: `WP_051_02D_PROVENANCE_VERIFICATION.json` y `WP_051_02D_VERIFIER_SEAL.json`. Este informe
no adelanta su veredicto.

## 6. Límites declarados

1. La suite completa de `tests/unit/research` no se ejecutó (timeout histórico de 600 s).
2. El control de symlinks del gate sigue sin poder ejecutarse en este host.
3. No hay ninguna captura prospectiva: la ventana abre el 2026-10-22. Lo probado es la regla y sus
   rechazos, no una jornada de mercado.
4. Sin attestation de tiempo externa; C-013 permanece `TIME_PROOF_WEAK`.
