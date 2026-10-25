# Informe ejecutivo — cifras derivadas

Derivado de `reports/ai-bots/RFC-AI-BOTS-002/evidence-004/canonical/CANONICAL_RUN.json` (`ledger_sha256` `c5bc42ecccf86965…`).

<!-- EVIDENCE004:COUNTS:BEGIN -->

Números canónicos (generado por `scripts/evidence004_generate.py`; no editar a mano).

| contador | valor |
| --- | --- |
| `phase_v31.work.operations` | 9 |
| `phase_v31.work.executed_with_evidence_id` | 7 |
| `phase_v31.work.executed_with_verified_artifact` | 2 |
| `phase_v31.work.not_executed` | 2 |
| `phase_v31.distinct_evidence_ids` | 8 |
| `all_dossiers.work.executed_with_evidence_id` | 10 |
| `all_dossiers.work.not_executed` | 2 |
| `all_dossiers.distinct_evidence_ids` | 12 |

Los dos ámbitos no se suman: `phase_v31` cubre el trabajo de esta iteración y
`all_dossiers` cubre todo lo registrado en los cuatro dossiers, con otro denominador.

<!-- EVIDENCE004:COUNTS:END -->

## Lectura en tres frases

1. En esta iteración hubo 9 operaciones REA de trabajo: 7 devolvieron `evidence_id` y 2 no llegaron a ejecutarse.
2. Sólo 2 de esas evidencias tienen artefacto verificado por hash en este repositorio; el resto está declarado en los dossiers.
3. Los cuatro dossiers completos suman 12 `evidence_id` distintos — otro ámbito, no la misma cifra.

## Lo que no se puede afirmar

- Ninguna llamada real a un modelo multimodal: `REAL_MODEL_CALLED = false`.
- Ningún patrón externo certificado: `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`.
- Ninguna rentabilidad: los runs son mock y no miden edge.
