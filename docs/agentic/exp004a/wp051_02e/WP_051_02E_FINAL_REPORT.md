# WP-051-02E — Informe final

**Run**: `wp051-02e/EXP-004A/2026-10-21`
**RFC**: `RFC-EXP004A-051-02E` — primera captura prospectiva y verificación temporal independiente
**Resultado**: `WP_051_02E = PENDING_WINDOW`
**Captura prospectiva**: **no ejecutada** (ventana cerrada en el momento de la ejecución)
**Verificador independiente**: `verifier-d/EXP-004A/WP-051-02E`, 31/31 checks PASS
**Ejecuciones económicas**: 0 · **Órdenes**: 0 · **Promoción**: ninguna

---

## 1. Resumen ejecutivo

El RFC pedía una de dos cosas: la primera captura prospectiva real, o el cierre honesto como
`PENDING_WINDOW` si la ventana aún no había abierto. A las `2026-10-21T19:25:58Z` faltaban
**16 441 s** para `2026-10-22T00:00:00Z`, y el store no contenía **ninguna** barra que abriera dentro
de la ventana. No se ha fabricado, sustituido ni retrofechado nada: se ha ejecutado el comando
declarado contra el runtime real, ha devuelto `3` en las tres series, y cero bytes han llegado a
`data/exp004a`.

Lo entregado es, por tanto, la parte que sí se puede demostrar hoy: la cadena de procedencia sigue
intacta, el extractor sigue rechazando lo que debe rechazar, hay un verificador que **no** confía en
el builder y que re-ejecuta cada rechazo, y existe una clasificación mecánica del intento que no
permite llamar «captura» a un rechazo.

## 2. Implementación

Sin tocar nada congelado. `scripts/exp004a_capture.py` y
`src/trading_bot/research/prospective/provenance.py` quedan byte a byte como estaban: el generador
está fijado por `generator.blob_sha256` en la declaración phase 2, de modo que **cualquier** edición
suya habría convertido toda captura futura en `exit 2`
(`GENERATOR_FILE_DIFFERS_FROM_DECLARED`). Los 19 artefactos sellados de WP-051-02D siguen con el
mismo digest (comprobado dos veces: por el builder y por el verificador).

| Fichero | Papel | Líneas |
| --- | --- | --- |
| `scripts/exp004a_wp051_02e_preflight.py` | 10 controles de builder, intento real y clasificación | 839 |
| `scripts/exp004a_wp051_02e_verify.py` | verificador independiente, anclajes propios, 31 checks | 1077 |
| `tests/unit/research/test_exp004a_wp051_02e.py` | 30 pruebas nuevas | 402 |

Decisiones que merecen explicación:

- **La clasificación es mecánica, no narrativa.** `classify()` recibe estado de ventana, códigos de
  salida y rutas publicadas. `CAPTURED` exige un dataset en disco dentro de una ventana abierta;
  cualquier otro nombre exige su ausencia. Un `exit 0` antes de la ventana produce `FAIL`, no
  `CAPTURED`.
- **El verificador declara sus anclajes antes de leer nada.** `PHASE1_SHA256`, `GENERATOR_COMMIT`,
  `WINDOW_START` son constantes del propio fichero. Un verificador que aprende la ventana esperada
  del documento que inspecciona solo puede confirmar que el documento coincide consigo mismo.
- **El verificador no importa `trading_bot` ni ningún script del builder** (`V-POL-01`, por AST), y
  ejecuta el extractor como subproceso, no como librería.
- **No hay scheduler nuevo.** El RFC lo prohíbe explícitamente si no se configura y verifica uno
  real; el preflight publica la invocación exacta y dice que no se ha ejecutado.

## 3. Ejecución real (no un dry-run)

```
$ python scripts/exp004a_wp051_02e_preflight.py --out-dir docs/agentic/exp004a/wp051_02e --attempt
[capture] PENDING_WINDOW: no bar opens inside the declared window yet; the extractor refused with exit 3 and wrote nothing
[preflight] READY_FOR_WINDOW - 10 controls - 0 failed
EXIT=0

$ python scripts/exp004a_capture.py --slice 1h:BTC   # y ETH, SOL, tal como los declara la freeze
{"ok": false, "error": "no bar of BTC.jsonl opens inside the declared window; an empty slice is not a dataset ..."}
EXIT=3   (BTC 3.68 s, ETH 4.22 s, SOL 3.85 s)
```

`data/exp004a` antes y después: los dos ledgers de admisión con el mismo sha256 (`1f10efb4…`,
`73f8ba7b…`) y ningún `EXP-004A-*.jsonl`. Los tres comandos se ejecutaron con el `--out` por defecto
—el que la declaración implica—, no con un directorio temporal: la prueba de que no escriben es que
no hay fichero, no que se lo hayan pedido.

## 4. Pruebas

| Suite | Resultado | Exit |
| --- | --- | --- |
| `test_exp004a_capture.py` + `test_exp004a_provenance.py` | 46 passed | 0 |
| `test_exp004a_wp051_02e.py` (nueva) | 30 passed | 0 |
| `test_exp004a_verify_adversarial.py` | 20 passed | 0 |
| `test_prospective_admission.py` | 36 passed | 0 |
| `test_prereg_gate*.py` | 69 passed, 1 skipped (symlinks) | 0 |
| `ruff check` (3 ficheros) | All checks passed | 0 |

Total 201 passed, 1 skip preexistente. **No ejecutado**: `tests/unit/research` completo — WP-051-02C
agotó 600 s; se declara `NOT_RUN` en `evidence/TEST_RUNS.json`, no «PASS».

## 5. Verificación independiente

