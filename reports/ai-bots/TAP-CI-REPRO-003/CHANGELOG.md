# CHANGELOG — RFC-TAP-CI-003

Todos los commits están sobre `base a83ac165` (rama `fix/ci-repro-003`, PR #53).
No se reescribió `main` ni se fusionó la PR #18.

| Commit | Qué hace | Ficheros |
| --- | --- | --- |
| `4ec7a7cd` | Corrige el contrato de `--check` y regenera la cadena de evidencia | `scripts/active_economic_audit.py`, `tests/unit/research/test_cost_barrier_gate.py`, `data/recovery/ACTIVE_ECONOMIC_AUDIT.{json,md}`, `data/recovery/COST_BARRIER_EXPLORER.{json,md}`, `data/recovery/COST_BARRIER_VERIFICATION.json`, `data/recovery/wp7/evidence/{INPUT_EVIDENCE,PRODUCER_PINS}.json` |
| `d62ecb76` | Re-emite la certificación sobre la evidencia nueva | `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` |
| `09a137c1` | Re-ejecuta el rehearsal sobre los artefactos regenerados y añade el check read-only a CI | `data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.{json,md}`, `.github/workflows/recovery-determinism.yml` |
| `7a6260ad` | Sube la evidencia oculta y lo fija con tests | `.github/workflows/{cost-barrier-gate,recovery-determinism}.yml`, `tests/unit/research/test_{cost_barrier,recovery}_ci_parity.py` |
| `63950a72` | Re-fingerprint de la certificación tras cambiar el workflow | `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` |
| `eda14ae4` | Registra la verificación independiente en el commit probado | `data/recovery/INDEPENDENT_VERIFICATION.json` |

## 1. `active_economic_audit.py --check` (B14b)

Antes:

```python
OUT.mkdir(parents=True, exist_ok=True)
payload = build()
payload["payload_sha256"] = payload_hash(payload)
(OUT / "ACTIVE_ECONOMIC_AUDIT.json").write_text(...)   # escribe
(OUT / "ACTIVE_ECONOMIC_AUDIT.md").write_text(...)     # escribe
if args.check:
    stored = read_json("data/recovery/ACTIVE_ECONOMIC_AUDIT.json")  # lee lo recién escrito
    same = stored.get("payload_sha256") == payload["payload_sha256"]  # siempre True
```

Ahora:

- `--check` reconstruye **en memoria** y no abre ningún fichero en escritura.
- Rechaza `MISSING`, `UNREADABLE`, `INCOMPLETE` (secciones obligatorias ausentes o `checks` vacío).
- Rechaza `TAMPERED` cuando el `payload_sha256` publicado no recomputa de su propio cuerpo o
  cuando `checks_failed` contradice su lista de checks.
- Rechaza la certificación si el rebuild falla sus propios checks.
- Distingue `ECONOMIC_DRIFT` (alguna conclusión económica cambió) de `STALE_PROVENANCE`
  (sólo se movió procedencia: entrypoints, sources, input_authority, momento, rama).
- Códigos: `0` CURRENT, `1` stale/drift, `2` inutilizable. `main(argv)` es invocable desde tests.

La escritura normal usa `newline="\n"` para que un Windows no convierta el artefacto a CRLF.

## 2. Tests de productores (B13)

Los dos tests exigían `PIN_EXACT`. El manifiesto declara:

> "a consumer must accept a watched producer whose bytes equal the pinned content in LF or CRLF
> form (`sha256_lf` / `sha256_crlf`); `sha256` records the bytes of the tree that wrote this
> manifest and is informational only."

Se alineó la expectativa con ese contrato (`EXACT` o `EOL_ONLY`; `DRIFT` sigue siendo fallo) y se
añadieron dos regresiones:

- `test_a_producer_is_the_same_content_in_either_line_ending_convention`: escribe los cuatro
  productores en LF y en CRLF y exige que ninguno derive; después introduce una edición real en
  ambas convenciones y exige `DRIFT` exactamente en ese productor.
- `test_an_absent_producer_is_never_a_match`: un productor ausente queda `ABSENT`, nunca PASS.

No se borró ningún check ni se relajó la detección de contenido.

## 3. Regeneración de la cadena (B14a)

| Artefacto | Identidad antes | Identidad después |
| --- | --- | --- |
| `ACTIVE_ECONOMIC_AUDIT.json` | `023b66ff…` | `c6ea3438…` |
| `COST_BARRIER_EXPLORER.json` | `4383d812…` | `0ab1ac23…` |
| `COST_BARRIER_CERTIFICATION.json` | `0cfdb13e…` | `5a79ebe3…` |

El diff de la auditoría, comparado campo a campo contra el artefacto publicado:

```
identity changed sections: ['entrypoints']
economic findings identical: True
strategies True · aggregates True · cost_plane True · checks True · answers True
entrypoint changed: scripts/start_paper_trading.py
  8cd8832010353ff10d1e1b04287720d40e732d61b1313683c20c54b76f0d0106
→ 5d7c59cd779c7e91bb9e36094870a5df10945131c4ae91dec277eeb8f8d27251
```

El explorer se reconstruyó porque `sources[]` fija el `state_sha256` de la auditoría; su
verificador independiente volvió a dar `PASS` (13/13 controles, `false_success 0`). El manifiesto
de productores se re-pinnó en el mismo commit y el certificador se re-emitió dos veces: la primera
para que el registro dejara de estar obsoleto respecto al árbol (el propio test de certificación lo
comprueba), la segunda para obtener `CERTIFIED`. La supersesión conserva fingerprint, head y digest
de la tabla de evidencia del registro anterior.

## 4. Workflow de recovery

Se añadió el paso:

```yaml
- name: The published audit is current (read-only check)
  run: uv run python scripts/active_economic_audit.py --check
```

Es el modo que CI necesita: no puede reescribir el artefacto que está juzgando.

## 5. Empaquetado de evidencia (B15)

```yaml
include-hidden-files: true
```

en los dos `upload-artifact@v4`, más una aserción en cada test de paridad. Sin esto,
`cost-barrier-gate` fallaba en el paso 10 con todo lo demás verde, y `recovery-determinism`
publicaba un artefacto sin `.ci/`.

## 6. Rehearsal

Re-ejecutado en un worktree detached del commit `d62ecb76`: `PASS`, los cuatro artefactos
derivados idénticos (`CAMPAIGN_STATE_VIEW.json/.md`, `ACTIVE_ECONOMIC_AUDIT.json/.md`),
`published_paths_moved: []`, y la auditoría referenciada por `c6ea3438` en ambos lados.

## 7. Lo que no se tocó

`git diff --name-only a83ac165..HEAD -- config/ src/trading_bot/risk/ docs/COST_MODEL_V3.json
src/trading_bot/research/microstructure/cost_model_v3.py .github/workflows/ci.yml
.github/workflows/integration-gate.yml` → **vacío**. No cambió ningún límite, coste, umbral de
admisión ni required check.
