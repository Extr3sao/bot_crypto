# RUN_REPORT — v3.1

| # | operación | sujeto | exit | `evidence_id` |
| --- | --- | --- | --- | --- |
| 1 | `git fetch` commit exacto | `195440/nof1.ai@5d27641dfa47…` | 0 | — |
| 2 | `analyze_javascript_application` | `nof1/public` | 0 | `ev_4b2bf9c5…` |
| 3 | `import-reference-source` | `nof1` | **1** | — (`unsupported_host`) |
| 4 | `compare-source-to-bundle` | `nof1` | 0 | — (`NOT_EXECUTED_INVALID_INPUT`, sin productor de graph) |
| 5 | `analyze_javascript_application` | `qrak/src/dashboard/static` | 0 | `ev_9b45318c…` |
| 6 | `analyze_web_bundle` | `127.0.0.1:8124` | 0 | `ev_b954b8b0…` |
| 7 | `capture_web_screenshot` | `127.0.0.1:8124` | 0 | `ev_ee6845ff…` |
| 8 | `npm ci` + `vite build` | `fenix/frontend` | 0 | — (285 paquetes, 2367 módulos) |
| 9 | `analyze_javascript_application` | `fenix/frontend/dist` | 0 | `ev_be8c7d74…` |
| 10 | `analyze_web_bundle` | `127.0.0.1:8123` | 0 | `ev_fc2b6552…` |
| 11 | `capture_web_screenshot` | `127.0.0.1:8123` | 0 | `ev_b3b1e837…` |

**7 operaciones REA ejecutadas con `evidence_id` en esta tabla; 2 no se ejecutaron y lo dicen:**
`import-reference-source` (exit 1, `unsupported_host`) y `compare-source-to-bundle` (exit **0**
con resultado `NOT_EXECUTED_INVALID_INPUT`). El exit 0 de la fila 4 **no cuenta como ejecución**:
REA rechazó la entrada porque exige un `HistoricalSourceGraph` que sólo produce el comando que
falló en este host. Contarlo por el código de salida sería el `FALSE_SUCCESS` que este RFC
prohíbe, y `scripts/ai_bots_rea_verify.py` lo comprueba fila por fila.

La tabla es un resumen: los dossiers guardan **12 `evidence_id`** distintos (incluye
`list_browser_targets` y la captura de la página pública que no figuran arriba).

Cero órdenes, cero claves, cero cambios en `config/risk.yaml`.
