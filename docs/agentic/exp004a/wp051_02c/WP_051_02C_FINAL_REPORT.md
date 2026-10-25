# WP-051-02C — informe final

**Run**: `wp051-02c/EXP-004A/2026-10-21`
**Rama de trabajo**: `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Regla corregida en**: `c280a1fe43743577abf22ba6d86223197e1c858c`
**Sidecar y pruebas P0 en**: `5462517`
**Generador declarado de phase 2 en**: `daa7bde`
**C-016 en**: `9488c60`
**Deadline**: `2026-10-22T00:00:00Z` — cumplido antes de que abra la ventana de captura.

---

## 1. Resumen ejecutivo

`P0_CORRECTION = PASS`. `CERTIFICATION = BLOCKED`. `PROMOTION = NO_PROMOTION`.

La divergencia C-004 entre RFC-050 §3 y `classify_day` está corregida y verificada por ejecución: la
cobertura decide **presencia** y todas las barras almacenadas deben estar cerradas y dentro de su
límite de lag para que una jornada se admita. La corrección no se aplicó retroactivamente al ledger:
un sidecar versionado conserva el veredicto registrado y el corregido, y los 248 prefijos atestados se
recomputaron desde bytes crudos con coincidencia total entre reconstrucción y runtime.

Que P0 pase **no** certifica el experimento. No existe todavía ninguna ejecución prospectiva posterior
al parche, la captura phase 2 está abierta, hay 4 días admitidos y no 90, el tamaño declarado no se ha
caminado y la independencia no está demostrada.

## 2. Estado diferenciado por claim

| Claim | Estado en este WP | Base | Qué falta |
| --- | --- | --- | --- |
| **C-004** admisión diaria | **CERRADO — PASS** | regla = RFC-050 §3; 7 adversariales; 248/248 prefijos; runtime = sidecar; evidencia original idéntica | nada para P0; nueva ejecución prospectiva para validar 90 días |
| **C-015** generador phase 2 | **FAIL / BLOCKED (parcial)** | el comando declarado ya existe y se niega a inventar (`st6:tape` exit 2, ventana vacía exit 3); 20 tests | gobernanza que re-emita la declaración con `generator_code_commit` real y contrato del tape |
| **C-016** rama alternativa de coste | **UNREACHABLE_UNDER_DECLARED_COST_MODEL** | suelo de 20.0 bps de comisión + spread positivo; mínimo medido 20.001191 bps | nada: el umbral no se cambia; hipótesis nueva exige nuevo pre-registro |
| **C-000** independencia | **NO LEVANTADO** | dos scripts, dos roles simulados y otro worktree no son verificación independiente | procedencia e identidades demostrables según la política aprobada |
| **C-013** prueba de tiempo | **TIME_PROOF_WEAK** | sin attestation de tiempo externo de confianza | attestation externa |
| Escape de symlink con privilegios de host | **NOT_EXECUTED / UNPROVEN** | no probado en este run | prueba explícita en entorno controlado |
| Impacto a 500 USDT | **NOT_EXECUTED / UNPROVEN** | 912/912 filas caminaron 200 USDT | caminar profundidad real a 500 |

## 3. Qué se ejecutó realmente

| Comprobación | Resultado | Código de salida |
| --- | --- | --- |
| `pytest test_prospective_admission.py test_exp004a_capture.py -q` | 56 passed | 0 |
| `pytest test_exp004a_verify_adversarial.py test_prereg_gate_two_phase.py test_prereg_gate.py test_prereg_gate_escape.py -q` | 89 passed, 1 skipped (symlinks) | 0 |
| `pytest test_edge03_forward.py -q` | 33 passed | 0 |
| `ruff check` sobre código tocado | All checks passed | 0 |
| `scripts/wp051_02c_recalculate.py` | 248 registros, 5 corregidos, 0 dentro de ventana, `runtime_agrees_with_sidecar: true` | 0 |
| `scripts/exp004a_capture.py --slice 1h:BTC --dry-run` | ventana sin abrir → rechazo | 3 |
| `scripts/exp004a_capture.py --slice st6:tape --dry-run` | contrato indefinido → rechazo | 2 |
| `pytest tests/unit/research -q` | **timeout a 600 s, no superado** | — |

La suite completa de `tests/unit/research` no se declara superada. Se ejecutaron y se reportan por
separado los conjuntos afectados por el cambio.

## 4. Números que cambian

| Métrica | Antes (registrado) | Después (corregido) |
| --- | --- | --- |
| Jornadas admitidas, lane `1h` | 5 | 3 |
| Jornadas admitidas, lane `1h+15m` | 4 | 1 |
| Total admitidas | 9 | 4 |
| Registros corregidos | — | 5 (4 días) |
| Correcciones dentro de la ventana de captura | — | **0** |

Días afectados: `2026-10-15`, `2026-10-17` (ambos lanes), `2026-10-19`, `2026-10-20`. El caso
`2026-10-15` (1h) tenía 24 de 24 barras almacenadas, 22 puntuales y 2 con lag de 3 h 56 min y 2 h 56 min
frente a un bound de 2 h: cobertura 100 %, y aun así no era una jornada observada. Ese es exactamente
el error que el ratio ocultaba.

## 5. Inmutabilidad

- `data/exp004a/admission_1h.jsonl` → `73f8ba7b…` y `admission_1h+15m.jsonl` → `1f10efb4…`, idénticos
  a los hashes capturados **antes** del cambio (`evidence/pre_change_hashes.txt`).
- 248/248 registros verificados contra su prefijo atestado; ningún día re-sellado; cero reescrituras.
- El tape ST-6 creció de 912 a 924 filas: los 2 030 451 bytes sellados siguen produciendo
  `3d5755d7…`, luego el fichero es append-only y la evidencia de 02B permanece como prefijo exacto.
- `docs/agentic/exp004a/independent/*` y `config/preregistrations/*` no se modificaron.

## 6. Estados de worktree (la contradicción «entregables sin commit»)

| Worktree | HEAD | Estado |
| --- | --- | --- |
| `Downloads/bot freebuff` (este WP) | `9488c60` tras este commit | rama de trabajo, cambios de este WP commiteados; ficheros modificados por otros WPs siguen sin tocar |
| `Downloads/bot-freebuff-wp051-02b-clean` | `47116b2` (detached) | limpio, **pero no contiene el paquete 02B** |
| Resto (26 worktrees) | detachados o en sus ramas | fuera del alcance de este WP |

Hecho comprobado: `docs/agentic/exp004a/wp051_02b/` está **sin versionar** (`??`) en este worktree y
no existe en `HEAD`. Un worktree limpio en `47116b2` no significa que los entregables de 02B estén
versionados: significa que ese worktree no los tiene. Este WP no commitea ficheros de 02B (no son
suyos); los cita por ruta y con hash local, y deja constancia de que su procedencia versionada sigue
pendiente.

## 7. Riesgos

1. **La ventana de captura abre el 2026-10-22.** Cualquier barras recogidas antes de que la declaración
   phase-2 cite un commit real de generador quedan sin procedencia formal aunque las barras sean
   honestas. Es un riesgo de gobernanza, no de datos.
2. **`st6:tape` sin contrato.** Sin la regla de rondas por ventana, el dataset de tape no puede
   producirse ni auditarse; su row_count declarado (2700) no es verificable.
3. **Muestra mínima.** 4 jornadas admitidas no sostienen ninguna conclusión económica: el mínimo
   pre-registrado es de 90 días.
4. **Independencia.** Este informe no es una verificación independiente. Lo produjo el mismo entorno
   que corrigió el código, y así se declara.
5. **`FALSE_SUCCESS=0`** se afirma solo sobre los controles P0 ejecutados aquí (regla, adversariales,
   reconstrucción, inmutabilidad, rechazos del extractor). No es una certificación universal.

## 8. Continuación recomendada

1. **Gobernanza (antes de que cierre la ventana)**: re-emitir `EXP-004A.datasets.json` con
   `generator_code_commit` = commit de `scripts/exp004a_capture.py`, sin editar las entradas
   originales in situ.
2. **Contrato del tape**: definir unidad de ventana, rondas obligatorias, tratamiento de huecos y
   columnas obligatorias; después implementar `st6:tape` con tests y sellar el manifiesto.
3. **Primera extracción real** cuando existan barras dentro de la ventana: `--slice 1h:BTC`,
   `1h:ETH`, `1h:SOL`, y sellado con el commit vigente.
4. **Verificación independiente** con identidades y procedencia demostrables (no este entorno).
5. **Attestation de tiempo externa** para cerrar C-013.

## 9. Evidencia del paquete

`WP_051_02C_CHANGELOG.md` · `WP_051_02C_RECALCULATION.json` · `WP_051_02C_TEST_REPORT.md` ·
`WP_051_02C_EVIDENCE_MANIFEST.json` · `RUN_REPORT.md` · `RUN_REPORT.json` ·
`WP_051_02C_C015_VERDICT.md` · `WP_051_02C_C016_REACHABILITY.json` · `evidence/`

Cero órdenes. Cero credenciales. Cero cambios de riesgo o capital. Cero promoción.
