# FINAL_REPORT — RFC-TDM-014A

**Veredicto:** `VERIFIED_PORTABLE_FULL_REPLAY`
**Baseline:** `04fb8bc8a0900c278cd72c5e3478a45b66fcbc03` · **Árbol cubierto por el cierre:** `49c8969617e0effee3872b006efe45dc7fb266eb`
**Decisión económica (heredada, no reevaluada):** NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA (inherited from TDM-11/12/13, untouched)

## Qué se ha demostrado

- Dos replays fríos del mismo commit de implementación, uno en checkout LF y otro en CRLF, cada uno regenerando review, métricas por celda, inventario y registro sin reutilizar nada del intento anterior.
- La huella v2 coincide entre ambos checkouts mientras los bytes físicos difieren y el blob de Git es el mismo: D-01 queda cerrado sin tocar el contenido.
- Contratos del replay: 10/10 comparados por valor, no solo por hash.
- Controles negativos: 10/10 demostrados con exit no cero.
- Histórico v1: PASS — sin reescritura ni atribución retroactiva de huellas v2.

## Qué NO se afirma

- Independencia organizativa: `INDEPENDENCE_NOT_DEMONSTRATED`. Un operador escribió constructor y verificador; la ruta de código es distinta, la identidad no.
- Alpha, rentabilidad, slippage real, funding o fills: fuera de alcance y sin evaluar.
- Que la suite completa esté verde: 79 tests fallan en esta máquina también en la baseline, con conjuntos de fallo idénticos entre baseline y HEAD.
- Que `false_success=0` sea una garantía universal: es el resultado de los controles observados, no una propiedad del universo.

## Criterios de aceptación

| ACC | estado |
| --- | --- |
| ACC-01 | PASS |
| ACC-02 | PASS |
| ACC-03 | PASS |
| ACC-04 | PASS |
| ACC-05 | PASS |
| ACC-06 | PASS |
| ACC-07 | PASS |
| ACC-08 | PASS |
| ACC-09 | PASS |
| ACC-10 | PASS |
| ACC-11 | PASS |
| ACC-12 | PASS |

## Commits de la rama

- `a806a7bf Publish the regenerated deliverables and the closing report`
- `d7185a21 Render the closing report from the verdict instead of writing it by hand`
- `409050c3 Close the second evidence commit against its own blobs`
- `49c89696 Re-verify after the custody fix: twelve of twelve`
- `d93408e8 Stop the custody check from mangling the first dirty path`
- `5f42de14 Close the first evidence commit against its own blobs`
- `f8ae0243 Replay TDM-12 from scratch twice and publish the evidence`
- `7a4593cb Keep the sealed TDM-13 inputs byte-identical in a CRLF checkout`
- `04b02c2d Fingerprint the committed blob so a checkout cannot rename the code`

## Ejecuciones

| run_id | core.autocrlf | estado | duración | outputs generados |
| --- | --- | --- | --- | --- |
| `tdm14a-lf-20261025T181821Z` | `false` | PASS | 419.7 s | 5/5 |
| `tdm14a-crlf-20261025T182823Z` | `true` | PASS | 386.1 s | 5/5 |

## Defectos

| id | estado | detalle |
| --- | --- | --- |
| `D-01` | FIXED | v1 hashed working-tree bytes, so the same blob produced two identities under LF and CRLF; v2 hashes the blob (ACC-02 reproduced, ACC-03 fixed). |
| `D-02` | DOCUMENTED, NOT REWRITTEN | tdm12_inventory.py hardcoded source_commit='504256ec' as a literal, so no TDM-12 artefact recorded the commit it actually ran at. v2 derives it from git HEAD; v1 keeps the literal only to reproduce the published artefact. |
| `D-03` | FIXED | the sealed TDM-13 input bundle had no -text attribute, so a CRLF checkout delivered 189575 bytes instead of 189574 and the replay could not start. Fixed in .gitattributes, which is why the CRLF run now reaches the pipeline. |
| `D-04` | FIXED IN THIS WORK, FOUND BY THE TESTS | the first v2 preflight used git status as its cleanliness oracle; on a CRLF checkout status reports ' M path' for content identical to the blob, which would have refused the only transformation the RFC tolerates. Replaced with content hash-object --path plus diff-index --cached. |
| `D-05` | OPEN, REPORTED | identity fields outside the registry (triage.json admission_ledger.sha256, runtime_entrypoints sha256) still hash working-tree bytes, so those scratch values remain EOL-sensitive. They are not published contracts and do not enter any ACC. |

## Cadena de custodia

Por construcción el informe de cierre se commitea *después* del árbol que verifica, así que HEAD puede estar exactamente un commit por delante: el diff entre ambos es solo `POST_COMMIT_CLOSURE.json`.

- ficheros comprobados contra el HEAD del cierre: 25
- coincidentes: 25
- excluido por construcción: `['evidence/tdm/wp-tdm-14a/POST_COMMIT_CLOSURE.json']`
- estado del cierre: `PASS`

## Órdenes

- `paper_orders = 0` · `live_orders = 0`
- `false_success = 0`

## Siguiente paso autorizado

Ninguno dentro de este RFC. Diagnosticar la causa económica de `NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA` requiere un RFC nuevo.
