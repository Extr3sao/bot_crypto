# WP-051-02D — informe final

**Run**: `wp051-02d/EXP-004A/2026-10-21`
**Rama**: `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Deadline**: antes de `2026-10-22T00:00:00Z` — cumplido.
**Regla de aceptación**: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`, sin validez retroactiva.

---

## 1. Resumen

| Campo | Valor |
| --- | --- |
| `WP_051_02D` | **PASS** |
| `C_015_PROVENANCE` | **PASS** para la declaración nueva y sus capturas válidamente ligadas |
| `C_004` | PASS según verificaciones vigentes (no tocado por este WP) |
| `C_016` | `UNREACHABLE_UNDER_DECLARED_COST_MODEL` |
| `C_013` | `TIME_PROOF_WEAK` |
| `PAPER_VALIDATION` | `NOT_PASS` |
| `CERTIFICATION` | **BLOCKED** |
| `PROMOTION` | **NO_PROMOTION** |
| Órdenes / ejecuciones económicas | **0** |

El problema que resolvía este WP no era de datos sino de procedencia: el comando declarado podía
producir un slice impecable sin que ninguna declaración nombrase el código que lo produjo. Ahora la
captura pregunta primero, y si la respuesta no está firmada por un commit, por un hash y por una
vigencia anterior a la ventana, no escribe nada.

## 2. Commits

| Commit | Contenido |
| --- | --- |
| `fc036d9` | Contrato de procedencia + extractor gobernado + 22 pruebas nuevas |
| `a179ed0` | Declaración sucesora `EXP-004A.datasets.phase2/v1` |
| `e170ae1` | Contraste por id de objeto de Git (LF/CRLF) |
| `583c663` | Preflight, verificador independiente y paquete de evidencia |
| `ca2a740` | Corrección de la fixture del verificador y primer veredicto 5/5 |
| `0c54133` | El RFC deja de adjudicar ACC-10 en su propio nombre |

El commit que lleva este informe cierra el paquete y es el que un lector debe mirar para los hashes
durables.

## 3. Cadena de procedencia

```
EXP-004A.datasets.json            sha256 8946f871…  blob 43c9deea…  (intacta desde 47116b2)
        │ supersedes (por referencia, sin reescritura)
        ▼
EXP-004A.datasets.phase2.json     sha256 eb27cedc…  blob 9421cc52…  commit a179ed0
                                  vigencia 2026-10-21T16:00:00Z
        │ generator.commit
        ▼
scripts/exp004a_capture.py        fc036d967923f09a6092cb0e5de7409afd07ebd7
                                  blob 052832c2…  sha256 af1ab7cc…
        │ ejecuta
        ▼
captura elegible                  fetched_at_ms ≥ vigencia  ∧  open_ms ∈ ventana
        │ escribe
        ▼
manifiesto con bloque provenance  declaration_id, commit, sha256, supersedes, ventana, basis
```

## 4. Verificación independiente

Emitida por `verifier-c/EXP-004A/WP-051-02D`, que **no importa** `trading_bot` ni el preflight
(comprobado por AST en `V-POL-03`). No acepta los informes del builder como evidencia: recomputa
digests, commits, blobs, orden temporal y ejecuta el comando declarado en un directorio desechable.

| Control | Resultado | Qué se recomputó |
| --- | --- | --- |
| `TECHNICAL_VERIFICATION` | **PASS** | campos, deriva por entrada, ventana, comandos, `st6:tape`=2, vacío=3, fixture positiva verbatim, pre-vigencia=5 |
| `PROVENANCE_VERIFICATION` | **PASS** | SHA completo, blob del commit, `hash-object` del worktree, ascendencia, digest de la original desde el commit congelado |
| `TEMPORAL_VERIFICATION` | **PASS** | `issued ≤ effective ≤ window`, commit de la declaración anterior a la ventana y ancestro de HEAD, sin capturas previas, puerta de elegibilidad en el código |
| `ARTIFACT_INTEGRITY` | **PASS** | artefactos presentes, commiteados y sin modificar; digests del builder recalculados |
| `POLICY_COMPLIANCE` | **PASS** | original intacta, `NO_PROMOTION` intacto, `BUILDER != VERIFIER`, extractor sin red ni credenciales, preregistro sin cambios |

