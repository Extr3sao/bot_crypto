# RUN_REPORT — v3.1

| # | operación | sujeto | exit | `evidence_id` |
| --- | --- | --- | --- | --- |
| 1 | `git fetch` commit exacto | `195440/nof1.ai@5d27641dfa47…` | 0 | — |
| 2 | `analyze_javascript_application` | `nof1/public` | 0 | `ev_4b2bf9c5…` |
| 3 | `import-reference-source` | `nof1` | **1** | — (`unsupported_host`) |
| 4 | `compare-source-to-bundle` | `nof1` | 0 | — (`invalid_input`, sin productor de graph) |
| 5 | `analyze_javascript_application` | `qrak/src/dashboard/static` | 0 | `ev_9b45318c…` |
| 6 | `analyze_web_bundle` | `127.0.0.1:8124` | 0 | `ev_b954b8b0…` |
| 7 | `capture_web_screenshot` | `127.0.0.1:8124` | 0 | `ev_ee6845ff…` |
| 8 | `npm ci` + `vite build` | `fenix/frontend` | 0 | — (285 paquetes, 2367 módulos) |
| 9 | `analyze_javascript_application` | `fenix/frontend/dist` | 0 | `ev_be8c7d74…` |
| 10 | `analyze_web_bundle` | `127.0.0.1:8123` | 0 | `ev_fc2b6552…` |
| 11 | `capture_web_screenshot` | `127.0.0.1:8123` | 0 | `ev_b3b1e837…` |

**9 operaciones REA con exit 0, 2 bloqueadas y declaradas.** Cero órdenes, cero claves, cero
cambios en `config/risk.yaml`.
