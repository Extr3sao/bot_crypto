# RUN REPORT — RFC-TAP-PAPER-ADMISSION-REPRO-001 (cierre)

## Identificadores

| Campo | Valor |
| --- | --- |
| Rama | `repro/paper-admission-001` |
| Base medida | `b4c8e3e2` (merge de `main` en la lane, antes de cualquier cambio) |
| Diagnóstico + tres defectos | `c44f912c` |
| Rehearsal de checkout limpio | `ddef6432` |
| **Artefacto verificado** | **`f118e556`** |
| Cierre | `6ae20844` (verificado desde clon; este informe viaja en el commit siguiente) |
| `main` | `e67194e7` — **sin cambios** |

## Entorno

`Windows-10-10.0.26200-SP0` · Python `3.11.15` · uv `0.11.26` · pytest `9.1.1` · git `2.51.1.windows.1`
· `core.autocrlf=true` en el clon (el valor que destapó el defecto A1).

## Corridas

Todas desde clones reales (`git clone --no-hardlinks`), árbol limpio, sin `.venv` previo.

| Commit | Comando | Resultado | Evidencia |
| --- | --- | --- | --- |
| `ddef6432` | `verify_repro.py` | **FAIL 10/12** (V01, V02; 13 de 44 digests) | `evidence/CLONE_ddef6432_verify_repro_FAIL.log` |
| `ddef6432` | `pytest tests/unit/ops -q` | 86 passed | `evidence/CLONE_ddef6432_pytest.log` |
| `ddef6432` | `uv sync --frozen` + `uv lock --check` + import | 0 / 0 / `matplotlib 3.11.2` | — |
| `f118e556` | `uv sync --frozen` | exit 0 | `evidence/CLONE_f118e556_uv_sync_frozen.log` |
| `f118e556` | `uv lock --check` | exit 0, 118 paquetes | `evidence/CLONE_f118e556_uv_lock_check.log` |
| `f118e556` | `pytest tests/unit/ops tests/unit/reports/test_evidence_manifest_eol.py -q` | **135 passed** | `evidence/CLONE_f118e556_pytest.log` |
| `f118e556` | `verify_repro.py` | **12/12 PASS**, 4/4 controles, `false_success 0` | `evidence/CLONE_f118e556_verify_repro.log` |
| `f118e556` | `paper_supervisor_verify.py --campaign …/campaign` | PASS 33/33, 12 mutaciones, `false_success 0` | — |
| `6ae20844` (cierre) | `verify_repro.py` | **12/12 PASS**, 4/4 controles, `false_success 0` | `evidence/CLONE_6ae20844_verify_repro.log` |
| `6ae20844` | `verify_independent.py` | **9/9 PASS** | `evidence/INDEPENDENT_VERIFICATION.json` |
| `6ae20844` | `pytest tests/unit/ops tests/unit/reports/test_evidence_manifest_eol.py -q` | **141 passed** | `evidence/CLONE_6ae20844_pytest.log` |
| `6ae20844` | `uv sync --frozen` + `uv lock --check` | 0 / 0 | `evidence/CLONE_6ae20844_uv_*.log` |

El fallo de `ddef6432` en un clon no es una regresión introducida después: es el mismo commit
que había pasado en un worktree con `core.autocrlf=false`. La diferencia era el entorno, y eso
es precisamente lo que un rehearsal de checkout limpio debe poder ver.

## Gates (sobre `f118e556`)

| Gate | Resultado |
| --- | --- |
| V01 documentos preservados byte-idénticos | PASS (7/7) |
| V02 manifiesto contra el árbol | PASS (46 digests) |
| V03 documentos ausentes en la base | PASS (`c44f912c`, probado con Git) |
| V04 auditoría windowless | PASS, HIGH 0 |
| V05 contrato `test_windowless` | PASS, 14 passed |
| V06 rechazo de esquema ajeno | PASS, `UNSUPPORTED_CAMPAIGN_SCHEMA`, 0 checks puntuados |
| V07 verificador de lock sobre su propio esquema | PASS, 33 checks, 10 mutaciones |
| V08 supervisor externo | PASS, 33 checks, 12 mutaciones, `false_success 0` |
| V09 lock reproducible | PASS |
| V10 dependencia declarada importable | PASS, `matplotlib 3.11.2` |
| V11 alcance respetado | PASS, 204 rutas, 0 fuera de allowlist |
| V12 admisión intacta | PASS, 0/24 admitidas, ledger byte-idéntico |

Controles negativos: `document_byte_flip`, `campaign_without_schema`,
`declared_local_hiding_removed`, `manifest_hash_tamper` — **4/4 detectados**.

## Verificación independiente

`verify_independent.py` (nuevo, sin código compartido con `verify_repro.py`): **9/9**.
Re-declara los siete digests, re-cuenta la admisión desde el JSON del ledger, re-ejecuta
auditoría, tests, supervisor, rechazo de esquema, lock y entorno, y comprueba por
`git check-attr` que ningún digest depende del checkout.

## Revisión de integración

```
main..f118e556  = 305 commits (301 de la lane supervisor + 4 del RFC)
f118e556..main  = 3 commits
git cherry-pick -n c44f912c sobre main → CONFLICT (7 ficheros)
```

Los siete conflictos son `deleted in HEAD and modified in c44f912c`: `main` no tiene
`src/trading_bot/ops/windowless.py`, `session_status.py`, `paper_lock_campaign_verify.py`,
`test_windowless.py`, `test_session_status.py` ni `test_paper_lock_campaign.py`. Fusionar la
rama entera traería la lane completa.

**Merge detenido → `NO_GO`.** `main` sigue en `e67194e7`; el checkout compartido conserva sus
entradas pendientes (26 al empezar, 28 al cerrar; ninguna de esta lane).

## Anomalías

- **A1** — 13 de 44 digests no reproducían en un clon con `core.autocrlf=true`. Corregido en
  `f118e556` con pines `-text`, diagnóstico `EOL_NORMALISED` y test de regresión.
- **A2** — El verificador independiente tenía dos fallos propios (leía `refusal` como cadena;
  contaba `STREAM.jsonl` de fixture como sesión abierta). Corregidos antes de usarlo como
  evidencia, sin rebajar ninguna comprobación.
- **A3** — El rehearsal de `ddef6432` no era un checkout independiente: compartía `.git` y
  heredaba `core.autocrlf=false`. Registrado, no reescrito.

## Defectos abiertos

`B1 LOCK_UNATTRIBUTED`, `B2 verify_claims.py no portable`, `B3 uv sync --frozen exit 0 ante
desajuste`, `B4 sin campaña de lock real` — detalle y criterio de cierre en
[OPEN_BLOCKERS.md](OPEN_BLOCKERS.md).

## Admisión PAPER

**`NO_GO`** — 0 de 24 estrategias, ledger byte-idéntico al base, 0 operaciones PAPER o LIVE.