- `WP_051_02D_PROVENANCE_VERIFICATION.json` — 5/5 controles, **29 comprobaciones**, `status = PASS`.
- `WP_051_02D_VERIFIER_SEAL.json` — 19 entradas del manifiesto verificadas, **0 discrepancias**,
  **0 artefactos requeridos sin listar**.

El sello no puede hashearse a sí mismo y no re-hashea el informe de verificación que acompaña: hashea
cada entrada que el manifiesto reclama. Está declarado en `EVIDENCE_MANIFEST.json > hashing`.

## 5. Qué se probó realmente

| Comprobación | Resultado | Exit |
| --- | --- | --- |
| `test_exp004a_provenance.py` + `test_exp004a_capture.py` | 46 passed | 0 |
| `test_prospective_admission.py` (C-004, no regresión) | 36 passed | 0 |
| Gate de preregistro (3 suites) | 69 passed, 1 skipped (symlinks) | 0 |
| Verificador adversarial existente | 20 passed | 0 |
| Forward observer EDGE-03 | 33 passed | 0 |
| Preflight de procedencia | 15/15 PASS | 0 |
| Verificador de procedencia | 5/5 PASS, 29 checks | 0 |
| Sello del manifiesto | 19/19, 0 discrepancias | 0 |
| `ruff check` | limpio | 0 |

## 6. Defectos y bloqueos que quedan abiertos

1. **Ninguna captura prospectiva existe todavía.** La ventana abre el 2026-10-22. Lo verificado es la
   regla y sus rechazos; no hay ninguna jornada de mercado que sostenga una conclusión económica.
2. **Attestation de tiempo externa ausente.** La cronología se apoya en ascendencia de Git y en el
   reloj de ingesta del store. El registro lo declara (`external_timestamp: UNAVAILABLE`) y C-013
   permanece `TIME_PROOF_WEAK`. Un sello RFC 3161 o un log de transparencia sería la siguiente mejora
   real, no un cambio de este WP.
3. **`st6:tape` sigue sin contrato de slice.** El dataset de tape no puede producirse; su `row_count`
   declarado (2700) no es verificable y el extractor lo rechaza con exit 2.
4. **Suite completa `tests/unit/research` no ejecutada.** Agotó 600 s en WP-051-02C; aquí se ejecutan
   y se reportan por separado las suites afectadas, con sus códigos de salida.
5. **El gate no verifica la sucesión.** Se comprobó en preflight y en el verificador; si se quiere que
   `prereg_gate` lo exija, hace falta una enmienda explícita del gate, que este WP no hace.
6. **Worktree compartido.** Había cambios de otros WP en el checkout; no se han tocado ni revertido, y
   este paquete solo commitea sus ficheros.

## 7. Estado exacto de C-015

`C-015_PROVENANCE = PASS` significa exactamente tres cosas:

1. existe una declaración sucesora inmutable, versionada y ligada criptográficamente a la original;
2. el generador que producirá las capturas está identificado por su SHA completo, y el fichero que se
   ejecutaría es el blob de ese commit;
3. ninguna captura puede ser elegible si alguna de sus barras fue ingestada antes de la vigencia de la
   declaración, y ninguna captura anterior a la autorización puede adquirir validez retroactiva.

No significa que EXP-004A tenga datos suficientes, ni una ventaja económica, ni permiso para
promocionar.

## 8. Evidencia del paquete

`RFC_EXP004A_051_02D.md` · `WP_051_02D_BASELINE.json` · `WP_051_02D_PREFLIGHT.json` ·
`WP_051_02D_PREFLIGHT.md` · `WP_051_02D_TEST_REPORT.md` · `WP_051_02D_CHANGELOG.md` ·
`WP_051_02D_PROVENANCE_VERIFICATION.json` · `WP_051_02D_PROVENANCE_VERIFICATION.md` ·
`WP_051_02D_VERIFIER_SEAL.json` · `EVIDENCE_MANIFEST.json` · `RUN_REPORT.md` · `RUN_REPORT.json` ·
`evidence/` (`CLI_CONTROLS.json`, logs de pytest, stdout del preflight).

Cero órdenes. Cero credenciales. Cero cambios de riesgo o capital. Cero promoción.

## 9. Siguiente puerta

No es ampliar arquitectura: es observar la ventana, medir la calidad de los datos capturados y
comprobar si existe una hipótesis de trading económicamente viable después de costes. Un PASS técnico
de captura no es una afirmación de rentabilidad.
