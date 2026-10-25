# WP-051-02C — run report

**Run**: `wp051-02c/EXP-004A/2026-10-21` · **Rama**: `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Código bajo prueba**: `c280a1fe43743577abf22ba6d86223197e1c858c`
**HEAD durante el run**: `d2aea555d952cccd1204764bea836528552d7471` (otros WPs han commiteado encima; la corrección es ancestro)
**Entorno**: Windows, Git Bash, Python 3.11 del `.venv` del proyecto. Sin red.
**Deadline**: `2026-10-22T00:00:00Z` — cumplido con la corrección fijada **antes** de que abra la
ventana de captura.

---

## 1. Qué se ejecutó

1. Se leyeron el defect register, el informe independiente, las veredictas y el RFC-050 §3 de WP-051-02B,
   y se localizó el código real de `classify_day` (`src/trading_bot/research/prospective/admission.py`)
   en lugar de asumir rutas.
2. Se capturaron hashes y estado **antes** de tocar código
   (`evidence/pre_change_hashes.txt`, `evidence/pre_change_state.txt`).
3. Se corrigió la condición de lag a universal sobre barras almacenadas y se añadieron 7 casos
   adversariales.
4. Se escribió `scripts/wp051_02c_recalculate.py`, que re-deriva cada veredicto desde el **prefijo
   atestado** del propio registro (bytes crudos), sin reescribir evidencia, y publica un sidecar
   versionado con `recorded_verdict`, `corrected_verdict` y `runtime_verdict`.
5. Se ejecutaron las suites afectadas, el lint y la comprobación de inmutabilidad.
6. Se abordó C-015 en un paquete separado: el generador declarado existe ahora para series de barras,
   con tests de rechazo; el slice `st6:tape` se rechaza por contrato indefinido.
7. Se documentó C-016 sin tocar el umbral.

## 2. Resultado por gate

| Gate | Estado | Base |
| --- | --- | --- |
| **P0 — C-004** | **PASS** | regla = RFC-050 §3, 7 adversariales, 248/248 prefijos recomputados, runtime coincide con el sidecar, evidencia original idéntica |
| P1 — C-015 | FAIL / BLOCKED (parcial) | extractor real para `1h:*`/`15m:*`; `st6:tape` sin contrato de slice; declaración sigue con `generator_code_commit` a cero |
| P2 — C-016 | UNREACHABLE_UNDER_DECLARED_COST_MODEL | suelo de ida y vuelta 20.001191 bps > 20.0 bps; umbral sin cambios |
| Certificación global | **BLOCKED** | sin ejecución prospectiva post-parche, captura phase 2 abierta, días admitidos insuficientes, `DECLARED_SIZE_NOT_WALKED`, independencia no probada, `TIME_PROOF_WEAK` |
| Promoción | **NO_PROMOTION** | 0 órdenes, 0 cambios de riesgo o capital |

`P0_CORRECTION=PASS` **no** es `CERTIFICATION=PASS`. La corrección arregla cómo se juzga una jornada;
no produce jornadas.

## 3. Números

| Métrica | Valor |
| --- | --- |
| Registros reevaluados | 248 (234 `1h` + 14 `1h+15m`) |
| Admitidos registrados | 9 |
| Admitidos corregidos | 4 |
| Registros corregidos | 5 (4 días: 2026-10-15, 10-17, 10-19, 10-20) |
| Correcciones dentro de la ventana de captura | 0 |
| Prefijos atestados verificados | 248 / 248 |
| Test: admisión + extractor | 56 passed |
| Test: verificador + pre-registro | 89 passed, 1 skipped (symlinks) |
| Test: observador forward | 33 passed |
| Lint | `All checks passed!` |

## 4. Decisiones

1. **Manda el RFC.** El runtime se corrigió; no se ajustó la lectura del RFC para que el runtime
   tuviera razón.
2. **Sin re-sellado.** La corrección no reescribe el ledger. Un sidecar versionado conserva ambas
   lecturas y el commit del código que las produjo.
3. **Cero tolerancia al lag.** El 90 % pertenece a la presencia; una barra tardía convierte la
   jornada en `DENSE_BUT_BACKFILLED`, no en «casi observada».
4. **Duplicados fail closed.** Dos registros para el mismo instante de apertura no son dos
   observaciones, así que la jornada es `INCOMPLETE`.
5. **No inventar el contrato del tape.** `st6:tape` declara «4h slot, 3 rounds of 15s»; qué rondas
   pertenecen a qué ventana no está definido. Se rechaza en lugar de fijar una regla unilateral.
6. **C-000 no se levanta** por tener dos scripts, dos roles simulados, otro worktree o el mismo
   desarrollador con otro nombre.

## 5. Limitaciones

- **No hay ejecución prospectiva posterior al parche.** La ventana abre el `2026-10-22`; no se valida
  ningún periodo de 90 días y `PAPER_VALIDATION` no es PASS.
- La suite `tests/unit/research` completa **no terminó en 600 s**; se ejecutaron y se reportan por
  separado las suites afectadas.
- `C-013` sigue `TIME_PROOF_WEAK`; sin attestation de tiempo externo de confianza.
- El escape de symlink con privilegios de host y el impacto a 500 USDT siguen
  `NOT_EXECUTED/UNPROVEN`.
- `FALSE_SUCCESS=0` se afirma **solo** para los controles P0 ejecutados en este run, no como
  certificación universal.

## 6. Evidencia

- `WP_051_02C_CHANGELOG.md` — qué cambió y por qué.
- `WP_051_02C_RECALCULATION.json` — sidecar por lane/día/serie con hashes y barras tardías.
- `WP_051_02C_TEST_REPORT.md` — comandos, salidas y exit codes.
- `WP_051_02C_EVIDENCE_MANIFEST.json` — rutas, tamaños, SHA-256 y commit.
- `WP_051_02C_C015_VERDICT.md`, `WP_051_02C_C016_REACHABILITY.json` — los dos defectos menores.
- `WP_051_02C_FINAL_REPORT.md` — estado diferenciado y continuación.
- `evidence/` — estado y hashes previos al cambio, y las recomputaciones de 02B.