`WP_051_02E_INDEPENDENT_VERIFICATION.json`: 31 checks, 5 controles, **PASS**, exit 0.

| Control | Qué se comprobó de forma independiente |
| --- | --- |
| `TECHNICAL_VERIFICATION` | commit/digest/blob del generador, sha256 y blob de phase 1, ventana anclada, 19/19 artefactos de 02D, commit de la declaración anterior a la apertura |
| `PROVENANCE_VERIFICATION` | `exit 0` con verbatim en directorio temporal; `exit 2` al reescribir; `exit 5` antes de vigencia; `exit 3` fuera de ventana; `exit 4` fuente vacía; `exit 2` para `st6:tape` y para un periodo fuera de ventana; `exit 2` con `GENERATOR_BLOB_MISMATCH` ante una declaración adulterada |
| `TEMPORAL_VERIFICATION` | el estado `BEFORE_WINDOW` recalculado con el reloj del verificador coincide con el del builder; `external_timestamp: UNAVAILABLE`; `C-013` débil |
| `ARTIFACT_INTEGRITY` | 6 digests declarados = 6 en disco; 0 datasets; ledgers de admisión intactos; ningún artefacto sellado sucio |
| `POLICY_COMPLIANCE` | sin auto-certificación, gates sin promoción, `L-01` declarada = `L-01` observada, 0 ejecuciones económicas |

## 6. Prueba temporal

`external_timestamp: UNAVAILABLE` en todos los registros. La cronología descansa en dos cosas
verificables y en ninguna más: el orden de Git (el commit de la declaración, `2026-10-21T15:21:23Z`,
precede a la apertura de la ventana) y el `fetched_at_ms` que el observador escribe al ingerir.
`C-013` se mantiene `TIME_PROOF_WEAK`. No se ha usado un `Date` HTTP, el reloj del host ni un commit
como si fueran una attestation.

## 7. Defectos y limitaciones

| ID | Descripción | Estado |
| --- | --- | --- |
| `DEF-02E-01` / `L-01` | El extractor congelado acepta una barra cuyo `fetched_at_ms` es **posterior** al instante de captura y la marca `eligible: true` (`exit 0`). Reproducido por el verificador. | **No corregido, por diseño**: editar el generador rompería la freeze. Remedio: declaración sucesora phase 3 con un commit nuevo del generador, commiteada antes de la ventana que gobierne. |
| `L-02` | No hay scheduler. La apertura de la ventana exige un operador. | Declarado en preflight y run report. |
| `L-03` | Sin attestation externa, `C-013` no puede subir de `TIME_PROOF_WEAK`. | Es el estado correcto, no un defecto a arreglar. |
| `L-04` | El observador estaba dentro de su lag bound (71 min < 2 h) pero la barra de `18:00Z` aún no estaba almacenada al ejecutar. | Revalidar el preflight justo antes de capturar. |

`DEF-02E-01` es material para la procedencia **futura**, no para este intento: sin captura no hay
nada que un store forjado pudiera haber contaminado. Se declara en lugar de silenciarse porque el RFC
pide explícitamente que un fallo de integridad no se convierta en aviso.

## 8. Estado exacto de los gates

| Gate | Estado | Base |
| --- | --- | --- |
| `C-004` | `PASS` | no tocado; `admission.py` sin cambios |
| `C-013` | `TIME_PROOF_WEAK` | sin attestation externa |
| `C-015` | `PASS` (procedencia de la declaración) | cadena verificada por objetos de Git; **sin captura** |
| `C-016` | `UNREACHABLE_UNDER_DECLARED_COST_MODEL` | fuera de alcance |
| `PAPER_VALIDATION` | `NOT_PASS` | no hay datos prospectivos |
| `CERTIFICATION` | `BLOCKED` | nada que certificar |
| `PROMOTION` | `NO_PROMOTION` | — |
| `WP_051_02E` | **`PENDING_WINDOW`** | ni PASS de captura ni FAIL |

`PASS` del verificador **no** significa `EXP-004A=VALIDATED`: significa que la afirmación del builder
(`PENDING_WINDOW`, cero datasets, gates intactos, `L-01` cierta) coincide con la evidencia.

## 9. Bloqueos

Ninguno de autoridad. El único bloqueo es el reloj: la ventana abre el `2026-10-22T00:00:00Z`. No se
ha esperado indefinidamente ni se ha simulado la espera.

## 10. Siguiente acción

1. Poco antes de `2026-10-22T00:00:00Z`, re-ejecutar el preflight y exigir
   `STORE_READABLE → bars_opening_in_window > 0` y `FORWARD_OBSERVER_FRESH`.
2. Ejecutar exactamente `python scripts/exp004a_capture.py --slice 1h:BTC|ETH|SOL`.
3. Re-ejecutar `python scripts/exp004a_wp051_02e_verify.py --mode verify` sobre el nuevo
   `WP_051_02E_CAPTURE_REPORT.json`: solo un `CAPTURED` con dataset verificado puede convertirse en
   `WP_051_02E=PASS`.
4. Antes de cualquier certificación, decidir en gobernanza si se emite la declaración phase 3 que
   cierra `L-01`.

## 11. Evidencia del paquete

`EVIDENCE_MANIFEST.json` sella rutas y sha256 de: este informe, el RFC incorporado, baseline,
preflight, capture report, run report (md y json), verificación independiente, `TEST_RUNS.json`, los
dos scripts, las pruebas, la declaración phase 2, la declaración phase 1, el generador y el manifiesto
sellado de 02D. `WP_051_02E_VERIFIER_SEAL.json` vuelve a hashear cada entrada y comprueba que Git
guarda esos mismos bytes.
