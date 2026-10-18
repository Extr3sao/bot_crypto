# RUN_REPORT — RFC-TAP-EVIDENCE-004 (generado)

Generado por `scripts/evidence004_generate.py` a partir de `reports/ai-bots/RFC-AI-BOTS-002/evidence-004/canonical/CANONICAL_RUN.json`.
`ledger_sha256`: `c5bc42ecccf86965effb52e505b3e0f9e3dadd5ea62ecb0b4bfbc0f43b629869`. No editar a mano: el verificador
independiente recalcula estos números desde los logs crudos y falla si no coinciden.

## Contadores

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

## Operaciones de esta iteración

**7 operaciones REA ejecutadas con `evidence_id`** en esta fase, de 9 de trabajo; 2 no se ejecutaron y la última columna lo dice. La clase de ejecución va en la celda de evidencia: un exit 0 sin `evidence_id` nunca cuenta como éxito.

| # | operación | sujeto | exit | `evidence_id` |
| --- | --- | --- | --- | --- |
| 1 | `git fetch / checkout` | `T-NF-NOF1` | 0 | — (`NON_REA_STEP`) |
| 2 | `analyze_javascript_application` | `T-NF-NOF1` | 0 | `ev_4b2bf9c5c…` (declarado) |
| 3 | `import-reference-source` | `T-NF-NOF1` | 1 | — (`BLOCKED_UNSUPPORTED_HOST`) |
| 4 | `compare-source-to-bundle` | `T-NF-NOF1` | 0 | — (`REFUSED_INVALID_INPUT`) |
| 5 | `analyze_javascript_application` | `T-QR-SIGNAL` | 0 | `ev_9b45318c0…` (declarado) |
| 6 | `analyze_javascript_application` | `T-FE-FENIX` | 0 | `ev_be8c7d74b…` (declarado) |
| 7 | `list_browser_targets` | `T-QR-SIGNAL` | 0 | `ev_4d5ba8ab1…` (declarado) |
| 8 | `analyze_web_bundle` | `T-QR-SIGNAL` | 0 | `ev_b954b8b01…` (declarado) |
| 9 | `analyze_web_bundle` | `T-FE-FENIX` | 0 | `ev_fc2b6552f…` (declarado) |
| 10 | `capture_web_screenshot` | `T-QR-SIGNAL` | 0 | `ev_ee6845ff7…` (verificado) |
| 11 | `capture_web_screenshot` | `T-FE-FENIX` | 0 | `ev_b3b1e8374…` (verificado) |

## Lo que la tabla no dice

- El exit code no decide nada: 1 operación(es) devolvieron exit 0 y aun así no se ejecutaron (`NOT_EXECUTED_INVALID_INPUT`).
- De las 7 operaciones con `evidence_id`, 2 tienen artefacto en disco cuyo sha256 coincide con el declarado; las otras 5 son evidencia **declarada**, no comprobada byte a byte.
- Ámbito ampliado: 12 `evidence_id` distintos en los cuatro dossiers, de 12 operaciones de trabajo. Es otro denominador, no una cifra mayor del mismo contador.
- Discovery separado del trabajo: 1 operación(es) de readiness en esta iteración (`list_browser_targets`), contadas aparte.
- Cero llamadas reales a un modelo, cero órdenes, cero cambios en `config/risk.yaml`.
- `REAL_MODEL_CALLED = false`; ningún patrón externo queda certificado por este informe.
